from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from weeing_weeing.contracts import Evidence

ProgressCallback = Callable[[str], None]


class Indexer(Protocol):
    def index_file(
        self,
        path: Path,
        metadata: dict[str, Any],
        *,
        on_progress: ProgressCallback | None = None,
    ) -> int:
        """문서를 색인하고 청크 수를 반환한다.

        같은 문서는 교체하고, on_progress가 있으면 처리 단계를 알린다.
        metadata에는 최소 doc_id, doc_version을 넣는다(인용 문자열 생성에 필요).
        카탈로그 동기화(rag/sync.py)는 doc_id·doc_version·doc_type·status·title·
        source_path·source_sha256을 넘긴다. 이 값을 바꾸지 말고 모든 청크의 메타데이터에
        그대로 넣는다. 청크 ID는 이 doc_id·doc_version으로 만든다. 값을 바꾸면 변경 감지가
        깨져서 sync가 그 문서를 failed로 보고한다.
        """
        ...


class Retriever(Protocol):
    def search(
        self, query: str, *, k: int = 5, filters: dict[str, Any] | None = None
    ) -> list[Evidence]:
        """관련도 순으로 근거를 돌려준다. filters 예: {"code": "BTT2-P01"}"""
        ...


class InvalidDocumentError(ValueError):
    """문서를 색인할 수 없다(형식·내용·입력 정보 문제). 사용자에게 보여 줄 메시지를 담는다."""


# #56 업로드 API가 쓰던 이름. 매뉴얼 외 문서도 처리하므로 InvalidDocumentError로 통일했다.
InvalidManualError = InvalidDocumentError


@lru_cache(maxsize=1)
def get_indexer() -> Indexer:
    """API 서버용 Indexer. 저장소(.env의 VECTOR_STORE 등)는 프로세스당 한 번만 조립한다.

    make index와 같은 Indexer·저장소 설정을 쓴다. 업로드 원본 옆에 검토용 미리보기를 남긴다.
    임베딩 모델은 첫 색인 때 올라온다.
    """
    from weeing_weeing.config import get_settings
    from weeing_weeing.rag.factory import build_store
    from weeing_weeing.rag.indexer import DocumentIndexer

    return DocumentIndexer(build_store(get_settings()), write_previews=True)


# 업로드 문서 목록(레지스트리) 관련. 구현은 rag/registry.py.
def upload_conflict(
    doc_id: str, sha256: str, catalog_path: Path, upload_dir: Path
) -> str | None:
    """새 업로드가 카탈로그·기존 업로드와 부딪히면 이유를 돌려준다."""
    from weeing_weeing.rag.registry import upload_conflict as check

    return check(doc_id, sha256, catalog_path, upload_dir)


def upload_index_metadata(folder: Path, record: dict[str, Any]) -> dict[str, str]:
    """업로드 매니페스트 → index_file에 넘길 metadata. make index가 계산하는 값과 같다."""
    from weeing_weeing.rag.catalog import file_sha256
    from weeing_weeing.rag.registry import upload_entry
    from weeing_weeing.rag.sync import index_metadata

    entry = upload_entry(folder, record)
    return index_metadata(entry, file_sha256(Path(entry.path)))


def newer_upload(
    upload_dir: Path, doc_id: str, uploaded_at: str, *, exclude: str
) -> str | None:
    """같은 doc_id로 더 늦게 올린 업로드가 있으면 그 upload_id(먼저 올린 것은 색인하지 않는다)."""
    from weeing_weeing.rag.registry import newer_upload as find

    return find(upload_dir, doc_id, uploaded_at, exclude=exclude)


def supersede_uploads(upload_dir: Path, doc_id: str, *, keep: str) -> list[str]:
    """같은 doc_id의 예전 업로드를 superseded로 바꾼다(개정판 업로드 완료 후)."""
    from weeing_weeing.rag.registry import supersede_uploads as supersede

    return supersede(upload_dir, doc_id, keep=keep)
