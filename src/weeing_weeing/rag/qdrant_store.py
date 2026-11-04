"""VectorStore의 Qdrant 구현(기본 백엔드). 계약과 규칙은 store.py.

- 컬렉션: named vector 두 개. dense(cosine)와 sparse(IDF). sparse 자리는 처음부터 만든다.
- point ID: uuid5(chunk_id). Qdrant는 "BTT-MANUAL:2.0:0001" 같은 문자열 ID를 거부한다.
- 컬렉션 metadata에 embedding_model·dim·store_schema를 기록하고 열 때 비교한다.
- 클라이언트(로컬 path / :memory: / 서버 url)는 factory가 만들어 넘긴다.
- 연결 실패·타임아웃은 그대로 올린다. 호출하는 쪽이 FAILED로 처리한다.
"""

import uuid
from collections.abc import Sequence

from qdrant_client import QdrantClient
from qdrant_client import models as qm

from weeing_weeing.rag.sparse import SparseEncoder
from weeing_weeing.rag.store import (
    FILTER_KEYS,
    RRF_K,
    Chunk,
    DocInfo,
    Embedder,
    Hit,
    Where,
    check_chunks,
    check_collection_meta,
    check_k,
    check_where,
    chunk_from_payload,
    chunk_payloads,
    collection_meta,
    doc_infos,
)

DENSE = "dense"
SPARSE = "sparse"
# chunk_id → point ID 변환용 고정 네임스페이스. 바꾸면 기존 포인트를 못 찾는다.
_POINT_NS = uuid.uuid5(uuid.NAMESPACE_URL, "weeing-weeing/rag/chunk")


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_POINT_NS, chunk_id))


def to_filter(where: Where | None) -> qm.Filter | None:
    """where → Filter(must=[...]). 리스트는 MatchAny, 스칼라는 MatchValue.

    배열 payload(codes)에 MatchValue를 주면 Qdrant가 "포함"으로 처리한다.
    """
    check_where(where)
    if not where:
        return None
    must: list[qm.Condition] = []
    for key, value in where.items():
        if isinstance(value, (list, tuple)):
            match: qm.Match = qm.MatchAny(any=list(value))
        elif isinstance(value, float):  # MatchValue는 float를 받지 않는다
            must.append(
                qm.FieldCondition(key=key, range=qm.Range(gte=value, lte=value))
            )
            continue
        else:
            match = qm.MatchValue(value=value)
        must.append(qm.FieldCondition(key=key, match=match))
    return qm.Filter(must=must)


class QdrantVectorStore:
    def __init__(
        self,
        client: QdrantClient,
        *,
        embedder: Embedder,
        embedding_model: str,
        sparse_encoder: SparseEncoder | None = None,
        collection: str = "knowledge_voyage",
        recreate: bool = False,
        batch_size: int = 64,
    ) -> None:
        self._client = client
        self._embedder = embedder
        self._sparse = sparse_encoder
        self._collection = collection
        self._batch_size = batch_size
        self._expected = collection_meta(
            embedding_model, sparse_encoder.name if sparse_encoder else None
        )
        if recreate and client.collection_exists(collection):
            client.delete_collection(collection)
        if client.collection_exists(collection):
            check_collection_meta(collection, self._stored_meta(), self._expected)

    # --- 컬렉션 ---

    def _stored_meta(self) -> dict:
        info = self._client.get_collection(self._collection)
        return dict(info.config.metadata or {})

    def _ensure_collection(self, dim: int) -> None:
        """첫 저장 때 첫 임베딩 길이로 컬렉션을 만든다. 이미 있으면 차원을 비교한다."""
        if self._client.collection_exists(self._collection):
            check_collection_meta(self._collection, self._stored_meta(), {"dim": dim})
            return
        self._client.create_collection(
            self._collection,
            vectors_config={
                DENSE: qm.VectorParams(size=dim, distance=qm.Distance.COSINE)
            },
            sparse_vectors_config={
                SPARSE: qm.SparseVectorParams(modifier=qm.Modifier.IDF)
            },
            metadata={
                **{k: v for k, v in self._expected.items() if v is not None},
                "dim": dim,
            },
        )
        # 로컬 모드에서는 인덱스가 효과가 없고 경고만 나므로 서버일 때만 만든다.
        if self._client.init_options.get("url") or self._client.init_options.get(
            "host"
        ):
            for key in FILTER_KEYS:
                self._client.create_payload_index(
                    self._collection, key, qm.PayloadSchemaType.KEYWORD
                )

    def _exists(self) -> bool:
        return self._client.collection_exists(self._collection)

    # --- 쓰기 ---

    def _points(self, chunks: Sequence[Chunk]) -> list[qm.PointStruct]:
        payloads = chunk_payloads(chunks)
        vectors = self._embedder.embed_documents([c.text for c in chunks])
        if len(vectors) != len(chunks):
            raise ValueError("임베더가 청크 수와 다른 개수의 벡터를 돌려줬다")
        sparse = (
            self._sparse.encode_documents([c.text for c in chunks])
            if self._sparse
            else None
        )
        self._ensure_collection(len(vectors[0]))
        points = []
        for i, (c, payload) in enumerate(zip(chunks, payloads, strict=True)):
            vector: dict = {DENSE: vectors[i]}
            if sparse is not None:
                vector[SPARSE] = qm.SparseVector(
                    indices=sparse[i].indices, values=sparse[i].values
                )
            points.append(
                qm.PointStruct(id=point_id(c.chunk_id), vector=vector, payload=payload)
            )
        return points

    def replace_document(self, doc_id: str, chunks: Sequence[Chunk]) -> int:
        check_chunks(doc_id, chunks)
        points = self._points(chunks)  # 임베딩·검사 먼저. 실패하면 기존 색인 그대로
        for start in range(0, len(points), self._batch_size):  # 새 청크 쓰기
            self._client.upsert(
                self._collection, points[start : start + self._batch_size], wait=True
            )
        # 남은 옛 청크(이번 ID에 없는 것) 지우기. 위에서 끊기면 옛·새가 섞이고
        # documents()가 complete=False로 알려 준다.
        stale = qm.Filter(
            must=[qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id))],
            must_not=[qm.HasIdCondition(has_id=[p.id for p in points])],
        )
        self._client.delete(
            self._collection, points_selector=qm.FilterSelector(filter=stale), wait=True
        )
        return len(points)

    def delete_document(self, doc_id: str) -> int:
        if not self._exists():
            return 0
        flt = to_filter({"doc_id": doc_id})
        count = self._client.count(self._collection, count_filter=flt, exact=True).count
        if count:
            self._client.delete(
                self._collection,
                points_selector=qm.FilterSelector(filter=flt),
                wait=True,
            )
        return count

    # --- 읽기 ---

    def query(self, text: str, *, k: int = 5, where: Where | None = None) -> list[Hit]:
        check_k(k)
        flt = to_filter(where)
        if not self._exists():
            return []
        result = self._client.query_points(
            self._collection,
            query=self._embedder.embed_query(text),
            using=DENSE,
            query_filter=flt,
            limit=k,
            with_payload=True,
        )
        return [
            Hit(chunk_from_payload(p.payload or {}), p.score) for p in result.points
        ]

    def hybrid_query(
        self, text: str, *, k: int = 5, where: Where | None = None
    ) -> list[Hit]:
        """dense·sparse를 각각 k*4개 뽑아(prefetch) DB 안에서 RRF로 합친다.

        필터는 prefetch마다 넣는다. 상위 쿼리 필터만으로는 prefetch 후보가 걸러지지 않는다.
        """
        if self._sparse is None:
            raise RuntimeError(
                "sparse_encoder 없이 만든 저장소는 hybrid_query를 못 쓴다"
            )
        flt = to_filter(where)
        if not self._exists():
            return []
        prefetch = [
            qm.Prefetch(
                query=self._embedder.embed_query(text),
                using=DENSE,
                filter=flt,
                limit=k * 4,
            )
        ]
        sparse = self._sparse.encode_query(text)
        if sparse.indices:  # 키워드가 하나도 안 나오면 dense만으로 순위를 낸다
            prefetch.append(
                qm.Prefetch(
                    query=qm.SparseVector(indices=sparse.indices, values=sparse.values),
                    using=SPARSE,
                    filter=flt,
                    limit=k * 4,
                )
            )
        result = self._client.query_points(
            self._collection,
            prefetch=prefetch,
            query=qm.RrfQuery(rrf=qm.Rrf(k=RRF_K)),
            query_filter=flt,
            limit=k,
            with_payload=True,
        )
        return [
            Hit(chunk_from_payload(p.payload or {}), p.score) for p in result.points
        ]

    def _payloads(self, where: Where | None) -> list[dict]:
        flt = to_filter(where)
        if not self._exists():
            return []
        found: list[dict] = []
        offset = None
        while True:
            records, offset = self._client.scroll(
                self._collection,
                scroll_filter=flt,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            found.extend(r.payload or {} for r in records)
            if offset is None:
                return found

    def chunks(self, where: Where | None = None) -> list[Chunk]:
        found = [chunk_from_payload(p) for p in self._payloads(where)]
        return sorted(found, key=lambda c: c.chunk_id)

    def documents(self, where: Where | None = None) -> dict[str, DocInfo]:
        return doc_infos(self._payloads(where))

    def close(self) -> None:
        self._client.close()
