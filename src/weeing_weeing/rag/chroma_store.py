"""VectorStore의 Chroma 구현(대체 백엔드, VECTOR_STORE=chroma). 계약과 규칙은 store.py.

- Chroma 임베딩 함수(EF)는 쓰지 않는다. Embedder로 계산한 벡터를 직접 넘긴다.
  EF 없이 텍스트만 넘기면 Chroma가 영어 전용 기본 모델을 인터넷에서 받는다.
- 거리는 컬렉션을 만들 때 cosine으로 고정한다. 벡터를 직접 넘기면 기본값이 l2이고,
  만든 뒤에는 바꿀 수 없다.
- EF 불일치 검사는 EF를 쓸 때만 동작하므로, 모델 이름은 컬렉션 metadata에 직접 기록한다.
- 내장 모드(PersistentClient)는 프로세스에 안전하지 않다. 한 프로세스만 쓴다.
- 텔레메트리 끄기(anonymized_telemetry=False)는 클라이언트를 만드는 factory가 맡는다.
- 하이브리드: Chroma의 sparse·Search API는 Cloud 전용이라, dense 검색 결과와
  메모리 BM25(Qdrant와 같은 인코더·IDF 식)를 파이썬 RRF로 합친다.
"""

import hashlib
import json
from collections.abc import Sequence

from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.errors import NotFoundError

from weeing_weeing.rag.sparse import Bm25Index, SparseEncoder
from weeing_weeing.rag.store import (
    LIST_KEYS,
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
    matches,
    rrf,
)


def _condition(key: str, value) -> dict:
    """키 하나의 조건. 리스트형 필드(codes)는 $contains, 스칼라 필드 리스트는 $in."""
    if key in LIST_KEYS:
        values = list(value) if isinstance(value, (list, tuple)) else [value]
        conds = [{key: {"$contains": v}} for v in values]
        return conds[0] if len(conds) == 1 else {"$or": conds}
    if isinstance(value, (list, tuple)):
        return {key: {"$in": list(value)}}
    return {key: value}


def to_where(where: Where | None) -> dict | None:
    """where → Chroma where. 조건이 1개면 $and로 묶지 않는다(Chroma 문법)."""
    check_where(where)
    if not where:
        return None
    conds = [_condition(k, v) for k, v in where.items()]
    return conds[0] if len(conds) == 1 else {"$and": conds}


def _split(payload: dict) -> tuple[str, dict]:
    """payload → (본문, metadata). 본문은 Chroma documents에 따로 저장한다."""
    meta = {k: v for k, v in payload.items() if k != "text"}
    return str(payload["text"]), meta


def _join(text: str, meta: dict) -> Chunk:
    return chunk_from_payload({**meta, "text": text})


class ChromaVectorStore:
    def __init__(
        self,
        client: ClientAPI,
        *,
        embedder: Embedder,
        embedding_model: str,
        sparse_encoder: SparseEncoder | None = None,
        collection: str = "knowledge_voyage",
        recreate: bool = False,
        owns_client: bool = False,
    ) -> None:
        self._client = client
        # Injected clients may be shared by several store wrappers. Ownership
        # must be explicit; factory-created stores own their dedicated client.
        self._owns_client = owns_client
        self._closed = False
        self._embedder = embedder
        self._sparse = sparse_encoder
        self._name = collection
        self._expected = collection_meta(
            embedding_model, sparse_encoder.name if sparse_encoder else None
        )
        # 메모리 BM25 캐시: (저장 내용 지문, 색인, chunk_id → (청크, 필터용 payload)).
        # 검색할 때마다 저장된 내용의 지문을 다시 계산해 다르면 캐시를 새로 만든다.
        # 다른 저장소 객체(예: 색인 명령)가 써도 따라간다. 컬렉션 metadata는 건드리지
        # 않는다(modify가 이후 검색 결과를 흔드는 것을 확인했다).
        self._bm25: tuple[str, Bm25Index, dict[str, tuple[Chunk, dict]]] | None = None
        if recreate and self._get() is not None:
            client.delete_collection(collection)
        col = self._get()
        if col is not None:
            check_collection_meta(collection, col.metadata or {}, self._expected)

    # --- 컬렉션 ---

    def _get(self) -> Collection | None:
        try:
            return self._client.get_collection(self._name, embedding_function=None)
        except NotFoundError:
            return None

    def _ensure(self, dim: int) -> Collection:
        col = self._get()
        if col is not None:
            check_collection_meta(self._name, col.metadata or {}, {"dim": dim})
            return col
        return self._client.create_collection(
            self._name,
            configuration={"hnsw": {"space": "cosine"}},
            metadata={
                **{k: v for k, v in self._expected.items() if v is not None},
                "dim": dim,
            },
            embedding_function=None,
        )

    # --- 쓰기 ---

    def replace_document(self, doc_id: str, chunks: Sequence[Chunk]) -> int:
        check_chunks(doc_id, chunks)
        parts = [_split(p) for p in chunk_payloads(chunks)]
        vectors = self._embedder.embed_documents([c.text for c in chunks])
        if len(vectors) != len(chunks):
            raise ValueError("임베더가 청크 수와 다른 개수의 벡터를 돌려줬다")
        # 임베딩·검사 먼저. 실패하면 기존 색인 그대로
        col = self._ensure(len(vectors[0]))
        ids = [c.chunk_id for c in chunks]
        existing = set(col.get(where={"doc_id": doc_id}, include=[])["ids"])
        # 새 ID는 add, 이미 있는 ID는 update로 쓴다. Chroma 1.5.9에서 새 ID를 upsert로
        # 넣으면 가끔 그 청크가 벡터 검색에서 빠지는 것을 확인했다(500회 중 3~6회).
        step = self._client.get_max_batch_size()  # 한 번에 넣을 수 있는 최대 개수
        for start in range(0, len(ids), step):  # 새 청크 쓰기
            batch = range(start, min(start + step, len(ids)))
            for write, picked in (
                (col.add, [i for i in batch if ids[i] not in existing]),
                (col.update, [i for i in batch if ids[i] in existing]),
            ):
                if picked:
                    write(
                        ids=[ids[i] for i in picked],
                        embeddings=[vectors[i] for i in picked],
                        documents=[parts[i][0] for i in picked],
                        metadatas=[parts[i][1] for i in picked],
                    )
        # 남은 옛 청크 지우기. 위에서 끊기면 documents()가 complete=False로 알려 준다.
        stale = sorted(existing - set(ids))
        if stale:
            col.delete(ids=stale)
        return len(chunks)

    def delete_document(self, doc_id: str) -> int:
        col = self._get()
        if col is None:
            return 0
        found = col.get(where={"doc_id": doc_id}, include=[])["ids"]
        if found:
            col.delete(ids=found)
        return len(found)

    # --- 읽기 ---

    def query(self, text: str, *, k: int = 5, where: Where | None = None) -> list[Hit]:
        check_k(k)
        flt = to_where(where)
        col = self._get()
        if col is None or col.count() == 0:
            return []
        result = col.query(
            query_embeddings=[self._embedder.embed_query(text)],
            n_results=k,
            where=flt,
            include=["documents", "metadatas", "distances"],
        )
        return [
            Hit(_join(doc, dict(meta)), 1.0 - dist)  # cosine 거리 → 유사도
            for doc, meta, dist in zip(
                result["documents"][0],
                result["metadatas"][0],
                result["distances"][0],
                strict=True,
            )
        ]

    def _bm25_index(self) -> tuple[Bm25Index, dict[str, tuple[Chunk, dict]]]:
        """저장 내용이 캐시와 같으면 재사용하고, 다르면 Kiwi로 다시 인코딩한다.

        청크 수백 개 규모라 내용을 읽어 지문을 내는 비용은 밀리초 단위다.
        비싼 것(형태소 분석)은 내용이 바뀔 때만 한다.
        """
        payloads = sorted(self._payloads(None), key=lambda p: str(p["chunk_id"]))
        digest = hashlib.blake2b(
            json.dumps(payloads, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        if self._bm25 is None or self._bm25[0] != digest:
            vectors = self._sparse.encode_documents([str(p["text"]) for p in payloads])
            self._bm25 = (
                digest,
                Bm25Index(
                    {
                        str(p["chunk_id"]): v
                        for p, v in zip(payloads, vectors, strict=True)
                    }
                ),
                {str(p["chunk_id"]): (chunk_from_payload(p), p) for p in payloads},
            )
        return self._bm25[1], self._bm25[2]

    def hybrid_query(
        self, text: str, *, k: int = 5, where: Where | None = None
    ) -> list[Hit]:
        """dense k*4개와 메모리 BM25 k*4개를 RRF(k=60)로 합친다."""
        if self._sparse is None:
            raise RuntimeError(
                "sparse_encoder 없이 만든 저장소는 hybrid_query를 못 쓴다"
            )
        dense = self.query(text, k=k * 4, where=where)
        if not dense:
            return []
        index, by_id = self._bm25_index()
        scores = index.scores(self._sparse.encode_query(text))
        sparse = sorted(
            (cid for cid in scores if matches(by_id[cid][1], where)),
            key=lambda cid: (-scores[cid], cid),
        )[: k * 4]
        # 청크 내용은 DB에서 방금 읽은 dense 결과를 먼저 쓰고, 없으면 캐시에서 꺼낸다.
        current = {h.chunk.chunk_id: h.chunk for h in dense}
        current.update({cid: by_id[cid][0] for cid in sparse if cid not in current})
        fused = rrf([[h.chunk.chunk_id for h in dense], sparse])[:k]
        return [Hit(current[cid], score) for cid, score in fused]

    def _payloads(self, where: Where | None) -> list[dict]:
        flt = to_where(where)
        col = self._get()
        if col is None:
            return []
        got = col.get(where=flt, include=["documents", "metadatas"])
        return [
            {**meta, "text": doc}
            for doc, meta in zip(got["documents"], got["metadatas"], strict=True)
        ]

    def chunks(self, where: Where | None = None) -> list[Chunk]:
        found = [chunk_from_payload(p) for p in self._payloads(where)]
        return sorted(found, key=lambda c: c.chunk_id)

    def documents(self, where: Where | None = None) -> dict[str, DocInfo]:
        return doc_infos(self._payloads(where))

    def close(self) -> None:
        """소유한 클라이언트만 닫는다. 빌린 공유 객체는 호출자가 관리한다."""
        if self._owns_client and not self._closed:
            self._client.close()
            self._closed = True
