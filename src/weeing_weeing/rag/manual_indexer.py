"""매뉴얼 PDF를 파싱·청킹·임베딩하고 Chroma에 저장한다."""

import hashlib
import json
import math
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

import chromadb
from langchain_core.embeddings import Embeddings

from weeing_weeing.rag.chunker import ChunkerConfig, chunk_documents
from weeing_weeing.rag.embedder import EmbeddingConfig, create_embeddings
from weeing_weeing.rag.interface import InvalidManualError, ProgressCallback
from weeing_weeing.rag.pdf_parser import ParserConfig, parse_pdf, save_markdown

# 한 개발 서버 프로세스 안에서 모델 로드와 색인 작업을 순서대로 처리한다.
_INDEX_LOCK = Lock()


class ManualIndexer:
    def __init__(self, *, chroma_dir: Path, model_name: str) -> None:
        self._chroma_dir = chroma_dir
        self._model_name = model_name
        self._embeddings: Embeddings | None = None

    def index_file(
        self,
        path: Path,
        metadata: dict[str, Any],
        *,
        on_progress: ProgressCallback | None = None,
    ) -> int:
        """동일 문서·버전·설비를 교체하고 처리 단계를 알린다."""
        required = ("doc_id", "doc_version", "asset_id")
        if any(
            not isinstance(metadata.get(key), str) or not metadata[key].strip()
            for key in required
        ):
            raise InvalidManualError("doc_id, doc_version, asset_id가 필요합니다.")

        with _INDEX_LOCK:
            return self._index_file(path, metadata, on_progress)

    def _index_file(
        self,
        path: Path,
        metadata: dict[str, Any],
        on_progress: ProgressCallback | None,
    ) -> int:
        report = on_progress or (lambda stage: None)
        report("parsing")
        # 현재 BTT-MANUAL 양식에 맞춘 설정이다.
        try:
            documents = parse_pdf(
                path,
                doc_id=metadata["doc_id"],
                doc_version=metadata["doc_version"],
                doc_type="manual",
                asset_id=metadata["asset_id"],
                config=ParserConfig(
                    margin_top=45,
                    margin_bottom=50,
                    infer_table_columns=True,
                    single_row_as_quote=True,
                ),
            )
        except Exception as exc:
            raise InvalidManualError(
                "PDF 파싱에 실패했습니다. 텍스트 추출 가능 여부와 "
                "암호 설정·페이지 여백을 확인하세요."
            ) from exc

        # 출처에 업로드 당시 파일명과 원본 저장 경로를 유지한다.
        for document in documents:
            document.metadata["source"] = metadata.get("source", path.name)
            document.metadata["source_path"] = metadata.get("source_path", str(path))

        # 파싱 결과를 PDF 원본과 같은 폴더에 저장한다.
        save_markdown(documents, path.parent / "parsed.md")

        report("chunking")
        chunks = chunk_documents(
            documents,
            config=ChunkerConfig(
                chunk_size=1000,
                chunk_overlap=150,
            ),
        )

        if not chunks:
            raise InvalidManualError("생성된 청크가 없습니다.")

        # 청크 경계·문자 수·메타데이터·본문을 검토용으로 저장한다.
        sections = []
        for number, chunk in enumerate(chunks, start=1):
            metadata_text = json.dumps(
                chunk.metadata,
                ensure_ascii=False,
            )
            sections.append(
                f"## 청크 {number}\n\n"
                f"- 문자 수: {len(chunk.page_content)}\n"
                f"- 메타데이터: {metadata_text}\n\n"
                f"{chunk.page_content}"
            )

        preview_path = path.parent / "chunks.md"
        preview_path.write_text(
            "\n\n---\n\n".join(sections) + "\n",
            encoding="utf-8",
        )

        if self._embeddings is None:
            report("loading_model")
            self._embeddings = create_embeddings(
                EmbeddingConfig(
                    model_name=self._model_name,
                    device="cpu",
                    batch_size=8,
                    normalize_embeddings=True,
                )
            )

        report("embedding")
        vectors = self._embeddings.embed_documents(
            [chunk.page_content for chunk in chunks]
        )

        if len(vectors) != len(chunks):
            raise RuntimeError("청크 수와 벡터 수가 다릅니다.")

        dimension = len(vectors[0])
        if dimension == 0:
            raise RuntimeError("빈 벡터가 생성됐습니다.")

        for vector in vectors:
            if (
                len(vector) != dimension
                or not all(math.isfinite(value) for value in vector)
                or not any(value != 0 for value in vector)
            ):
                raise RuntimeError("유효하지 않은 임베딩 벡터입니다.")

        # 다른 모델의 벡터가 같은 컬렉션에 섞이지 않도록 구분한다.
        report("storing")
        model_key = hashlib.sha256(self._model_name.encode("utf-8")).hexdigest()[:16]

        client = chromadb.PersistentClient(path=str(self._chroma_dir))
        collection = client.get_or_create_collection(
            name=f"manuals_{model_key}",
            embedding_function=None,
            configuration={"hnsw": {"space": "cosine"}},
            metadata={
                "embedding_model": self._model_name,
                "normalized": True,
            },
        )

        identity = json.dumps(
            [
                metadata["doc_id"],
                metadata["doc_version"],
                metadata["asset_id"],
            ],
            ensure_ascii=False,
        )
        document_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        generation_id = uuid4().hex

        ids = [
            f"{document_key}:{generation_id}:{index}" for index in range(len(chunks))
        ]
        metadatas = [
            {
                **chunk.metadata,
                "document_key": document_key,
                "generation_id": generation_id,
                "upload_id": metadata.get("upload_id", generation_id),
                "embedding_model": self._model_name,
            }
            for chunk in chunks
        ]

        try:
            batch_size = client.get_max_batch_size()

            for start in range(0, len(chunks), batch_size):
                end = start + batch_size
                collection.add(
                    ids=ids[start:end],
                    documents=[chunk.page_content for chunk in chunks[start:end]],
                    metadatas=metadatas[start:end],
                    embeddings=vectors[start:end],
                )

            stored = collection.get(
                where={"generation_id": generation_id},
                include=[],
            )
            if len(stored["ids"]) != len(chunks):
                raise RuntimeError("저장된 청크 수가 일치하지 않습니다.")

            # 새 데이터 저장을 확인한 뒤 같은 문서의 이전 등록분을 제거한다.
            collection.delete(
                where={
                    "$and": [
                        {"document_key": document_key},
                        {"generation_id": {"$ne": generation_id}},
                    ]
                }
            )
        except Exception:
            # 이번 등록에서 일부만 저장됐다면 정리한다.
            collection.delete(where={"generation_id": generation_id})
            raise

        return len(chunks)
