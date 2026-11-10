"""문서 PDF 업로드와 색인 API.

    POST /documents  원본을 UPLOAD_DIR/<upload_id>/에 저장(git 밖) → 충돌 검사 → DB에 기록 → 202
                     이후 백그라운드에서 PDF 파싱·청킹·임베딩·벡터 저장
    GET  /documents              등록 문서 목록(로그인)
    GET  /documents/{upload_id}  처리 상태(DB document 행, 로그인)
    GET  /documents/{upload_id}/file  저장된 원본 PDF(로그인, 화면 열람용)
    DELETE /documents/{doc_id}   관제 담당자가 문서·검색 청크 삭제

문서 목록과 처리 상태는 DB(document 테이블)로 관리한다. 별도 기본 문서 목록은 읽지 않는다.
DB에 연결하지 못하면 503.
"""

import hashlib
import logging
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Annotated, Any, Literal
from unicodedata import normalize
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel

from weeing_weeing.api.auth import current_user, require_roles
from weeing_weeing.config import from_root, get_settings
from weeing_weeing.contracts import DocumentRecord, Role
from weeing_weeing.contracts.document import DOC_ID_PATTERN
from weeing_weeing.db import interface as db
from weeing_weeing.rag import interface
from weeing_weeing.rag.interface import InvalidDocumentError

router = APIRouter(tags=["documents"])
logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
FILENAME_VERSION = re.compile(
    r"(?:^|[^A-Za-z0-9])v([0-9]+\.[0-9]+(?:\.[0-9]+)*)(?![A-Za-z0-9.])",
    re.IGNORECASE,
)


def _version_from_filename(filename: str) -> str:
    """파일명의 마지막 v숫자.숫자 표기를 사용한다. 없으면 1.0."""
    versions = FILENAME_VERSION.findall(Path(filename).stem)
    return versions[-1] if versions else "1.0"


def upload_dir() -> Path:
    """레포 루트 기준으로 푼 업로드 폴더."""
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


def _index(repo: db.DocumentRepository, upload_id: str) -> None:
    record = repo.get_upload(upload_id)
    if record is None:
        return
    with _doc_lock(record.doc_id), repo.lock_document(record.doc_id):
        record = repo.get_upload(upload_id)
        if record is None or record.status not in ("queued", "processing"):
            return
        # 잠금을 기다리는 동안 더 새 업로드가 끝났을 수 있어 잠근 뒤에 판단한다.
        blocker = repo.newer_upload(
            record.doc_id, record.uploaded_at, exclude=record.upload_id
        )
        if blocker:  # 먼저 올린 것이 최신 문서를 덮지 않게 색인하지 않는다
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
    except ValueError as exc:  # 설정 오류 등(예: 알 수 없는 EMBEDDING_PROVIDER)
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
        # 저장 도중 다른 호출자가 승자를 바꿨다면 현재 등록 문서에 확인 필요 표시를 남긴다.
        repo.record_index_results(
            [],
            {
                record.doc_id: f"업로드 {upload_id}가 색인을 덮어씀. 최신 문서를 웹에서 다시 등록하세요."
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


@router.post(
    "/documents", status_code=202, dependencies=[Depends(require_roles(Role.CONTROL))]
)
def upload_document(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    # 청크 ID 구분자 ':'와 공백은 쓸 수 없다
    doc_id: Annotated[str, Form(min_length=1, max_length=128, pattern=DOC_ID_PATTERN)],
    asset_id: Annotated[str, Form(min_length=1, max_length=128)],
    doc_type: Annotated[Literal["manual", "rule", "sop"], Form()] = "manual",
    confirm_replace: Annotated[bool, Form()] = False,
    expected_upload_id: Annotated[str, Form()] = "",
    expected_version: Annotated[str, Form()] = "",
    expected_sha256: Annotated[str, Form()] = "",
) -> dict[str, Any]:
    """원본을 저장하고 접수 정보를 반환한다. 색인은 이후 진행한다."""
    try:
        values = {
            "doc_id": doc_id.strip(),
            "asset_id": asset_id.strip(),
        }
        if not all(values.values()):
            raise HTTPException(
                status_code=422,
                detail="문서 ID·설비 ID는 비워 둘 수 없습니다.",
            )
        if values["doc_id"].upper().startswith("RPT-"):
            raise HTTPException(status_code=422, detail="RPT-는 보고서 전용 ID입니다.")

        original_name = Path((file.filename or "").replace("\\", "/")).name
        if Path(original_name).suffix.lower() != ".pdf":
            raise HTTPException(
                status_code=415,
                detail="PDF 파일만 업로드할 수 있습니다.",
            )

        doc_version = _version_from_filename(original_name)
        if len(doc_version) > 128:
            raise HTTPException(
                status_code=422, detail="파일명의 문서 버전이 너무 깁니다."
            )

        upload_id = uuid4().hex
        folder = upload_dir() / upload_id
        folder.mkdir(parents=True, exist_ok=False)

        try:
            file_size, sha256 = _save_pdf(file, folder / original_name)
            repo = documents()
            record = DocumentRecord(
                doc_id=values["doc_id"],
                doc_version=doc_version,
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
                with repo.lock_document(record.doc_id, source_sha256=sha256):
                    conflict = repo.upload_conflict(record.doc_id, sha256)
                    if conflict:
                        raise HTTPException(status_code=409, detail=conflict)
                    current = repo.upload_target(record.doc_id)
                    if current:
                        if current.doc_type != record.doc_type:
                            raise HTTPException(
                                status_code=409,
                                detail="이미 다른 종류의 문서가 사용 중인 ID입니다. 다른 문서 ID를 입력하세요.",
                            )
                        if current.extra.get("asset_id") != record.extra.get(
                            "asset_id"
                        ):
                            raise HTTPException(
                                status_code=409,
                                detail="이미 다른 설비의 문서가 사용 중인 ID입니다. 다른 문서 ID를 입력하세요.",
                            )
                        if not confirm_replace:
                            raise HTTPException(
                                status_code=409,
                                detail={
                                    "code": "replace_confirmation_required",
                                    "message": "같은 문서 ID가 있습니다. 교체 여부를 확인하세요.",
                                    "current": {
                                        "doc_id": current.doc_id,
                                        "title": current.title,
                                        "doc_type": current.doc_type,
                                        "asset_id": current.extra.get("asset_id"),
                                        "doc_version": current.doc_version,
                                        "upload_id": current.upload_id,
                                        "source_sha256": current.source_sha256,
                                    },
                                    "incoming": {
                                        "title": original_name,
                                        "doc_version": doc_version,
                                    },
                                },
                            )
                        if (
                            current.upload_id or "",
                            current.doc_version,
                            current.source_sha256,
                        ) != (expected_upload_id, expected_version, expected_sha256):
                            raise HTTPException(
                                status_code=409,
                                detail="문서가 변경됐습니다. 다시 등록해 교체 내용을 확인하세요.",
                            )
                    elif confirm_replace:
                        raise HTTPException(
                            status_code=409,
                            detail="기존 문서가 변경되거나 삭제됐습니다. 다시 등록해 확인하세요.",
                        )
                    repo.add_upload(record)
            except db.DocumentConflictError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
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


def _search_text(value: str) -> str:
    return " ".join(normalize("NFC", value).split())


def _body_excerpt(record: DocumentRecord, term: str) -> dict[str, str] | None:
    """현재 업로드의 추출 본문만 검색한다. 보관된 이전 판·삭제 문서는 읽지 않는다."""
    if record.origin != "upload" or not record.upload_id:
        return None
    root = upload_dir().resolve()
    try:
        path = (root / record.upload_id / "parsed.md").resolve()
        if not path.is_relative_to(root):
            return None
        body = _search_text(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        # 추출 파일이 없는 문서도 제목·ID로는 조회할 수 있다.
        return None
    match = re.search(re.escape(term), body, re.IGNORECASE)
    if not match:
        return None
    start, end = match.span()
    left, right = max(0, start - 70), min(len(body), end + 70)
    return {
        "before": ("…" if left else "") + body[left:start],
        "match": body[start:end],
        "after": body[end:right] + ("…" if right < len(body) else ""),
    }


@router.get("/documents", dependencies=[Depends(current_user)])
def list_documents(
    q: Annotated[str, Query(max_length=200)] = "",
) -> list[dict[str, Any]]:
    """등록 문서를 조회하고, 검색어가 있으면 제목·ID·설비 ID·추출 본문을 검색한다."""
    try:
        records = documents().managed_documents()
    except db.DatabaseUnavailableError as exc:
        raise _db_unavailable(exc) from exc
    fields = {
        "doc_id",
        "doc_version",
        "doc_type",
        "title",
        "origin",
        "upload_id",
        "source_sha256",
        "status",
        "error",
        "index_error",
        "chunk_count",
        "uploaded_at",
        "indexed_at",
    }
    term = _search_text(q)
    result = []
    for record in records:
        item = {
            **record.model_dump(mode="json", include=fields),
            "asset_id": record.extra.get("asset_id"),
        }
        if term:
            metadata_match = any(
                term.casefold() in _search_text(str(value or "")).casefold()
                for value in (record.title, record.doc_id, item["asset_id"])
            )
            excerpt = _body_excerpt(record, term)
            if not metadata_match and excerpt is None:
                continue
            if excerpt is not None:
                item["search_excerpt"] = excerpt
        result.append(item)
    return result


class DeleteDocument(BaseModel):
    doc_version: str
    source_sha256: str
    upload_id: str | None = None


@router.delete(
    "/documents/{doc_id:path}", dependencies=[Depends(require_roles(Role.CONTROL))]
)
def delete_document(doc_id: str, body: DeleteDocument) -> dict[str, Any]:
    """검색 청크를 지운 뒤 문서의 모든 판을 DB에서 실제 삭제한다. 원본 파일은 보관한다."""
    failure = None
    try:
        repo = documents()
        with repo.lock_document(doc_id):
            repo.begin_delete(doc_id, **body.model_dump())
            try:
                removed = interface.get_indexer().delete_document(doc_id)
            except Exception as exc:
                failure = type(exc).__name__
                logger.error(
                    "문서 삭제 실패: doc_id=%s, error_type=%s", doc_id, failure
                )
                repo.finish_delete(
                    doc_id,
                    error="검색 자료 삭제에 실패했습니다. 삭제를 다시 시도하세요.",
                )
            else:
                repo.finish_delete(doc_id)
    except db.DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="등록된 문서를 찾을 수 없습니다."
        ) from exc
    except db.DocumentConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except db.DatabaseUnavailableError as exc:
        raise _db_unavailable(exc) from exc
    # 잠금 트랜잭션을 커밋한 뒤 오류를 돌려줘야 재시도 상태가 보존된다.
    if failure:
        raise HTTPException(
            status_code=503,
            detail="검색 자료 삭제에 실패했습니다. 목록에서 삭제를 다시 시도하세요.",
        )
    return {"doc_id": doc_id, "status": "deleted", "removed_chunks": removed}


@router.get("/documents/original", dependencies=[Depends(current_user)])
def get_document_original(
    doc_id: Annotated[str, Query(pattern=DOC_ID_PATTERN, max_length=128)],
    doc_version: Annotated[str, Query(pattern=DOC_ID_PATTERN, max_length=128)],
) -> FileResponse:
    """챗봇이 인용한 현재 등록 판의 원본만 반환한다. 파일 경로는 입력받지 않는다."""
    try:
        record = next(
            (
                r
                for r in documents().listed()
                if r.doc_id == doc_id and r.doc_version == doc_version
            ),
            None,
        )
    except db.DatabaseUnavailableError as exc:
        raise _db_unavailable(exc) from exc
    if record is None or record.origin not in {"seed", "upload"}:
        raise HTTPException(
            status_code=404, detail="인용한 문서 버전의 원본을 찾을 수 없습니다."
        )
    # seed도 프로젝트 data 밖의 임의 파일이나 symlink 탈출은 허용하지 않는다.
    try:
        root = (
            upload_dir().resolve()
            if record.origin == "upload"
            else from_root(Path("data")).resolve()
        )
        path = (
            (root / record.source).resolve()
            if record.origin == "upload"
            else from_root(Path(record.source)).resolve()
        )
        if (
            not path.is_relative_to(root)
            or path.suffix.lower() != ".pdf"
            or not path.is_file()
        ):
            raise OSError("원본 경로 확인 실패")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != record.source_sha256:
            raise OSError("등록 원본과 내용 불일치")
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=404, detail="인용한 문서의 원본이 없거나 변경되었습니다."
        ) from exc
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
        content_disposition_type="inline",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/documents/{upload_id}", dependencies=[Depends(current_user)])
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


@router.get("/documents/{upload_id}/file", dependencies=[Depends(current_user)])
def get_document_file(upload_id: UUID) -> FileResponse:
    """업로드한 원본 PDF를 화면에서 바로 볼 수 있게 돌려준다."""
    try:
        record = documents().get_upload(upload_id.hex)
    except db.DatabaseUnavailableError as exc:
        raise _db_unavailable(exc) from exc
    if record is None or record.origin != "upload":
        raise HTTPException(
            status_code=404,
            detail="업로드 기록을 찾을 수 없습니다.",
        )
    root = upload_dir().resolve()
    path = (root / record.source).resolve()
    # DB 값이 업로드 폴더 밖을 가리키거나 PDF가 아니면 읽지 않는다.
    if (
        not path.is_relative_to(root)
        or path.suffix.lower() != ".pdf"
        or not path.is_file()
    ):
        raise HTTPException(
            status_code=404,
            detail="원본 PDF 파일을 찾을 수 없습니다.",
        )
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=record.title,
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff"},
    )
