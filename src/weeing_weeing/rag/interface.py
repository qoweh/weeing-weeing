from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from weeing_weeing.contracts import DocumentRecord, Evidence
from weeing_weeing.rag.retriever import HybridRetriever as HybridRetriever

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
        """관련도 순으로 최대 k개의 근거를 돌려준다. 없으면 빈 리스트다.

        HybridRetriever에 저장소를 주입해 사용한다. filters의 code는 저장소의
        codes 별칭이다(둘을 함께 쓰면 오류). 예: {"code": "BTT2-P01"}.
        나머지 키는 저장소 메타데이터 필터로 전달한다. 여러 키는 AND,
        리스트 값은 하나라도 일치하면 된다. 빈 리스트·None 값은 허용하지 않는다.
        query는 공백만 있는 문자열일 수 없고 k는 1 이상의 정수다.
        score는 RRF 순위 점수이며 검색 실패는 예외로 전달한다.
        """
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


# 문서 레지스트리(DB의 document 행) ↔ 색인. 구현은 rag/registry.py.
# DB를 읽고 쓰는 일은 api·실행 스크립트가 db.interface로 한다.
def seed_records(catalog_path: Path) -> list[DocumentRecord]:
    """data/catalog.toml → seed 행(DB에 반영할 값). 카탈로그가 잘못되면 ValueError."""
    from weeing_weeing.rag.registry import seed_records as load

    return load(catalog_path)


def upload_index_metadata(record: DocumentRecord, upload_dir: Path) -> dict[str, str]:
    """업로드 행 → index_file에 넘길 metadata. make index가 계산하는 값과 같다."""
    from weeing_weeing.rag.catalog import file_sha256
    from weeing_weeing.rag.registry import entry_from_record
    from weeing_weeing.rag.sync import index_metadata

    entry = entry_from_record(record, upload_dir)
    return index_metadata(entry, file_sha256(Path(entry.path)))
