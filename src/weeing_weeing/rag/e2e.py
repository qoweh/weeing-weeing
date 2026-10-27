"""실제 문서 E2E 검증(#28). 저장소 하나에 대해 색인·멱등·갱신·검색 품질을 확인한다.

    run_backend(이름, store, catalog, Indexer 만드는 함수, 질의들)
      1. 색인      sync(catalog) → 문서별 청크 수, 걸린 시간
      2. 멱등      한 번 더 sync → 전부 unchanged여야 한다
      3. 검색      dense·hybrid, retriever 주입 시 reranked 상위 k개와 정답 순위
      4. 갱신      첫 문서의 버전만 올린 카탈로그로 sync → 그 문서만 updated,
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
from weeing_weeing.rag.catalog import Catalog
from weeing_weeing.rag.interface import Indexer, Retriever
from weeing_weeing.rag.query import codes_query
from weeing_weeing.rag.store import Chunk, Hit, VectorStore
from weeing_weeing.rag.sync import SyncReport, sync

MODES = ("dense", "hybrid")
# #6 Indexer가 파싱해서 채울 메타데이터. 없으면 #8의 인용·필터가 약해진다.
PARSED_KEYS = ("section", "page", "codes", "citation")
UPDATE_SUFFIX = "-e2e"


class QueryError(ValueError):
    """질의 파일이 잘못됐다."""


class EvalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    query: str | None = Field(default=None, min_length=1)
    # Incident 코드. 질의문은 rag.query로 만든다
    codes: tuple[str, ...] | None = Field(default=None, min_length=1)
    doc_id: str = Field(min_length=1)  # 정답이 있어야 할 문서
    any_of: tuple[str, ...] = Field(min_length=1)  # 정답 청크 본문에 있어야 할 키워드
    where: dict[str, str | list[str]] | None = None

    @model_validator(mode="after")
    def _query_or_codes(self) -> "EvalQuery":
        if (self.query is None) == (self.codes is None):
            raise ValueError(f"{self.id}: query와 codes 중 하나만 쓴다")
        unknown = [c for c in self.codes or () if c not in CODES]
        if unknown:
            raise ValueError(f"{self.id}: 정의되지 않은 코드 {unknown}")
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


@dataclass(frozen=True)
class ModeSummary:
    backend: str
    mode: str
    total: int
    hit_at_1: int
    hit_at_k: int
    mrr: float  # 정답 순위 역수의 평균. 1위면 1, 2위면 0.5, 없으면 0


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
            rs = [r for r in self.results if r.mode == mode]
            out.append(
                ModeSummary(
                    backend=self.backend,
                    mode=mode,
                    total=len(rs),
                    hit_at_1=sum(r.rank == 1 for r in rs),
                    hit_at_k=sum(r.rank is not None for r in rs),
                    mrr=sum(1 / r.rank for r in rs if r.rank) / len(rs) if rs else 0.0,
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
        results.append(QueryResult(query.id, mode, rank, top))
    return results


def _check_update(
    store: VectorStore, catalog: Catalog, indexer: Indexer, before: dict[str, int]
) -> tuple[bool, str]:
    """첫 문서의 버전만 올린 카탈로그로 sync한다. 파일은 그대로 쓴다."""
    target = catalog.documents[0]
    new_version = target.doc_version + UPDATE_SUFFIX
    bumped = catalog.model_copy(
        update={
            "documents": [
                e.model_copy(update={"doc_version": new_version}) if e is target else e
                for e in catalog.documents
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
    catalog: Catalog,
    make_indexer: Callable[[VectorStore], Indexer],
    queries: Sequence[EvalQuery],
    *,
    k: int = 5,
    retriever: Retriever | None = None,
) -> BackendResult:
    """빈 저장소에서 시작한다. 갱신 검사가 첫 문서의 버전을 바꿔 두므로 끝난 뒤 버린다."""
    indexer = make_indexer(store)
    started = time.perf_counter()
    indexed = sync(catalog, indexer, store)
    seconds = time.perf_counter() - started
    counts = {d: info.chunk_count for d, info in store.documents().items()}
    rerun = sync(catalog, indexer, store)
    all_chunks = store.chunks()
    missing = {
        key: sum(key not in c.metadata for c in all_chunks) for key in PARSED_KEYS
    }
    results = [r for q in queries for r in _search(store, q, k, retriever)]
    update_ok, detail = _check_update(store, catalog, indexer, counts)
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
            lines.append(
                f"| {s.backend} | {s.mode} | {s.hit_at_1}/{s.total} "
                f"| {s.hit_at_k}/{s.total} | {s.mrr:.3f} |"
            )
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
            got = f"{r.rank}위" if r.rank else "없음"
            lines.append(f"- **{r.query_id}** {r.mode} 정답 {got}")
            for i, h in enumerate(r.top, 1):
                source = h.chunk if isinstance(h, Hit) else h
                source_id = h.chunk.chunk_id if isinstance(h, Hit) else h.evidence_id
                lines.append(f"  {i}. `{source_id}` {source.text[:40]!r}")
    return "\n".join(lines) + "\n"
