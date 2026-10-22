from pathlib import Path
from typing import Any, Protocol

from weeing_weeing.contracts import Evidence


class Indexer(Protocol):
    def index_file(self, path: Path, metadata: dict[str, Any]) -> int:
        """문서 하나를 색인하고 만든 청크 수를 돌려준다. 같은 문서를 다시 넣으면 교체한다.

        metadata에는 최소 doc_id, doc_version을 넣는다(인용 문자열 생성에 필요).
        """
        ...


class Retriever(Protocol):
    def search(
        self, query: str, *, k: int = 5, filters: dict[str, Any] | None = None
    ) -> list[Evidence]:
        """관련도 순으로 근거를 돌려준다. filters 예: {"code": "BTT2-P01"}"""
        ...
