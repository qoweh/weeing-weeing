"""실제 문서 E2E 검증(#28). 저장소 하나에 대해 색인·멱등·갱신·검색 품질을 확인한다.

    run_backend(이름, store, corpus, Indexer 만드는 함수, 질의들)
      1. 색인      sync(corpus) → 문서별 청크 수, 걸린 시간
      2. 멱등      한 번 더 sync → 전부 unchanged여야 한다
      3. 검색      dense·hybrid, retriever 주입 시 reranked 상위 k개와 정답 순위
      4. 갱신      첫 문서의 버전만 올린 평가 자료 목록로 sync → 그 문서만 updated,
                   청크가 모두 새 버전이고 수는 같아야 한다(#7 완료 조건)
      5. 메타데이터 #6이 채울 키(section·page·codes·citation)가 빠진 청크 수

정답 판정은 청크 ID가 아니라 "기대 문서 + 기대 키워드"로 한다. 청크 ID는 청킹 방식에 따라
달라지기 때문이다. 질의 파일 형식은 data/eval/rag_queries_v1.toml.
질의는 문장(query) 또는 Incident 코드(codes → rag.query.codes_query로 질의문 생성)로 쓴다.
"""

import time
import tomllib
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from weeing_weeing.contracts import CODES, Evidence
from weeing_weeing.rag.eval_corpus import EvalCorpus
from weeing_weeing.rag.eval_sync import SyncReport, sync
from weeing_weeing.rag.interface import Indexer, Retriever
from weeing_weeing.rag.query import codes_query
from weeing_weeing.rag.store import Chunk, Embedder, Hit, VectorStore

MODES = ("dense", "hybrid")
# #6 Indexer가 파싱해서 채울 메타데이터. 없으면 #8의 인용·필터가 약해진다.
PARSED_KEYS = ("section", "page", "codes", "citation")
UPDATE_SUFFIX = "-e2e"


class EvaluationEmbedder:
    """한 평가 실행에서 동일한 입력의 임베딩만 재사용한다.

    문서와 질문은 서로 다른 인코딩 설정을 쓸 수 있어 캐시를 분리한다.
    문서는 배치 전체를 키로 삼아 최초 계산의 배치 구성도 유지한다.
    저장소 쓰기·검색·갱신 검사는 생략하지 않으며 디스크에는 캐시하지 않는다.
    """

    def __init__(self, embedder: Embedder) -> None:
        self._embedder: Embedder | None = embedder
        self._documents: dict[tuple[str, ...], list[list[float]]] = {}
        self._queries: dict[str, list[float]] = {}

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        key = tuple(texts)
        if key not in self._documents:
            if self._embedder is None:
                raise ValueError("고정된 평가 임베딩 캐시에 없는 문서 입력입니다.")
            vectors = self._embedder.embed_documents(texts)
            if len(vectors) != len(texts):
                raise ValueError("임베더가 청크 수와 다른 개수의 벡터를 돌려줬다")
            self._documents[key] = [list(vector) for vector in vectors]
        return [vector.copy() for vector in self._documents[key]]

    def embed_query(self, text: str) -> list[float]:
        if text not in self._queries:
            if self._embedder is None:
                raise ValueError("고정된 평가 임베딩 캐시에 없는 질의 입력입니다.")
            self._queries[text] = list(self._embedder.embed_query(text))
        return self._queries[text].copy()

    def freeze(self) -> None:
        """계산한 벡터만 보관하고 모델 참조를 해제한다. 새 입력은 오류로 알린다."""
        self._embedder = None


class QueryError(ValueError):
    """질의 파일이 잘못됐다."""


class EvalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    query: str | None = Field(default=None, min_length=1)
    # Incident 코드. 질의문은 rag.query로 만든다
    codes: tuple[str, ...] | None = Field(default=None, min_length=1)
    doc_id: str | None = Field(default=None, min_length=1)
    any_of: tuple[str, ...] = ()  # 정답 청크 본문에 있어야 할 키워드
    expect_no_evidence: bool = Field(default=False, strict=True)
    where: dict[str, str | list[str]] | None = None

    @model_validator(mode="after")
    def _query_or_codes(self) -> "EvalQuery":
        if (self.query is None) == (self.codes is None):
            raise ValueError(f"{self.id}: query와 codes 중 하나만 쓴다")
        unknown = [c for c in self.codes or () if c not in CODES]
        if unknown:
            raise ValueError(f"{self.id}: 정의되지 않은 코드 {unknown}")
        if self.expect_no_evidence:
            if self.doc_id is not None or self.any_of:
                raise ValueError(
                    f"{self.id}: 근거 없음 질의에는 정답 문서·키워드를 쓰지 않는다"
                )
        elif self.doc_id is None or not self.any_of:
            raise ValueError(f"{self.id}: 정답 문서와 키워드가 필요하다")
        return self

    @property
    def text(self) -> str:
        """검색에 넣을 질의문. codes면 Incident 질의문과 같은 방식으로 만든다."""
        return self.query if self.query is not None else codes_query(self.codes)


def load_queries(path: str | Path) -> list[EvalQuery]:
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        queries = [EvalQuery(**q) for q in raw.get("queries", [])]
    except (OSError, tomllib.TOMLDecodeError, ValidationError, TypeError) as exc:
        raise QueryError(f"{path}: {exc}") from exc
    dup = [i for i, n in Counter(q.id for q in queries).items() if n > 1]
    if dup:
        raise QueryError(f"{path}: 질의 id 중복 {dup}")
    return queries


def is_hit(chunk: Chunk | Evidence, query: EvalQuery) -> bool:
    return chunk.doc_id == query.doc_id and any(k in chunk.text for k in query.any_of)


@dataclass
class QueryResult:
    query_id: str
    mode: str  # dense | hybrid | reranked
    rank: int | None  # 첫 정답의 순위(1부터). 상위 k개 안에 없으면 None
    top: list[Hit] | list[Evidence]
    expect_no_evidence: bool = False


@dataclass(frozen=True)
class ModeSummary:
    backend: str
    mode: str
    total: int
    hit_at_1: int
    hit_at_k: int
    mrr: float  # 정답 질의만 집계. 1위면 1, 2위면 0.5, 없으면 0
    no_evidence_total: int = 0
    rejected: int = 0  # 근거 없음 질의에서 실제로 빈 결과를 반환한 수


@dataclass
class BackendResult:
    backend: str
    indexed: SyncReport
    index_seconds: float
    chunk_counts: dict[str, int]
    rerun_unchanged: bool
    update_ok: bool
    update_detail: str
    missing_metadata: dict[str, int]
    results: list[QueryResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """색인·멱등·갱신 검사가 모두 통과했다. 검색 품질은 숫자로만 남긴다."""
        return self.indexed.ok and self.rerun_unchanged and self.update_ok

    def summaries(self) -> list[ModeSummary]:
        out = []
        modes = list(MODES)
        if any(r.mode == "reranked" for r in self.results):
            modes.append("reranked")
        for mode in modes:
            measured = [r for r in self.results if r.mode == mode]
            rs = [r for r in measured if not r.expect_no_evidence]
            negatives = [r for r in measured if r.expect_no_evidence]
            out.append(
                ModeSummary(
                    backend=self.backend,
                    mode=mode,
                    total=len(rs),
                    hit_at_1=sum(r.rank == 1 for r in rs),
                    hit_at_k=sum(r.rank is not None for r in rs),
                    mrr=sum(1 / r.rank for r in rs if r.rank) / len(rs) if rs else 0.0,
                    no_evidence_total=len(negatives),
                    rejected=sum(not r.top for r in negatives),
                )
            )
        return out


def _search(
    store: VectorStore, query: EvalQuery, k: int, retriever: Retriever | None
) -> list[QueryResult]:
    found: dict[str, list[Hit] | list[Evidence]] = {
        "dense": store.query(query.text, k=k, where=query.where),
        "hybrid": store.hybrid_query(query.text, k=k, where=query.where),
    }
    if retriever is not None:
        found["reranked"] = retriever.search(query.text, k=k, filters=query.where)
    results = []
    for mode, top in found.items():
        rank = next(
            (
                i
                for i, h in enumerate(top, 1)
                if is_hit(h.chunk if isinstance(h, Hit) else h, query)
            ),
            None,
        )
        results.append(QueryResult(query.id, mode, rank, top, query.expect_no_evidence))
    return results


def _check_update(
    store: VectorStore, corpus: EvalCorpus, indexer: Indexer, before: dict[str, int]
) -> tuple[bool, str]:
    """첫 문서의 버전만 올린 평가 자료 목록로 sync한다. 파일은 그대로 쓴다."""
    target = corpus.documents[0]
    new_version = target.doc_version + UPDATE_SUFFIX
    bumped = corpus.model_copy(
        update={
            "documents": [
                e.model_copy(update={"doc_version": new_version}) if e is target else e
                for e in corpus.documents
            ]
        }
    )
    report = sync(bumped, indexer, store)
    chunks = store.chunks(where={"doc_id": target.doc_id})
    versions = {c.doc_version for c in chunks}
    problems = []
    if report.updated != [target.doc_id] or report.failed:
        problems.append(f"updated={report.updated} failed={list(report.failed)}")
    if versions != {new_version}:
        problems.append(f"남은 버전 {sorted(versions)}")
    if len(chunks) != before.get(target.doc_id):
        problems.append(f"청크 수 {before.get(target.doc_id)} → {len(chunks)}")
    detail = f"{target.doc_id} {target.doc_version} → {new_version}: " + (
        "; ".join(problems) if problems else f"옛 청크 0, 새 청크 {len(chunks)}"
    )
    return not problems, detail


def run_backend(
    name: str,
    store: VectorStore,
    corpus: EvalCorpus,
    make_indexer: Callable[[VectorStore], Indexer],
    queries: Sequence[EvalQuery],
    *,
    k: int = 5,
    retriever: Retriever | None = None,
    progress: Callable[[str], None] | None = None,
    prepare_search: Callable[[], None] | None = None,
) -> BackendResult:
    """빈 저장소에서 시작한다. 갱신 검사가 첫 문서의 버전을 바꿔 두므로 끝난 뒤 버린다."""
    indexer = make_indexer(store)
    started = time.perf_counter()
    if progress is not None:
        progress(f"[{name}] 색인 시작: 문서 {len(corpus.documents)}개")
    indexed = sync(corpus, indexer, store)
    seconds = time.perf_counter() - started
    counts = {d: info.chunk_count for d, info in store.documents().items()}
    if progress is not None:
        progress(
            f"[{name}] 색인 완료: {seconds:.1f}초, "
            f"청크 {sum(counts.values())}개, 실패 {len(indexed.failed)}개"
        )
        progress(f"[{name}] 멱등·메타데이터 검사 시작")
    rerun = sync(corpus, indexer, store)
    all_chunks = store.chunks()
    missing = {
        key: sum(key not in c.metadata for c in all_chunks) for key in PARSED_KEYS
    }
    # 빈 색인을 근거 없음 질의의 성공으로 집계하지 않는다.
    results = []
    if indexed.ok:
        if prepare_search is not None:
            prepare_search()
        for i, query in enumerate(queries, 1):
            query_started = time.perf_counter()
            if progress is not None:
                progress(f"[{name}] 질의 {i}/{len(queries)} {query.id} 시작")
            results.extend(_search(store, query, k, retriever))
            if progress is not None:
                progress(
                    f"[{name}] 질의 {i}/{len(queries)} {query.id} 완료: "
                    f"{time.perf_counter() - query_started:.1f}초, "
                    f"누적 {time.perf_counter() - started:.1f}초"
                )
    if progress is not None:
        progress(
            f"[{name}] 갱신 검사 시작" if indexed.ok else f"[{name}] 초기 색인 실패"
        )
    update_ok, detail = (
        _check_update(store, corpus, indexer, counts)
        if indexed.ok
        else (False, "초기 색인 실패: 검색 품질·갱신 미측정")
    )
    if progress is not None:
        progress(f"[{name}] 검사 종료: 총 {time.perf_counter() - started:.1f}초")
    return BackendResult(
        backend=name,
        indexed=indexed,
        index_seconds=seconds,
        chunk_counts=counts,
        rerun_unchanged=rerun.ok
        and not (rerun.added or rerun.updated or rerun.removed),
        update_ok=update_ok,
        update_detail=detail,
        missing_metadata=missing,
        results=results,
    )


def _mark(ok: bool) -> str:
    return "통과" if ok else "**실패**"


def format_markdown(runs: Sequence[BackendResult], *, k: int) -> str:
    lines = ["# RAG E2E 검증 결과", "", "## 검색 비교", ""]
    lines += [f"| 백엔드 | 방식 | hit@1 | hit@{k} | MRR |", "|---|---|---|---|---|"]
    for run in runs:
        for s in run.summaries():
            values = (
                f"{s.hit_at_1}/{s.total} | {s.hit_at_k}/{s.total} | {s.mrr:.3f}"
                if s.total
                else "- | - | -"
            )
            lines.append(f"| {s.backend} | {s.mode} | {values} |")
    lines += [
        "",
        "## 근거 없음 질의",
        "",
        "순위 지표는 정답이 있는 질의만 집계한다. 거절은 실제 빈 결과일 때만 성공이다.",
        "| 백엔드 | 방식 | 거절 / 근거 없음 질의 | 오반환 |",
        "|---|---|---|---|",
    ]
    for run in runs:
        for s in run.summaries():
            values = (
                f"{s.rejected}/{s.no_evidence_total} | {s.no_evidence_total - s.rejected}"
                if s.no_evidence_total
                else "- | -"
            )
            lines.append(f"| {s.backend} | {s.mode} | {values} |")
    lines += [
        "",
        "## 반환 1위 관련도 분포",
        "",
        "필터를 끈 실행으로 기준값을 검토한다. 미측정(None)은 0으로 대체하지 않는다.",
        "| 백엔드 | 질의 종류 | 측정 수 | 최소 | 평균 | 최대 |",
        "|---|---|---|---|---|---|",
    ]
    for run in runs:
        for negative, label in ((False, "정답 있음"), (True, "근거 없음")):
            scores = [
                r.top[0].relevance
                for r in run.results
                if r.mode == "reranked"
                and r.expect_no_evidence == negative
                and r.top
                and r.top[0].relevance is not None
            ]
            values = (
                f"{min(scores):.4f} | {sum(scores) / len(scores):.4f} | {max(scores):.4f}"
                if scores
                else "- | - | -"
            )
            lines.append(f"| {run.backend} | {label} | {len(scores)} | {values} |")
    lines += ["", "## 색인·갱신", ""]
    lines += [
        "| 백엔드 | 색인(초) | 문서별 청크 수 | 실패 | 멱등(재실행 unchanged) | 갱신 |",
        "|---|---|---|---|---|---|",
    ]
    for run in runs:
        counts = ", ".join(f"{d} {n}" for d, n in sorted(run.chunk_counts.items()))
        failed = ", ".join(run.indexed.failed) or "-"
        lines.append(
            f"| {run.backend} | {run.index_seconds:.1f} | {counts} | {failed} "
            f"| {_mark(run.rerun_unchanged)} | {_mark(run.update_ok)} |"
        )
    lines.append("")
    lines += [f"- {run.backend} 갱신: {run.update_detail}" for run in runs]
    for run in runs:
        if run.indexed.failed:
            lines += [
                f"- {run.backend} 실패 {d}: {m}" for d, m in run.indexed.failed.items()
            ]
    first = runs[0] if runs else None
    if first:
        total = sum(first.chunk_counts.values())
        lines += [
            "",
            f"## #6이 채울 메타데이터가 빠진 청크 ({first.backend}, 전체 {total})",
            "",
        ]
        lines += [f"- `{key}`: {n}" for key, n in first.missing_metadata.items()]
        lines += ["", f"## 질의별 상위 {k}개 ({first.backend})", ""]
        for r in first.results:
            if r.expect_no_evidence:
                outcome = "근거 없음 거절 성공" if not r.top else "근거 오반환"
            else:
                outcome = f"정답 {r.rank}위" if r.rank else "정답 없음"
            lines.append(f"- **{r.query_id}** {r.mode} {outcome}")
            for i, h in enumerate(r.top, 1):
                source = h.chunk if isinstance(h, Hit) else h
                source_id = h.chunk.chunk_id if isinstance(h, Hit) else h.evidence_id
                relevance = (
                    f"{h.relevance:.4f}" if h.relevance is not None else "미측정"
                )
                lines.append(
                    f"  {i}. `{source_id}` relevance={relevance} {source.text[:40]!r}"
                )
    return "\n".join(lines) + "\n"
