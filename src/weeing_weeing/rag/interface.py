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


class InvalidManualError(ValueError):
    """PDF 내용이나 매뉴얼 입력 정보를 처리할 수 없는 경우."""


@lru_cache(maxsize=1)
def get_manual_indexer(
    chroma_dir: Path,
    model_name: str = "BAAI/bge-m3",
) -> Indexer:
    """매뉴얼 색인기를 재사용한다. 모델은 첫 색인 시 로드한다."""
    from weeing_weeing.rag.manual_indexer import ManualIndexer

    return ManualIndexer(
        chroma_dir=chroma_dir,
        model_name=model_name,
    )
