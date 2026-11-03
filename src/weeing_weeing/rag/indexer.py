"""범용 Indexer(rag/interface.py의 Indexer 구현). 웹 업로드와 격리된 검색 평가가 같이 쓴다.

    index_file(path, metadata)
      1. 파싱    parser_for(path) → 페이지별 Document           (#6 pdf_parser)
      2. 절 제목  페이지 첫 줄 "03 …"·"제2장 …"을 section으로(없으면 앞 페이지 것을 이어 씀)
      3. 청킹    chunk_documents → 문서 전체에서 0부터 이어지는 순번  (#6 chunker)
      4. Chunk  청크 ID {doc_id}:{doc_version}:{순번}, 받은 metadata를 그대로 +
                page·section·codes·citation
      5. 저장    store.replace_document(doc_id, chunks)   임베딩·키워드 벡터는 저장소가 계산(#7)

받은 metadata(문서 등록 정보)는 바꾸지 않는다. 동기화가 이 값으로 변경을 감지한다.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from langchain_core.documents import Document

from weeing_weeing.contracts import MaintenanceReport
from weeing_weeing.rag.chunker import ChunkerConfig, chunk_documents
from weeing_weeing.rag.interface import InvalidDocumentError, ProgressCallback
from weeing_weeing.rag.parsers import parser_for
from weeing_weeing.rag.pdf_parser import save_markdown
from weeing_weeing.rag.report import report_chunk
from weeing_weeing.rag.sparse import extract_codes
from weeing_weeing.rag.store import Chunk, VectorStore, make_chunk_id
from weeing_weeing.rag.structured_chunker import structured_chunk_documents

__all__ = ["DocumentIndexer", "InvalidDocumentError"]

# 같은 프로세스(API 서버) 안에서 색인을 한 번에 하나씩 처리한다. 모델 로드·로컬 DB 쓰기 보호.
_INDEX_LOCK = Lock()
# 매뉴얼·룰 정의서의 "03 이송·광전 현장 대응 절차", SOP의 "제2장 이상 대응 및 에너지 격리"
_SECTION = re.compile(r"^(?:\d{2}\s+\S|제\s*\d+\s*장\s+\S)")
_PAGE_MARK = re.compile(r"\A## 페이지 \d+\s*")


def page_section(text: str) -> str | None:
    """페이지 본문의 첫 줄이 절 제목이면 돌려준다."""
    for line in _PAGE_MARK.sub("", text).splitlines():
        line = line.strip()
        if line:
            heading = (
                _SECTION.match(line)
                and "|" not in line
                and re.search("[가-힣]", line)
                and len(line) <= 60
            )
            return line if heading else None
    return None


def _citation(doc_id: str, doc_version: str, section: str | None, page: Any) -> str:
    where = section or (f"{page}쪽" if page else "")
    return f"{doc_id} {doc_version} {where}".strip()


class DocumentIndexer:
    def __init__(
        self,
        store: VectorStore,
        *,
        chunker: ChunkerConfig | None = None,
        write_previews: bool = False,
        report_preview_dir: Path | None = None,
        chunking: Literal["legacy", "structured"] = "legacy",
    ) -> None:
        """write_previews: 원본 옆에 parsed.md·chunks.md를 남긴다(업로드 검토용)."""
        self.store = store
        self._chunker = chunker or ChunkerConfig()
        self._write_previews = write_previews
        self._report_preview_dir = report_preview_dir
        if chunking not in ("legacy", "structured"):
            raise ValueError(f"지원하지 않는 청킹 방식: {chunking}")
        self._chunking = chunking

    def index_file(
        self,
        path: Path,
        metadata: dict[str, Any],
        *,
        on_progress: ProgressCallback | None = None,
    ) -> int:
        doc_id, version = metadata.get("doc_id"), metadata.get("doc_version")
        if not all(isinstance(v, str) and v.strip() for v in (doc_id, version)):
            raise InvalidDocumentError("metadata에 doc_id와 doc_version이 필요하다")
        with _INDEX_LOCK:
            existing = self.store.documents(where={"doc_id": doc_id})
            if any(
                info.metadata.get("doc_type") == "report" for info in existing.values()
            ):
                raise InvalidDocumentError(
                    "승인 보고서와 같은 문서 ID로 등록할 수 없습니다."
                )
            return self._index(
                Path(path), metadata, on_progress or (lambda stage: None)
            )

    def delete_document(self, doc_id: str) -> int:
        with _INDEX_LOCK:
            documents = self.store.documents(where={"doc_id": doc_id})
            if any(
                info.metadata.get("doc_type") == "report" for info in documents.values()
            ):
                raise InvalidDocumentError("승인 보고서는 매뉴얼 삭제 대상이 아닙니다.")
            return self.store.delete_document(doc_id)

    def delete_report(self, report_id: str) -> int:
        with _INDEX_LOCK:
            existing = self.store.documents(where={"doc_id": report_id})
            if any(
                info.metadata.get("doc_type") != "report" for info in existing.values()
            ):
                raise InvalidDocumentError(
                    "보고서가 아닌 검색 자료는 삭제할 수 없습니다."
                )
            if self._report_preview_dir is not None:
                folder = self._report_preview_folder(report_id)
                if folder.exists():
                    # 미리보기 정리에 실패했다면 검색 자료도 그대로 유지한다.
                    shutil.rmtree(folder)
            return self.store.delete_document(report_id)

    def index_report(self, report: MaintenanceReport) -> int:
        """전체 사례를 청크 하나로 저장한다. doc_id가 같으면 이전 승인 판을 교체한다."""
        chunk = report_chunk(report)
        with _INDEX_LOCK:
            existing = self.store.documents(where={"doc_id": report.report_id})
            if any(
                info.metadata.get("doc_type") != "report" for info in existing.values()
            ):
                raise InvalidDocumentError(
                    "등록 문서와 같은 ID로 보고서를 색인할 수 없습니다."
                )
            count = self.store.replace_document(report.report_id, [chunk])
            if self._report_preview_dir is not None:
                self._write_report_preview(chunk)
            return count

    def _report_preview_folder(self, report_id: str) -> Path:
        assert self._report_preview_dir is not None
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", report_id)[:64]
        digest = hashlib.sha256(report_id.encode("utf-8")).hexdigest()[:16]
        return self._report_preview_dir / f"{safe_id}-{digest}"

    def _write_report_preview(self, chunk: Chunk) -> None:
        folder = self._report_preview_folder(chunk.doc_id)
        folder.mkdir(parents=True, exist_ok=True)
        preview = (
            f"# 보고서 검색 청크\n\n"
            f"- 보고서 ID: {chunk.doc_id}\n"
            f"- 버전: {chunk.doc_version}\n"
            f"- 청크 ID: {chunk.chunk_id}\n"
            f"- 문자 수: {len(chunk.text)}\n"
            f"- 메타데이터: {json.dumps(dict(chunk.metadata), ensure_ascii=False)}\n\n"
            f"## 검색 본문\n\n{chunk.text}\n"
        )
        path = folder / f"v{chunk.doc_version}.md"
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=folder, delete=False
            ) as file:
                temp_path = Path(file.name)
                file.write(preview)
            os.replace(temp_path, path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def _index(self, path: Path, metadata: Mapping[str, Any], report) -> int:
        doc_id, version = metadata["doc_id"], metadata["doc_version"]
        parser = parser_for(path)
        report("parsing")
        try:
            pages = parser.parse(
                path,
                doc_id=doc_id,
                doc_version=version,
                doc_type=str(metadata.get("doc_type", "manual")),
            )
        except Exception as exc:
            raise InvalidDocumentError(
                f"{parser.name.upper()} 파싱에 실패했다. 텍스트 추출 가능 여부와 "
                "암호 설정·페이지 여백을 확인한다"
            ) from exc

        section = None
        for page in pages:  # 절 제목은 청킹 전에 페이지마다 붙여 청크로 이어지게 한다
            section = page_section(page.page_content) or section
            if section:
                page.metadata["section"] = section

        report("chunking")
        split = (
            structured_chunk_documents
            if self._chunking == "structured"
            else chunk_documents
        )
        pieces = split(pages, config=self._chunker)
        if not pieces:
            raise InvalidDocumentError("본문에서 청크를 만들지 못했다")
        chunks = [self._chunk(seq, piece, metadata) for seq, piece in enumerate(pieces)]
        if self._write_previews:
            self._previews(path, pages, chunks)

        report("embedding")  # 임베딩과 저장은 저장소가 한 번에 한다
        return self.store.replace_document(doc_id, chunks)

    @staticmethod
    def _chunk(seq: int, piece: Document, metadata: Mapping[str, Any]) -> Chunk:
        doc_id, version = metadata["doc_id"], metadata["doc_version"]
        page = piece.metadata.get("page")
        section = piece.metadata.get("section")
        derived = {
            "page": page,
            "section": section,
            "codes": extract_codes(piece.page_content),
            "citation": _citation(doc_id, version, section, page),
        }
        if piece.metadata.get("structural_heading"):
            derived["structural_heading"] = piece.metadata["structural_heading"]
        return Chunk(
            chunk_id=make_chunk_id(doc_id, version, seq),
            doc_id=doc_id,
            doc_version=version,
            text=piece.page_content,
            metadata={**derived, **metadata},  # 받은 값이 우선(바꾸지 않는다)
        )

    @staticmethod
    def _previews(path: Path, pages: list[Document], chunks: list[Chunk]) -> None:
        save_markdown(pages, path.parent / "parsed.md")
        sections = [
            f"## 청크 {n}\n\n- 문자 수: {len(c.text)}\n"
            f"- 메타데이터: {json.dumps(dict(c.metadata), ensure_ascii=False)}\n\n{c.text}"
            for n, c in enumerate(chunks, start=1)
        ]
        (path.parent / "chunks.md").write_text(
            "\n\n---\n\n".join(sections) + "\n", encoding="utf-8"
        )
