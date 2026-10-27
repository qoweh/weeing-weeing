"""문서 PDF 업로드와 색인 API.

    POST /documents  원본을 UPLOAD_DIR/<upload_id>/에 저장(git 밖) → 충돌 검사 → 202
                     이후 백그라운드에서 make index와 같은 Indexer·저장소로 색인
    GET  /documents/{upload_id}  처리 상태(metadata.json)

metadata.json은 처리 상태 파일이자 문서 목록(rag 레지스트리)의 업로드 항목이다.
status가 completed인 업로드는 make index가 카탈로그와 함께 관리한다(모델 교체 시 재색인 등).
"""

import hashlib
import json
import logging
import shutil
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

from weeing_weeing.config import from_root, get_settings
from weeing_weeing.rag import interface
from weeing_weeing.rag.interface import InvalidDocumentError

router = APIRouter(tags=["documents"])
logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
# 청크 ID({doc_id}:{doc_version}:{순번})의 구분자 ':'와 공백은 쓸 수 없다.
ID_PATTERN = r"^[^:\s]+$"


def upload_dir() -> Path:
    """make index와 같은 기준(레포 루트)으로 푼 업로드 폴더."""
    return from_root(get_settings().upload_dir)


def _write_metadata(folder: Path, record: dict[str, Any]) -> None:
    """상태 파일을 임시 파일에 쓴 뒤 교체한다."""
    temporary = folder / "metadata.tmp"
    temporary.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(folder / "metadata.json")


def _save_pdf(upload: UploadFile, destination: Path) -> tuple[int, str]:
    """PDF 원본을 저장하고 (크기, SHA-256)을 돌려준다. 잘못된 파일이나 초과 파일은 남기지 않는다."""
    first = upload.file.read(1024)

    if b"%PDF-" not in first:
        raise HTTPException(
            status_code=415,
            detail="PDF 형식을 확인할 수 없습니다.",
        )

    size = 0
    digest = hashlib.sha256()

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
                digest.update(block)
                block = upload.file.read(1024 * 1024)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    return size, digest.hexdigest()


def _index_uploaded_document(folder: Path, record: dict[str, Any]) -> None:
    """저장된 PDF를 색인하고 단계별 상태를 기록한다."""

    def on_progress(stage: str) -> None:
        record["status"] = "processing"
        record["stage"] = stage
        _write_metadata(folder, record)

    newer = interface.newer_upload(
        folder.parent,
        record["doc_id"],
        record["uploaded_at"],
        exclude=record["upload_id"],
    )
    if (
        newer
    ):  # 같은 문서를 연달아 올림: 먼저 올린 것이 최신을 덮지 않게 색인하지 않는다
        record["status"] = record["stage"] = "superseded"
        record["superseded_by"] = newer
        _write_metadata(folder, record)
        return

    try:
        metadata = interface.upload_index_metadata(folder, record)
        chunk_count = interface.get_indexer().index_file(
            folder / record["source"],
            metadata,
            on_progress=on_progress,
        )
    except InvalidDocumentError as exc:
        record["status"] = "failed"
        record["error"] = str(exc)
    except ValueError as exc:  # 설정 누락 등(예: EMBEDDING_MODEL이 비어 있음)
        record["status"] = "failed"
        record["error"] = str(exc)
        record["error_type"] = type(exc).__name__
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = "문서 처리에 실패했습니다. 백엔드 로그를 확인하세요."
        record["error_type"] = type(exc).__name__

        logger.error(
            "문서 등록 실패: upload_id=%s, stage=%s, error_type=%s",
            record["upload_id"],
            record.get("stage"),
            type(exc).__name__,
        )
    else:
        # 예전 업로드를 먼저 대체한 뒤 완료로 쓴다. 같은 doc_id가 둘 다 completed인 순간이 없게.
        # (저장소의 청크는 replace_document가 이미 교체했다)
        interface.supersede_uploads(
            folder.parent, record["doc_id"], keep=record["upload_id"]
        )
        record["status"] = "completed"
        record["stage"] = "completed"
        record["chunk_count"] = chunk_count
        record["completed_at"] = datetime.now(UTC).isoformat()

    _write_metadata(folder, record)


@router.post("/documents", status_code=202)
def upload_document(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    doc_id: Annotated[str, Form(min_length=1, max_length=128, pattern=ID_PATTERN)],
    doc_version: Annotated[str, Form(min_length=1, max_length=128, pattern=ID_PATTERN)],
    asset_id: Annotated[str, Form(min_length=1, max_length=128)],
    doc_type: Annotated[Literal["manual", "rule", "sop"], Form()] = "manual",
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
        if Path(original_name).suffix.lower() != ".pdf":
            raise HTTPException(
                status_code=415,
                detail="PDF 파일만 업로드할 수 있습니다.",
            )

        upload_id = uuid4().hex
        uploads = upload_dir()
        folder = uploads / upload_id
        folder.mkdir(parents=True, exist_ok=False)

        try:
            file_size, sha256 = _save_pdf(file, folder / original_name)
            try:
                conflict = interface.upload_conflict(
                    values["doc_id"],
                    sha256,
                    from_root(get_settings().rag_catalog),
                    uploads,
                )
            except ValueError as exc:  # 카탈로그 파일이 깨짐(CatalogError)
                raise HTTPException(
                    status_code=503,
                    detail=f"문서 목록(카탈로그)을 읽지 못했습니다: {exc}",
                ) from exc
            if conflict:
                raise HTTPException(status_code=409, detail=conflict)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise

        record: dict[str, Any] = {
            **values,
            "upload_id": upload_id,
            "doc_type": doc_type,
            "doc_status": "approved",
            "title": original_name,
            "source": original_name,
            "file_size": file_size,
            "source_sha256": sha256,
            "uploaded_at": datetime.now(UTC).isoformat(),
            "status": "queued",
            "stage": "queued",
        }
        _write_metadata(folder, record)

        # UploadFile 대신 저장된 파일 경로를 사용하므로
        # 요청 종료 후에도 원본을 읽어서 처리할 수 있다.
        background_tasks.add_task(
            _index_uploaded_document,
            folder,
            record,
        )

        return record
    finally:
        file.file.close()


@router.get("/documents/{upload_id}")
def get_document_status(upload_id: UUID) -> dict[str, Any]:
    """업로드 건의 현재 처리 상태를 반환한다."""
    metadata_path = upload_dir() / upload_id.hex / "metadata.json"

    if not metadata_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="업로드 기록을 찾을 수 없습니다.",
        )

    return json.loads(metadata_path.read_text(encoding="utf-8"))
