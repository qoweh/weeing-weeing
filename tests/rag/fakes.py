"""rag 테스트 공용 가짜 부품. 모델·DB 없이 #6·#7·#8 테스트에서 같이 쓴다.

- FakeEmbedder: 단어 해시 기반 결정적 임베더. 같은 단어가 많을수록 가깝다.
- MemoryVectorStore: VectorStore 계약의 기준 구현(파이썬 dict). 계약 테스트의 기준이자
  DB 없이 검색 쪽(#8)을 테스트할 때 쓴다.
"""

import hashlib
import math
import re
from collections.abc import Sequence

from weeing_weeing.rag.store import (
    STORE_SCHEMA,
    Chunk,
    DocInfo,
    Hit,
    Where,
    check_chunks,
    check_collection_meta,
    check_k,
    check_where,
    chunk_from_payload,
    chunk_payloads,
    doc_infos,
    matches,
)


class FakeEmbedder:
    """공백·구두점으로 자른 단어를 해시해 dim칸에 더한 뒤 정규화한다."""

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim
        self.calls = 0  # embed_documents 호출 횟수

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        vec[-1] = 0.01  # 빈 텍스트도 0 벡터가 되지 않게
        for token in re.findall(r"\w+", text.lower()):
            h = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest())
            vec[h % (self.dim - 1)] += 1.0 if (h >> 32) & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class BrokenEmbedder(FakeEmbedder):
    """embed_documents가 실패한다. 교체 원자성 테스트용."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("임베딩 실패(테스트)")


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


class MemoryVectorStore:
    """VectorStore 기준 구현. storage dict를 공유하면 '같은 DB를 다시 연 것'이 된다."""

    def __init__(
        self,
        storage: dict,
        *,
        embedder,
        embedding_model: str,
        collection: str = "knowledge",
    ) -> None:
        self._storage = storage
        self._embedder = embedder
        self._collection = collection
        self._meta = {"embedding_model": embedding_model, "store_schema": STORE_SCHEMA}
        if collection in storage:
            check_collection_meta(collection, storage[collection]["meta"], self._meta)

    @property
    def _points(self) -> dict[str, tuple[dict, list[float]]]:
        col = self._storage.get(self._collection)
        return col["points"] if col else {}

    def replace_document(self, doc_id: str, chunks: Sequence[Chunk]) -> int:
        check_chunks(doc_id, chunks)
        payloads = chunk_payloads(chunks)
        vectors = self._embedder.embed_documents([c.text for c in chunks])
        col = self._storage.setdefault(
            self._collection,
            {"meta": {**self._meta, "dim": len(vectors[0])}, "points": {}},
        )
        check_collection_meta(self._collection, col["meta"], {"dim": len(vectors[0])})
        new_ids = {p["chunk_id"] for p in payloads}
        for payload, vector in zip(payloads, vectors, strict=True):  # 새 청크 먼저
            col["points"][payload["chunk_id"]] = (payload, vector)
        stale = [  # 그다음 남은 옛 청크
            cid
            for cid, (p, _) in col["points"].items()
            if p["doc_id"] == doc_id and cid not in new_ids
        ]
        for cid in stale:
            del col["points"][cid]
        return len(chunks)

    def delete_document(self, doc_id: str) -> int:
        ids = [cid for cid, (p, _) in self._points.items() if p["doc_id"] == doc_id]
        for cid in ids:
            del self._points[cid]
        return len(ids)

    def query(self, text: str, *, k: int = 5, where: Where | None = None) -> list[Hit]:
        check_k(k)
        check_where(where)
        if not self._points:
            return []
        q = self._embedder.embed_query(text)
        hits = [
            Hit(chunk_from_payload(p), _cosine(q, v))
            for p, v in self._points.values()
            if matches(p, where)
        ]
        return sorted(hits, key=lambda h: (-h.score, h.chunk.chunk_id))[:k]

    def hybrid_query(
        self, text: str, *, k: int = 5, where: Where | None = None
    ) -> list[Hit]:
        raise NotImplementedError("hybrid_query는 #25에서 구현한다")

    def documents(self, where: Where | None = None) -> dict[str, DocInfo]:
        check_where(where)
        return doc_infos([p for p, _ in self._points.values() if matches(p, where)])

    def chunks(self, where: Where | None = None) -> list[Chunk]:
        check_where(where)
        found = [
            chunk_from_payload(p) for p, _ in self._points.values() if matches(p, where)
        ]
        return sorted(found, key=lambda c: c.chunk_id)
