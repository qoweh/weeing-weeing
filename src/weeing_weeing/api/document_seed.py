"""팀 문서(data/manuals·rulebase·regulations)를 웹 업로드와 같은 경로로 미리 등록한다.

    seed_documents(load_seed(path))
      문서마다: SHA-256 계산 → 지금 컬렉션에 같은 파일이 임베딩돼 있으면 건너뜀
               → 아니면 업로드 폴더에 원본 복사 + DB document 행 + 색인(파싱·청킹·임베딩)

웹 업로드(api/documents.py)와 같은 잠금·충돌 검사·완료 처리를 쓰므로, 등록한 문서는
웹 문서 목록에 보이고 웹에서 교체·삭제할 수 있다. 자동 동기화가 아니다(D-28).
"""

import hashlib
import re
import shutil
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from weeing_weeing.api import documents as upload_api
from weeing_weeing.config import from_root
from weeing_weeing.contracts import DocumentRecord
from weeing_weeing.contracts.document import DOC_ID_PATTERN
from weeing_weeing.db import interface as db
from weeing_weeing.rag import interface as rag

DOC_TYPES = ("manual", "rule", "sop")
Action = Literal["added", "reindexed", "replaced", "skipped", "failed"]


@dataclass(frozen=True)
class SeedDocument:
    doc_id: str
    doc_type: str
    asset_id: str
    path: Path
    doc_version: str = ""  # 비우면 파일명 규칙(웹 업로드와 같음)


@dataclass(frozen=True)
class SeedResult:
    doc_id: str
    action: Action
    detail: str = ""


def load_seed(path: Path) -> list[SeedDocument]:
    """시드 목록 TOML을 읽고 검증한다. path는 저장소 루트 기준으로 푼다."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    items = []
    seen: set[str] = set()
    for raw in data.get("documents", []):
        doc_id = str(raw.get("doc_id", "")).strip()
        doc_type = str(raw.get("doc_type", "")).strip()
        asset_id = str(raw.get("asset_id", "")).strip()
        file = from_root(Path(str(raw.get("path", ""))))
        version = str(raw.get("doc_version", "")).strip()
        if not re.fullmatch(DOC_ID_PATTERN, doc_id) or doc_id.upper().startswith(
            "RPT-"
        ):
            raise ValueError(f"잘못된 doc_id: {doc_id!r}")
        if doc_id in seen:
            raise ValueError(f"doc_id 중복: {doc_id}")
        if doc_type not in DOC_TYPES:
            raise ValueError(f"{doc_id}: doc_type은 {DOC_TYPES} 중 하나")
        if not asset_id:
            raise ValueError(f"{doc_id}: asset_id가 비어 있다")
        if file.suffix.lower() != ".pdf" or not file.is_file():
            raise ValueError(f"{doc_id}: PDF 파일이 없다: {file}")
        if version and not re.fullmatch(DOC_ID_PATTERN, version):
            raise ValueError(f"{doc_id}: 잘못된 doc_version: {version!r}")
        seen.add(doc_id)
        items.append(SeedDocument(doc_id, doc_type, asset_id, file, version))
    if not items:
        raise ValueError(f"{path}에 documents 항목이 없다")
    return items


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def seed_documents(
    items: list[SeedDocument],
    repo: db.DocumentRepository,
    *,
    indexed: Callable[[], dict[str, str | None]] = rag.indexed_documents,
    index_upload: Callable[[db.DocumentRepository, str], None] = upload_api._index,
    upload_root: Callable[[], Path] = upload_api.upload_dir,
    replace: bool = False,
    on_result: Callable[[SeedResult], None] | None = None,
) -> list[SeedResult]:
    """문서를 차례로 등록한다. 한 문서의 실패가 다른 문서를 막지 않는다."""
    stored = indexed()
    results = []
    for item in items:
        try:
            result = _seed_one(item, repo, stored, index_upload, upload_root, replace)
        except db.DatabaseUnavailableError:
            raise
        except Exception as exc:  # 다음 문서는 계속한다
            result = SeedResult(item.doc_id, "failed", f"{type(exc).__name__}: {exc}")
        results.append(result)
        if on_result:
            on_result(result)
    return results


def _seed_one(
    item: SeedDocument,
    repo: db.DocumentRepository,
    stored: dict[str, str | None],
    index_upload: Callable[[db.DocumentRepository, str], None],
    upload_root: Callable[[], Path],
    replace: bool,
) -> SeedResult:
    sha256 = _sha256(item.path)
    original_name = item.path.name
    version = item.doc_version or upload_api._version_from_filename(original_name)
    upload_id = uuid4().hex
    folder = upload_root() / upload_id

    with repo.lock_document(item.doc_id, source_sha256=sha256):
        conflict = repo.upload_conflict(item.doc_id, sha256)
        if conflict:
            return SeedResult(item.doc_id, "skipped", conflict)
        current = repo.upload_target(item.doc_id)
        same_file = current is not None and current.source_sha256 == sha256
        if same_file and stored.get(item.doc_id) == sha256:
            return SeedResult(item.doc_id, "skipped", "이미 등록·임베딩됨")
        if current is not None and not same_file and not replace:
            return SeedResult(
                item.doc_id,
                "skipped",
                "웹에서 다른 파일로 등록돼 있다. 교체하려면 --replace",
            )
        if current is not None and (
            current.doc_type != item.doc_type
            or current.extra.get("asset_id") != item.asset_id
        ):
            return SeedResult(
                item.doc_id, "skipped", "등록된 문서와 종류·설비 ID가 다르다"
            )
        folder.mkdir(parents=True, exist_ok=False)
        try:
            shutil.copyfile(item.path, folder / original_name)
            repo.add_upload(
                DocumentRecord(
                    doc_id=item.doc_id,
                    doc_version=version,
                    doc_type=item.doc_type,
                    origin="upload",
                    upload_id=upload_id,
                    title=original_name,
                    source=f"{upload_id}/{original_name}",
                    source_sha256=sha256,
                    file_size=item.path.stat().st_size,
                    extra={"asset_id": item.asset_id},
                    uploaded_at=datetime.now(UTC),
                    status="queued",
                    stage="queued",
                )
            )
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise

    # 색인은 웹 업로드의 백그라운드 작업과 같은 함수로 한다(자체 잠금을 다시 잡는다).
    index_upload(repo, upload_id)
    done = repo.get_upload(upload_id)
    if done is None or done.status != "completed":
        status = done.status if done else "missing"
        error = (done.error or "") if done else ""
        return SeedResult(item.doc_id, "failed", f"{status} {error}".strip())
    if current is None:
        action: Action = "added"
    elif same_file:
        action = "reindexed"
    else:
        action = "replaced"
    return SeedResult(item.doc_id, action, f"청크 {done.chunk_count}개")
