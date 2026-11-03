"""rag 내부 저장 계층 계약. #6(색인)·#7(저장)·#8(검색)이 이 모양으로 만난다.

rag 모듈 안에서만 쓴다. 다른 모듈은 rag/interface.py만 import한다.

[색인] 파싱·청킹 → list[Chunk] → store.replace_document(doc_id, chunks)
       └ 저장소 안에서 임베딩(dense)·sparse 인코딩 → DB 저장
[검색] 질의문·where → store.hybrid_query(text, k=…, where=…) → list[Hit]
       └ 저장소 안에서 질의 임베딩 → dense+sparse 검색 → RRF

규칙
- where: {"doc_type": "manual", "codes": ["BTT2-P01", "BTT2-P03"]}
  값이 스칼라면 일치, 리스트면 하나라도 일치(any), 키가 여러 개면 AND.
  리스트형 메타데이터(LIST_KEYS)에 스칼라를 주면 "포함"으로 해석한다.
- Hit.score: query는 cosine 유사도, hybrid_query는 RRF 점수. 순위만 의미가 있고
  두 점수끼리, 백엔드끼리 크기를 비교하지 않는다.
- 메타데이터: 저장소는 키를 해석하지 않고 그대로 저장·반환한다(STANDARD_KEYS 참고).
  None과 빈 리스트는 키째 뺀다. dict 등 허용하지 않는 타입은 거부한다.
- 임베딩 모델 이름은 생성자에서 embedding_model로 따로 받아 컬렉션에 기록하고,
  다른 모델로 열면 StoreMismatchError를 낸다. 모델을 바꾸면 전체를 다시 색인한다.
- 저장소 객체는 프로세스당 한 번 만든다(DB 연결·로컬 폴더 잠금). 조립은 factory.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

# 저장 방식(payload 구성 등)이 바뀌면 올린다. 컬렉션에 기록하고 열 때 비교한다.
STORE_SCHEMA = "1"

MetaValue = str | int | float | bool | list[str]
Where = Mapping[str, str | int | float | bool | Sequence[str]]

# 표준 메타데이터 키. 웹 색인기와 검색 평가가 채운다.
STANDARD_KEYS = (
    "doc_type",  # manual | rule | sop | report
    "status",  # approved | draft
    "section",
    "page",
    "codes",  # list[str]. 없으면 키를 생략
    "citation",  # 사람이 읽는 인용 문자열
    "source_path",
    "source_sha256",
    "title",
)
# 필터에 쓰는 키. 서버 저장소는 이 키에 인덱스를 만든다.
FILTER_KEYS = ("doc_id", "doc_type", "status", "codes")
# 리스트 값을 담는 메타데이터 키. where의 스칼라 값을 "포함"으로 해석한다.
LIST_KEYS = frozenset({"codes", "action_dates"})
# 문서 단위로 같은 값을 갖는 키. documents()가 변경 감지용으로 모은다.
DOC_LEVEL_KEYS = (
    "doc_type",
    "status",
    "title",
    "source_path",
    "source_sha256",
    "asset_id",
    "model",
)
# Chunk 필드와 같은 이름이라 메타데이터로 따로 저장하지 않는 키.
RESERVED_KEYS = ("chunk_id", "doc_id", "doc_version", "text")
# 저장소가 payload에 덧붙이는 키. 청크 메타데이터에 넣을 수 없고 조회 때 빠진다.
# chunk_total: 그 문서를 저장할 때의 전체 청크 수. 저장이 중간에 끊긴 문서를 알아낸다.
SYSTEM_KEYS = ("chunk_total",)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str  # "{doc_id}:{doc_version}:{seq:04d}" = Evidence.evidence_id
    doc_id: str
    doc_version: str
    text: str
    metadata: Mapping[str, MetaValue] = field(default_factory=dict)


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float  # 클수록 관련. 순위만 의미 있음(모듈 docstring)
    relevance: float | None = None  # 리랭커가 채운 모델 점수. 저장소는 None을 반환


@dataclass(frozen=True)
class DocInfo:
    """저장된 문서 하나의 요약. 문서 조회와 검색 평가의 변경 감지에 쓴다."""

    doc_id: str
    doc_version: str
    source_sha256: str | None
    chunk_count: int
    metadata: Mapping[str, MetaValue] = field(default_factory=dict)  # DOC_LEVEL_KEYS
    # 청크 수가 저장 당시 전체 수와 같고, 모든 청크의 버전·문서 메타데이터가 같다.
    # False면 저장이 중간에 끊긴 문서다. 동기화가 다시 색인한다.
    complete: bool = True


class Embedder(Protocol):
    """LangChain Embeddings와 같은 모양. 구현은 rag/embedder.py(hashing·Voyage)."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class VectorStore(Protocol):
    def replace_document(self, doc_id: str, chunks: Sequence[Chunk]) -> int:
        """문서의 기존 청크를 모두 chunks로 바꾼다. 저장한 청크 수를 돌려준다.

        순서: 입력 검사 → 임베딩 → 컬렉션 검사 → 새 청크 쓰기 → 남은 옛 청크 지우기.
        - 쓰기 전 단계에서 실패하면 기존 색인이 그대로 남는다.
        - 쓰는 도중 실패하면 옛·새 청크가 섞일 수 있다. 이때 documents()가
          complete=False로 알려 주고, 다음 동기화가 그 문서를 다시 색인한다.
        빈 chunks는 ValueError다(지우려면 delete_document).
        chunk_id는 "{doc_id}:{doc_version}:"로 시작해야 한다(다른 문서와 충돌 방지).
        """
        ...

    def delete_document(self, doc_id: str) -> int:
        """문서의 청크를 모두 지우고 지운 수를 돌려준다. 없으면 0."""
        ...

    def query(self, text: str, *, k: int = 5, where: Where | None = None) -> list[Hit]:
        """dense 검색. score는 cosine 유사도."""
        ...

    def hybrid_query(
        self, text: str, *, k: int = 5, where: Where | None = None
    ) -> list[Hit]:
        """dense + sparse(BM25)를 RRF(k=60)로 합친 검색. score는 RRF 점수."""
        ...

    def documents(self, where: Where | None = None) -> dict[str, DocInfo]:
        """doc_id별 저장 상태. where로 일부 문서만 볼 수 있다(예: {"doc_id": "A"})."""
        ...

    def chunks(self, where: Where | None = None) -> list[Chunk]:
        """조건에 맞는 청크 전체. chunk_id 순서."""
        ...

    def close(self) -> None:
        """연결·로컬 폴더 잠금을 푼다. 프로세스가 끝나기 전에 부른다."""
        ...


RRF_K = 60  # Qdrant RrfQuery(rrf=Rrf(k=60))와 같은 값


def rrf(
    rankings: Sequence[Sequence[str]], *, k: int = RRF_K
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion. 점수 = Σ 1/(k + rank), rank는 0부터(Qdrant와 같은 식).

    여러 순위 목록(dense, sparse)을 합쳐 (id, 점수)를 점수 내림차순으로 돌려준다.
    점수가 같으면 id 순서.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


class StoreMismatchError(RuntimeError):
    """컬렉션이 다른 임베딩 모델·차원·스키마·sparse 인코더로 만들어졌다."""


def make_chunk_id(doc_id: str, doc_version: str, seq: int) -> str:
    """청크 ID 규칙. 예: make_chunk_id("BTT-MANUAL", "2.0", 12) → "BTT-MANUAL:2.0:0012"."""
    return f"{doc_id}:{doc_version}:{seq:04d}"


def clean_metadata(metadata: Mapping[str, object]) -> dict[str, MetaValue]:
    """두 구현체 공용 메타데이터 정리.

    None과 빈 리스트는 키째 뺀다(Chroma는 빈 리스트를 거부한다).
    리스트는 문자열만 담을 수 있다. 그 밖의 타입(dict 등)은 TypeError.
    """
    cleaned: dict[str, MetaValue] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            if not value:
                continue
            if not all(isinstance(item, str) for item in value):
                raise TypeError(f"메타데이터 {key}: 리스트에는 문자열만 넣는다")
            cleaned[key] = list(value)
        elif isinstance(value, float) and not math.isfinite(value):
            raise TypeError(f"메타데이터 {key}: NaN·무한대는 저장할 수 없다")
        elif isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
        else:
            raise TypeError(
                f"메타데이터 {key}: {type(value).__name__}는 저장할 수 없다 "
                "(str·int·float·bool·list[str]만)"
            )
    return cleaned


def chunk_payload(chunk: Chunk, *, total: int) -> dict[str, MetaValue]:
    """저장할 평평한 dict: Chunk 필드 + 정리한 메타데이터 + chunk_total.

    메타데이터에 Chunk 필드와 같은 이름의 키(doc_id 등)가 있으면 값이 같아야 한다.
    total은 이 문서를 이번에 저장하는 전체 청크 수다.
    """
    meta = dict(chunk.metadata)
    for key in RESERVED_KEYS:
        if key in meta and meta.pop(key) != getattr(chunk, key):
            raise ValueError(f"{chunk.chunk_id}: 메타데이터 {key}가 Chunk 값과 다르다")
    for key in SYSTEM_KEYS:
        if key in meta:
            raise ValueError(f"{chunk.chunk_id}: 메타데이터 {key}는 저장소가 쓰는 키다")
    return {
        **clean_metadata(meta),
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "doc_version": chunk.doc_version,
        "text": chunk.text,
        "chunk_total": total,
    }


def chunk_payloads(chunks: Sequence[Chunk]) -> list[dict[str, MetaValue]]:
    return [chunk_payload(c, total=len(chunks)) for c in chunks]


def chunk_from_payload(payload: Mapping[str, object]) -> Chunk:
    """chunk_payload의 역변환. 저장소용 키(chunk_total)는 뺀다."""
    hidden = (*RESERVED_KEYS, *SYSTEM_KEYS)
    meta = {k: v for k, v in payload.items() if k not in hidden}
    return Chunk(
        chunk_id=str(payload["chunk_id"]),
        doc_id=str(payload["doc_id"]),
        doc_version=str(payload["doc_version"]),
        text=str(payload["text"]),
        metadata=meta,  # type: ignore[arg-type]
    )


def check_chunks(doc_id: str, chunks: Sequence[Chunk]) -> None:
    """replace_document 입력 검사. 저장 전에 실수를 잡는다."""
    if not chunks:
        raise ValueError(f"{doc_id}: 빈 chunks. 문서를 지우려면 delete_document")
    versions = {c.doc_version for c in chunks}
    if len(versions) > 1:
        raise ValueError(f"{doc_id}: 한 문서에 버전이 여러 개다 {sorted(versions)}")
    ids = [c.chunk_id for c in chunks]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{doc_id}: chunk_id가 중복된다")
    for chunk in chunks:
        if chunk.doc_id != doc_id:
            raise ValueError(f"{chunk.chunk_id}: doc_id가 {doc_id}가 아니다")
        prefix = f"{chunk.doc_id}:{chunk.doc_version}:"
        if not chunk.chunk_id.startswith(prefix):
            raise ValueError(f"{chunk.chunk_id}: chunk_id는 {prefix}로 시작해야 한다")


def check_k(k: int) -> None:
    if k < 1:
        raise ValueError(f"k는 1 이상이어야 한다: {k}")


def check_where(where: Where | None) -> None:
    """빈 리스트 조건은 아무것도 맞지 않아 실수일 가능성이 높으므로 거부한다."""
    for key, value in (where or {}).items():
        if isinstance(value, (list, tuple)) and not value:
            raise ValueError(f"where {key}: 빈 리스트")


def matches(metadata: Mapping[str, object], where: Where | None) -> bool:
    """파이썬에서 where를 평가한다(메모리 BM25 등). 규칙은 모듈 docstring."""
    for key, cond in (where or {}).items():
        value = metadata.get(key)
        wanted = list(cond) if isinstance(cond, (list, tuple)) else [cond]
        have = value if isinstance(value, list) else [value]
        if not any(w in have for w in wanted):
            return False
    return True


def doc_infos(payloads: Sequence[Mapping[str, object]]) -> dict[str, DocInfo]:
    """저장된 payload를 doc_id별로 모은다. 모든 구현체의 documents()가 쓴다.

    대표값은 chunk_id가 가장 앞선 청크에서 읽는다. 청크 수가 chunk_total과 다르거나
    청크끼리 버전·문서 메타데이터가 다르면 complete=False다.
    """
    groups: dict[str, list[Mapping[str, object]]] = {}
    for payload in sorted(payloads, key=lambda p: str(p["chunk_id"])):
        groups.setdefault(str(payload["doc_id"]), []).append(payload)

    def signature(p: Mapping[str, object]) -> tuple:
        return (
            p["doc_version"],
            p.get("chunk_total"),
            *(p.get(k) for k in DOC_LEVEL_KEYS),
        )

    infos: dict[str, DocInfo] = {}
    for doc_id, group in groups.items():
        first = group[0]
        sha = first.get("source_sha256")
        complete = len({signature(p) for p in group}) == 1 and first.get(
            "chunk_total"
        ) == len(group)
        infos[doc_id] = DocInfo(
            doc_id=doc_id,
            doc_version=str(first["doc_version"]),
            source_sha256=sha if isinstance(sha, str) else None,
            chunk_count=len(group),
            metadata={k: first[k] for k in DOC_LEVEL_KEYS if k in first},  # type: ignore[misc]
            complete=complete,
        )
    return infos


def collection_meta(
    embedding_model: str, sparse_encoder: str | None
) -> dict[str, str | None]:
    """컬렉션에 기록하고 열 때 비교하는 값. sparse_encoder가 None이면 dense 전용."""
    return {
        "embedding_model": embedding_model,
        "store_schema": STORE_SCHEMA,
        "sparse_encoder": sparse_encoder,
    }


def check_collection_meta(
    collection: str, stored: Mapping[str, object], expected: Mapping[str, object]
) -> None:
    """컬렉션에 기록된 값과 현재 설정이 다르면 재색인을 안내하며 멈춘다.

    기록이 없는 키는 None으로 본다(None 값은 기록하지 않는다. Chroma가 거부한다).
    """
    for key, want in expected.items():
        have = stored.get(key)
        if have != want:
            raise StoreMismatchError(
                f"컬렉션 '{collection}'의 {key}: 기록={have!r}, 현재={want!r}. "
                "새 컬렉션을 준비하고 웹에서 문서를 재등록해야 한다"
            )
