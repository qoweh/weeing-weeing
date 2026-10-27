"""문서 레지스트리 한 줄: 색인 대상 문서 하나의 정보와 처리 상태.

db가 저장하고, rag가 색인 목록으로 쓰고, api가 업로드 상태로 돌려준다.

- origin: seed(data/catalog.toml에서 옮긴 기준 문서) · upload(업로드 API) · report(승인 보고서, #29)
- status: 업로드 처리 상태. seed는 등록되면 바로 completed다.
  같은 doc_id의 completed는 하나뿐이다(색인 목록에 들어가는 행).
- source: 원본 파일 경로. seed는 catalog.toml 폴더 기준, upload는 UPLOAD_DIR 기준
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DocType = Literal["manual", "rule", "sop", "report"]
DocStatus = Literal["approved", "draft"]  # 문서 자체의 승인 상태
DocOrigin = Literal["seed", "upload", "report"]
DocumentStatus = Literal["queued", "processing", "completed", "failed", "superseded"]

# 청크 ID({doc_id}:{doc_version}:{순번})의 구분자 ':'와 공백은 쓸 수 없다.
DOC_ID_PATTERN = r"^[^:\s]+$"


class DocumentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    doc_id: str = Field(pattern=DOC_ID_PATTERN, max_length=128)
    doc_version: str = Field(pattern=DOC_ID_PATTERN, max_length=128)
    doc_type: DocType
    doc_status: DocStatus = "approved"
    origin: DocOrigin
    title: str = Field(min_length=1)
    source: str = Field(min_length=1)
    source_sha256: str
    upload_id: str | None = None  # upload만. 업로드 건마다 하나
    status: DocumentStatus = "completed"
    stage: str | None = None  # 처리 단계(화면 진행 표시용)
    file_size: int | None = None
    chunk_count: int | None = None
    error: str | None = None  # 사용자에게 보여 줄 실패 사유
    error_type: str | None = None
    superseded_by: str | None = None  # 대체한 upload_id, 카탈로그에 밀렸으면 "seed"
    # 청크 메타데이터로 옮길 값(asset_id 등)
    extra: dict[str, str] = Field(default_factory=dict)
    uploaded_at: datetime | None = None
    completed_at: datetime | None = None
    indexed_at: datetime | None = None  # 마지막으로 make index가 확인한 시각
    index_error: str | None = None  # 마지막 make index에서 실패한 사유

    @model_validator(mode="after")
    def _upload_has_id(self) -> "DocumentRecord":
        if self.origin == "upload" and not self.upload_id:
            raise ValueError("upload 문서는 upload_id가 필요하다")
        return self
