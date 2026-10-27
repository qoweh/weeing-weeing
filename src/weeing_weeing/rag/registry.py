"""문서 레지스트리(DB의 document 행) ↔ 색인 목록(Catalog).

    data/catalog.toml ──seed_records()──▶ DB document(origin=seed) ◀── 업로드 API(origin=upload)
    DB의 completed 행 ──catalog_from_records()──▶ Catalog ──▶ sync(make index)

DB를 읽고 쓰는 일은 실행 스크립트·API가 db.interface로 한다. rag는 DocumentRecord(contracts)만
받아 색인 목록으로 바꾼다(rag는 db를 import하지 않는다).

검증 원칙: 카탈로그(팀 파일)는 엄격하게 검증해 문제가 있으면 멈춘다. 업로드는 항목별로
처리해서, 파일이 없거나 카탈로그·다른 업로드와 부딪히는 항목은 건너뛰고 경고만 남긴다.
업로드 하나 때문에 팀 전체의 make index가 멈추지 않게 하기 위해서다.
"""

from collections.abc import Iterable
from pathlib import Path

from pydantic import ValidationError

from weeing_weeing.contracts import DocumentRecord
from weeing_weeing.rag.catalog import (
    Catalog,
    CatalogEntry,
    file_sha256,
    load_catalog,
)


def seed_records(catalog_path: str | Path) -> list[DocumentRecord]:
    """카탈로그 → seed 행. 카탈로그 문제는 CatalogError(ValueError)로 멈춘다."""
    catalog = load_catalog(catalog_path)
    return [
        DocumentRecord(
            doc_id=entry.doc_id,
            doc_version=entry.doc_version,
            doc_type=entry.doc_type,
            doc_status=entry.status,
            origin="seed",
            title=entry.title,
            source=entry.path,
            source_sha256=file_sha256(catalog.file(entry)),
            extra=dict(entry.extra),
        )
        for entry in catalog.documents
    ]


def entry_from_record(record: DocumentRecord, upload_dir: Path) -> CatalogEntry:
    """DB 행 → 카탈로그 항목. seed는 catalog.toml 폴더 기준 경로, 업로드는 절대 경로.

    값이 잘못되면 ValidationError(extra에 예약 키 등).
    """
    if record.origin == "seed":
        path = record.source
    else:
        path = str((upload_dir / record.source).resolve())
    extra = dict(record.extra)
    if record.upload_id:
        extra["upload_id"] = record.upload_id
    return CatalogEntry(
        doc_id=record.doc_id,
        doc_version=record.doc_version,
        doc_type=record.doc_type,
        status=record.doc_status,
        path=path,
        title=record.title,
        extra=extra,
    )


def catalog_from_records(
    records: Iterable[DocumentRecord],
    *,
    seed_root: Path,
    upload_dir: Path,
    warnings: list[str] | None = None,
) -> Catalog:
    """색인 목록을 만든다. seed를 먼저 넣고, 부딪히는 업로드는 경고와 함께 뺀다."""
    warn = warnings.append if warnings is not None else (lambda message: None)
    ordered = sorted(records, key=lambda r: (r.origin != "seed", r.doc_id))
    catalog = Catalog(root=seed_root, documents=[])
    documents: list[CatalogEntry] = []
    taken_sha: dict[str, str] = {}
    for record in ordered:
        label = "카탈로그" if record.origin == "seed" else f"업로드 {record.upload_id}"
        try:
            entry = entry_from_record(record, upload_dir)
        except ValidationError as exc:
            warn(
                f"{label}: 값이 잘못돼 건너뜀 ({record.doc_id}, {exc.error_count()}건)"
            )
            continue
        if any(e.doc_id == entry.doc_id for e in documents):
            warn(f"{label}: doc_id {entry.doc_id}가 이미 목록에 있어 건너뜀")
            continue
        file = catalog.file(entry)
        if not file.is_file():
            warn(f"{label}: 파일 없음, 건너뜀 ({entry.doc_id})")
            continue
        sha = record.source_sha256
        if sha in taken_sha:
            warn(f"{label}: {taken_sha[sha]}와 같은 내용이라 건너뜀 ({entry.doc_id})")
            continue
        taken_sha[sha] = entry.doc_id
        documents.append(entry)
    return Catalog(root=seed_root, documents=documents)
