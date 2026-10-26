"""매뉴얼 PDF 업로드와 색인 API."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    UploadFile,
)

from weeing_weeing.config import get_settings
from weeing_weeing.rag.interface import InvalidManualError, get_manual_indexer

router = APIRouter(tags=["documents"])
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MANUAL_DIR = PROJECT_ROOT / "data/manuals"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _write_metadata(folder: Path, record: dict[str, Any]) -> None:
    """상태 파일을 임시 파일에 쓴 뒤 교체한다."""
    temporary = folder / "metadata.tmp"
    temporary.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(folder / "metadata.json")


def _save_pdf(upload: UploadFile, destination: Path) -> int:
    """PDF 원본을 저장한다. 잘못된 파일이나 초과 파일은 남기지 않는다."""
    first = upload.file.read(1024)

    if b"%PDF-" not in first:
        raise HTTPException(
            status_code=415,
            detail="PDF 형식을 확인할 수 없습니다.",
        )

    size = 0

    try:
        with destination.open("xb") as output:
            block = first

            while block:
                size += len(block)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="PDF는 20MB 이하만 업로드할 수 있습니다.",
                    )

                output.write(block)
                block = upload.file.read(1024 * 1024)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    return size


def _index_uploaded_manual(folder: Path, record: dict[str, Any]) -> None:
    """저장된 PDF를 처리하고 단계별 상태를 기록한다."""

    def on_progress(stage: str) -> None:
        record["status"] = "processing"
        record["stage"] = stage
        _write_metadata(folder, record)

    try:
        settings = get_settings()
        chroma_dir = settings.chroma_dir
        if not chroma_dir.is_absolute():
            chroma_dir = PROJECT_ROOT / chroma_dir

        indexer = get_manual_indexer(
            chroma_dir=chroma_dir,
            model_name=settings.embedding_model.strip() or "BAAI/bge-m3",
        )
        chunk_count = indexer.index_file(
            PROJECT_ROOT / record["source_path"],
            record,
            on_progress=on_progress,
        )
    except InvalidManualError as exc:
        record["status"] = "failed"
        record["error"] = str(exc)
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = "문서 처리에 실패했습니다. 백엔드 로그를 확인하세요."
        record["error_type"] = type(exc).__name__

        logger.error(
            "매뉴얼 등록 실패: upload_id=%s, stage=%s, error_type=%s",
            record["upload_id"],
            record.get("stage"),
            type(exc).__name__,
        )
    else:
        record["status"] = "completed"
        record["stage"] = "completed"
        record["chunk_count"] = chunk_count
        record["completed_at"] = datetime.now(UTC).isoformat()

    _write_metadata(folder, record)


@router.post("/documents", status_code=202)
def upload_document(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    doc_id: Annotated[str, Form(min_length=1, max_length=128)],
    doc_version: Annotated[str, Form(min_length=1, max_length=128)],
    asset_id: Annotated[str, Form(min_length=1, max_length=128)],
    doc_type: Annotated[Literal["manual"], Form()] = "manual",
) -> dict[str, Any]:
    """원본을 저장하고 접수 정보를 반환한다. 색인은 이후 진행한다."""
    try:
        values = {
            "doc_id": doc_id.strip(),
            "doc_version": doc_version.strip(),
            "asset_id": asset_id.strip(),
        }
        if not all(values.values()):
            raise HTTPException(
                status_code=422,
                detail="문서 ID·버전·설비 ID는 비워 둘 수 없습니다.",
            )

        original_name = Path((file.filename or "").replace("\\", "/")).name
        if not original_name.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=415,
                detail="PDF 파일만 업로드할 수 있습니다.",
            )

        upload_id = uuid4().hex
        folder = MANUAL_DIR / upload_id
        folder.mkdir(parents=True, exist_ok=False)
        source_path = folder / original_name

        file_size = _save_pdf(file, source_path)

        record: dict[str, Any] = {
            **values,
            "upload_id": upload_id,
            "doc_type": doc_type,
            "source": original_name,
            "source_path": source_path.relative_to(PROJECT_ROOT).as_posix(),
            "file_size": file_size,
            "uploaded_at": datetime.now(UTC).isoformat(),
            "status": "queued",
            "stage": "queued",
        }
        _write_metadata(folder, record)

        # UploadFile 대신 저장된 파일 경로를 사용하므로
        # 요청 종료 후에도 원본을 읽어서 처리할 수 있다.
        background_tasks.add_task(
            _index_uploaded_manual,
            folder,
            record,
        )

        return record
    finally:
        file.file.close()


@router.get("/documents/{upload_id}")
def get_document_status(upload_id: UUID) -> dict[str, Any]:
    """업로드 건의 현재 처리 상태를 반환한다."""
    metadata_path = MANUAL_DIR / upload_id.hex / "metadata.json"

    if not metadata_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="업로드 기록을 찾을 수 없습니다.",
        )

    return json.loads(metadata_path.read_text(encoding="utf-8"))
