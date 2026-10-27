"""문서 레지스트리: 색인 대상 문서 목록을 한 곳으로 모은다.

    git이 관리하는 기준 문서  data/catalog.toml            (팀이 PR로 고친다)
  + git 밖의 업로드 문서     storage/uploads/<id>/metadata.json  (업로드 API가 쓴다)
  = load_registry() → Catalog 하나 → sync(make index)가 그대로 처리

서버가 git이 추적하는 파일을 고치지 않으면서도 목록은 하나다. 모델을 바꿔 컬렉션을 새로
만들어도(--recreate) 업로드 문서까지 다시 색인된다. 2차에 PostgreSQL document 테이블이
생기면 업로드 쪽 읽기를 DB로 바꾼다.

검증 원칙: 카탈로그(팀 파일)는 엄격하게 검증해 문제가 있으면 멈춘다. 업로드는 항목별로
처리해서, 깨졌거나 카탈로그·다른 업로드와 부딪히는 항목은 건너뛰고 경고만 남긴다.
업로드 하나 때문에 팀 전체의 make index가 멈추지 않게 하기 위해서다.

업로드 매니페스트(metadata.json)는 업로드 API의 처리 상태 파일이기도 하다.
status: queued → processing → completed | failed, 대체되면 superseded.
목록에는 completed만 들어가고, 같은 doc_id가 여럿이면 가장 늦게 올린 것 하나만 쓴다.
"""

import json
from pathlib import Path

from pydantic import ValidationError

from weeing_weeing.rag.catalog import (
    Catalog,
    CatalogEntry,
    file_sha256,
    load_catalog,
)

MANIFEST = "metadata.json"
EXTRA_KEYS = (
    "asset_id",
    "upload_id",
)  # 업로드 매니페스트에서 청크 메타데이터로 옮길 값
ACTIVE = (
    "queued",
    "processing",
    "completed",
)  # 충돌 검사에서 살아 있는 업로드로 보는 상태


def _manifests(upload_dir: Path) -> list[tuple[Path, dict]]:
    if not upload_dir.is_dir():
        return []
    found = []
    for path in sorted(upload_dir.glob(f"*/{MANIFEST}")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue  # 쓰는 중이거나 깨진 파일은 목록에서 뺀다
        if isinstance(record, dict):
            found.append((path.parent, record))
    return found


def write_manifest(folder: Path, record: dict) -> None:
    """임시 파일에 쓴 뒤 교체한다. 읽는 쪽이 반쯤 쓴 파일을 보지 않게."""
    temporary = folder / f"{MANIFEST}.tmp"
    temporary.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(folder / MANIFEST)


def upload_entry(folder: Path, record: dict) -> CatalogEntry:
    """업로드 매니페스트 하나 → 카탈로그 항목. 파일 경로는 절대 경로.

    필수 키가 없거나 값이 잘못되면 KeyError·ValidationError.
    """
    return CatalogEntry(
        doc_id=record["doc_id"],
        doc_version=record["doc_version"],
        doc_type=record.get("doc_type", "manual"),
        status=record.get("doc_status", "approved"),
        path=str((folder / record["source"]).resolve()),
        title=record.get("title") or record["source"],
        extra={k: str(record[k]) for k in EXTRA_KEYS if record.get(k)},
    )


def _newest_first(items: list[tuple[Path, dict]]) -> list[tuple[Path, dict]]:
    return sorted(items, key=lambda it: str(it[1].get("uploaded_at", "")), reverse=True)


def upload_entries(
    upload_dir: Path, *, warnings: list[str] | None = None
) -> list[CatalogEntry]:
    """완료된 업로드 → 카탈로그 항목. doc_id마다 가장 늦게 올린 것 하나. 깨진 항목은 건너뛴다."""
    warn = warnings.append if warnings is not None else (lambda message: None)
    completed = [
        it for it in _manifests(upload_dir) if it[1].get("status") == "completed"
    ]
    chosen: dict[str, CatalogEntry] = {}
    for folder, record in _newest_first(completed):
        try:
            entry = upload_entry(folder, record)
        except (KeyError, ValidationError, TypeError) as exc:
            warn(
                f"업로드 {folder.name}: 매니페스트가 잘못돼 건너뜀 ({type(exc).__name__})"
            )
            continue
        if entry.doc_id in chosen:
            continue  # 더 늦게 올린 같은 doc_id가 이미 있다
        if not Path(entry.path).is_file():
            warn(f"업로드 {folder.name}: 파일 없음, 건너뜀 ({entry.doc_id})")
            continue
        chosen[entry.doc_id] = entry
    return sorted(chosen.values(), key=lambda e: e.doc_id)


def load_registry(
    catalog_path: str | Path, upload_dir: Path, *, warnings: list[str] | None = None
) -> Catalog:
    """카탈로그(엄격) + 완료된 업로드(항목별). 부딪히는 업로드는 경고와 함께 뺀다."""
    warn = warnings.append if warnings is not None else (lambda message: None)
    catalog = load_catalog(catalog_path)  # 카탈로그 문제는 CatalogError로 멈춘다
    taken_ids = {e.doc_id for e in catalog.documents}
    taken_sha = {file_sha256(catalog.file(e)): e.doc_id for e in catalog.documents}

    documents = list(catalog.documents)
    for entry in upload_entries(upload_dir, warnings=warnings):
        sha = file_sha256(Path(entry.path))
        if entry.doc_id in taken_ids:
            warn(f"업로드 {entry.doc_id}: 카탈로그와 doc_id가 같아 건너뜀")
            continue
        if sha in taken_sha:
            warn(f"업로드 {entry.doc_id}: {taken_sha[sha]}와 같은 내용이라 건너뜀")
            continue
        taken_ids.add(entry.doc_id)
        taken_sha[sha] = entry.doc_id
        documents.append(entry)
    return Catalog(root=catalog.root, documents=documents)


def upload_conflict(
    doc_id: str, sha256: str, catalog_path: str | Path, upload_dir: Path
) -> str | None:
    """새 업로드가 기존 목록과 부딪히면 이유를, 아니면 None을 돌려준다.

    같은 doc_id의 업로드는 개정판으로 보고 허용한다(완료되면 예전 것을 대체).
    진행 중인 업로드도 내용 비교에 넣는다(같은 파일을 동시에 두 번 올리는 경우).
    """
    catalog = load_catalog(catalog_path)
    if any(e.doc_id == doc_id for e in catalog.documents):
        return f"{doc_id}는 카탈로그(data/catalog.toml)가 관리하는 문서다. 다른 doc_id를 쓴다"
    for entry in catalog.documents:
        if file_sha256(catalog.file(entry)) == sha256:
            return f"{entry.doc_id}와 같은 내용의 파일이다. 같은 문서가 두 번 검색·인용된다"
    for _, record in _manifests(upload_dir):
        if (
            record.get("status") in ACTIVE
            and record.get("doc_id") != doc_id
            and record.get("source_sha256") == sha256
        ):
            return (
                f"{record.get('doc_id')}와 같은 내용의 파일이다. "
                "같은 문서가 두 번 검색·인용된다"
            )
    return None


def newer_upload(
    upload_dir: Path, doc_id: str, uploaded_at: str, *, exclude: str
) -> str | None:
    """같은 doc_id로 더 늦게 올린 살아 있는 업로드가 있으면 그 upload_id를 돌려준다.

    같은 문서를 연달아 올렸을 때 먼저 올린 것이 나중에 색인되어 최신을 덮지 않게 한다.
    """
    for _, record in _newest_first(_manifests(upload_dir)):
        if (
            record.get("doc_id") == doc_id
            and record.get("upload_id") != exclude
            and record.get("status") in ACTIVE
            and str(record.get("uploaded_at", "")) > uploaded_at
        ):
            return record.get("upload_id")
    return None


def supersede_uploads(upload_dir: Path, doc_id: str, *, keep: str) -> list[str]:
    """같은 doc_id의 완료된 예전 업로드를 superseded로 바꾸고 그 upload_id들을 돌려준다."""
    changed = []
    for folder, record in _manifests(upload_dir):
        if (
            record.get("doc_id") == doc_id
            and record.get("upload_id") != keep
            and record.get("status") == "completed"
        ):
            record["status"] = "superseded"
            write_manifest(folder, record)
            changed.append(record.get("upload_id"))
    return changed
