"""문서 PDF 업로드와 색인 API.

    POST /documents  원본을 UPLOAD_DIR/<upload_id>/에 저장(git 밖) → 충돌 검사 → DB에 기록 → 202
                     이후 백그라운드에서 make index와 같은 Indexer·저장소로 색인
    GET  /documents/{upload_id}  처리 상태(DB document 행)

업로드 상태와 문서 목록은 DB(document 테이블)가 원본이다. 완료된 업로드는 make index가
카탈로그 문서와 함께 관리한다(모델 교체 시 재색인 등). DB에 연결하지 못하면 503.
"""

import hashlib
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
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
from weeing_weeing.contracts import DocumentRecord
from weeing_weeing.contracts.document import DOC_ID_PATTERN
from weeing_weeing.db import interface as db
from weeing_weeing.rag import interface
from weeing_weeing.rag.interface import InvalidDocumentError

router = APIRouter(tags=["documents"])
logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ID_PATTERN = DOC_ID_PATTERN  # 청크 ID 구분자 ':'와 공백은 쓸 수 없다


def upload_dir() -> Path:
    """make index와 같은 기준(레포 루트)으로 푼 업로드 폴더."""
    return from_root(get_settings().upload_dir)


def documents() -> db.DocumentRepository:
    try:
        return db.get_documents()
    except db.DatabaseUnavailableError as exc:
        raise _db_unavailable(exc) from exc


def _db_unavailable(exc: Exception) -> HTTPException:
    logger.error("DB 연결 실패: %s", type(exc).__name__)
    return HTTPException(
        status_code=503,
        detail="문서 DB에 연결하지 못했습니다. 잠시 후 다시 시도하세요.",
    )


def _response(record: DocumentRecord) -> dict[str, Any]:
    """화면이 쓰던 모양 그대로(asset_id 등 extra를 위로 펼친다)."""
    return {**record.extra, **record.model_dump(mode="json", exclude={"extra"})}


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


def _index_uploaded_document(upload_id: str) -> None:
    """저장된 PDF를 색인하고 단계별 상태를 DB에 기록한다."""
    try:
        _index(db.get_documents(), upload_id)
    except db.DatabaseUnavailableError as exc:  # 상태를 기록할 수 없다. 로그만 남긴다
        logger.error(
            "문서 색인 상태 기록 실패: upload_id=%s, error_type=%s",
            upload_id,
            type(exc).__name__,
        )


# 같은 doc_id의 색인은 한 번에 하나만 한다. 둘이 동시에 저장소를 교체하면 DB가 고른 승자와
# 저장소에 남은 청크가 달라질 수 있다(먼저 끝난 것을 나중 것이 덮음).
_DOC_LOCKS: dict[str, Lock] = {}
_DOC_LOCKS_GUARD = Lock()


def _doc_lock(doc_id: str) -> Lock:
    with _DOC_LOCKS_GUARD:
        return _DOC_LOCKS.setdefault(doc_id, Lock())


def _blocker(repo: db.DocumentRepository, record: DocumentRecord) -> str | None:
    """이 업로드를 색인하면 안 되는 이유(더 늦게 올린 업로드나 카탈로그 문서가 있음)."""
    newer = repo.newer_upload(
        record.doc_id, record.uploaded_at, exclude=record.upload_id
    )
    if newer:
        return newer
    if any(r.origin == "seed" and r.doc_id == record.doc_id for r in repo.listed()):
        return "seed"
    return None


def _index(repo: db.DocumentRepository, upload_id: str) -> None:
    record = repo.get_upload(upload_id)
    if record is None:
        return
    with _doc_lock(record.doc_id):
        # 잠금을 기다리는 동안 더 새 업로드가 끝났을 수 있어 잠근 뒤에 판단한다.
        blocker = _blocker(repo, record)
        if (
            blocker
        ):  # 먼저 올린 것이 최신(또는 카탈로그 문서)을 덮지 않게 색인하지 않는다
            repo.update_upload(
                upload_id,
                status="superseded",
                stage="superseded",
                superseded_by=blocker,
            )
            return
        _index_locked(repo, record)


def _index_locked(repo: db.DocumentRepository, record: DocumentRecord) -> None:
    upload_id = record.upload_id

    def on_progress(stage: str) -> None:
        repo.update_upload(upload_id, status="processing", stage=stage)

    folder = upload_dir()
    try:
        metadata = interface.upload_index_metadata(record, folder)
        chunk_count = interface.get_indexer().index_file(
            folder / record.source,
            metadata,
            on_progress=on_progress,
        )
    except db.DatabaseUnavailableError:
        raise
    except InvalidDocumentError as exc:
        repo.update_upload(upload_id, status="failed", error=str(exc))
        return
    except ValueError as exc:  # 설정 누락 등(예: EMBEDDING_MODEL이 비어 있음)
        repo.update_upload(
            upload_id, status="failed", error=str(exc), error_type=type(exc).__name__
        )
        return
    except Exception as exc:
        _fail(repo, upload_id, exc)
        return

    # 예전 업로드 superseded + 이 업로드 completed를 트랜잭션 하나로.
    # (저장소의 청크는 replace_document가 이미 교체했다)
    try:
        done = repo.complete_upload(upload_id, chunk_count=chunk_count)
    except db.DatabaseUnavailableError:
        raise
    except Exception as exc:  # processing으로 멈춰 있지 않게 실패로 남긴다
        _fail(repo, upload_id, exc)
        return
    if done.status == "superseded":
        # 그사이 다른 프로세스(make index 등)가 이 doc_id의 승자를 정했다. 저장소에는 이
        # 업로드의 청크가 들어갔으므로 승자를 다시 색인해야 한다. make index가 내용
        # 차이(sha)로 알아채고 고치지만, 그때까지 화면·로그에서 보이게 남긴다.
        repo.record_index_results(
            [],
            {
                record.doc_id: f"업로드 {upload_id}가 색인을 덮어씀. make index로 다시 맞춘다"
            },
        )


def _fail(repo: db.DocumentRepository, upload_id: str, exc: Exception) -> None:
    repo.update_upload(
        upload_id,
        status="failed",
        error="문서 처리에 실패했습니다. 백엔드 로그를 확인하세요.",
        error_type=type(exc).__name__,
    )
    logger.error(
        "문서 등록 실패: upload_id=%s, error_type=%s", upload_id, type(exc).__name__
    )


def _catalog_conflict(
    seeds: list[DocumentRecord], doc_id: str, sha256: str
) -> str | None:
    """카탈로그(data/catalog.toml)와의 충돌. DB에 쓰지 않고 파일 기준으로 본다."""
    for seed in seeds:
        if seed.doc_id == doc_id:
            return f"{doc_id}는 카탈로그(data/catalog.toml)가 관리하는 문서다. 다른 doc_id를 쓴다"
        if seed.source_sha256 == sha256:
            return (
                f"{seed.doc_id}와 같은 내용의 파일이다. 같은 문서가 두 번 검색·인용된다"
            )
    return None


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
        folder = upload_dir() / upload_id
        folder.mkdir(parents=True, exist_ok=False)

        try:
            file_size, sha256 = _save_pdf(file, folder / original_name)
            try:
                seeds = interface.seed_records(from_root(get_settings().rag_catalog))
            except ValueError as exc:  # 카탈로그 파일이 깨짐(CatalogError)
                raise HTTPException(
                    status_code=503,
                    detail=f"문서 목록(카탈로그)을 읽지 못했습니다: {exc}",
                ) from exc
            repo = documents()
            record = DocumentRecord(
                doc_id=values["doc_id"],
                doc_version=values["doc_version"],
                doc_type=doc_type,
                origin="upload",
                upload_id=upload_id,
                title=original_name,
                source=f"{upload_id}/{original_name}",
                source_sha256=sha256,
                file_size=file_size,
                extra={"asset_id": values["asset_id"]},
                uploaded_at=datetime.now(UTC),
                status="queued",
                stage="queued",
            )
            try:
                conflict = _catalog_conflict(
                    seeds, record.doc_id, sha256
                ) or repo.upload_conflict(record.doc_id, sha256)
                if conflict:
                    raise HTTPException(status_code=409, detail=conflict)
                repo.add_upload(record)
            except db.DatabaseUnavailableError as exc:
                raise _db_unavailable(exc) from exc
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise

        # UploadFile 대신 저장된 파일 경로를 사용하므로
        # 요청 종료 후에도 원본을 읽어서 처리할 수 있다.
        background_tasks.add_task(_index_uploaded_document, upload_id)

        return _response(record)
    finally:
        file.file.close()


@router.get("/documents/{upload_id}")
def get_document_status(upload_id: UUID) -> dict[str, Any]:
    """업로드 건의 현재 처리 상태를 반환한다."""
    try:
        record = documents().get_upload(upload_id.hex)
    except db.DatabaseUnavailableError as exc:
        raise _db_unavailable(exc) from exc
    if record is None:
        raise HTTPException(
            status_code=404,
            detail="업로드 기록을 찾을 수 없습니다.",
        )
    return _response(record)
