"""색인 대상 문서 목록(data/catalog.toml) 모델·로더·검증.

파일명을 파싱하지 않고 문서 ID·버전·종류·상태를 명시적으로 적는다. 파일명 규칙을 어기면
조용히 틀리고, 초안/승인 같은 상태는 파일명으로 표현할 수 없기 때문이다.
"""

import hashlib
import tomllib
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from weeing_weeing.contracts.document import DocStatus, DocType

# 청크 ID 구분자(':')와 공백은 ID·버전에 쓸 수 없다.
_ID = r"^[^:\s]+$"


class CatalogError(ValueError):
    """카탈로그 파일이 잘못됐다. 문제를 한 번에 모두 알린다."""


class CatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: str = Field(pattern=_ID)
    doc_version: str = Field(pattern=_ID)
    doc_type: DocType
    status: DocStatus
    path: str = Field(min_length=1)  # catalog.toml이 있는 폴더 기준(업로드는 절대 경로)
    title: str = Field(min_length=1)
    # 청크 메타데이터에 함께 넣을 값(업로드의 asset_id·upload_id 등). 표준 키는 덮어쓰지 않는다.
    extra: dict[str, str] = Field(default_factory=dict)

    @field_validator("extra")
    @classmethod
    def _extra_keys(cls, value: dict[str, str]) -> dict[str, str]:
        """표준·파생·저장소 키는 extra로 넣을 수 없다(청크 값을 덮어쓰거나 저장이 거부됨)."""
        reserved = {
            "doc_id",
            "doc_version",
            "doc_type",
            "status",
            "title",
            "source_path",
            "source_sha256",
            "page",
            "section",
            "codes",
            "citation",
            "chunk_id",
            "text",
            "chunk_total",
        }
        bad = sorted(set(value) & reserved)
        if bad:
            raise ValueError(f"extra에 쓸 수 없는 키: {bad}")
        return value


class Catalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    root: Path  # catalog.toml이 있는 폴더
    documents: list[CatalogEntry]

    def file(self, entry: CatalogEntry) -> Path:
        return self.root / entry.path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_catalog(path: str | Path) -> Catalog:
    """읽고 검증한다: 형식, doc_id 중복, 파일 존재, 서로 다른 항목의 같은 파일 내용."""
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        catalog = Catalog(root=path.parent, documents=raw.get("documents", []))
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise CatalogError(f"{path}: {exc}") from exc
    validate_catalog(catalog, label=str(path))
    return catalog


def validate_catalog(catalog: Catalog, *, label: str) -> None:
    """doc_id 중복, 파일 없음, 서로 다른 항목의 같은 파일 내용을 한 번에 모아 알린다."""
    problems: list[str] = []
    counts = Counter(e.doc_id for e in catalog.documents)
    problems += [f"doc_id 중복: {d}" for d, n in counts.items() if n > 1]

    by_sha: dict[str, list[str]] = {}
    for entry in catalog.documents:
        file = catalog.file(entry)
        if not file.is_file():
            problems.append(f"{entry.doc_id}: 파일 없음 {entry.path}")
            continue
        by_sha.setdefault(file_sha256(file), []).append(entry.doc_id)
    # 같은 내용이 두 문서로 색인되면 검색 상위가 중복으로 차고 인용 출처가 헷갈린다.
    problems += [
        f"내용이 같은 파일(SHA-256 {sha[:8]}…): {', '.join(ids)}"
        for sha, ids in by_sha.items()
        if len(ids) > 1
    ]
    if problems:
        raise CatalogError(f"{label}:\n  " + "\n  ".join(problems))
