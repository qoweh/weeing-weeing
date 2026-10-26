from pathlib import Path
from typing import Any, Protocol

from weeing_weeing.contracts import Evidence


class Indexer(Protocol):
    def index_file(self, path: Path, metadata: dict[str, Any]) -> int:
        """문서 하나를 색인하고 만든 청크 수를 돌려준다. 같은 문서를 다시 넣으면 교체한다.

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
