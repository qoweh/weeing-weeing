"""다른 모듈이 RAG 기능을 사용하는 공개 진입점과 호출 계약.

Indexer·Retriever Protocol은 구현체가 제공할 메서드 형태를 정의한다.
get_indexer()·get_retriever()는 설정에 맞는 실제 구현체를 만들어 재사용한다.
문서 레지스트리 관련 함수도 여기서 노출하므로 외부 모듈은 rag 내부 파일 대신
이 interface.py와 공통 contracts를 import해 기능을 연결한다.
"""

from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from weeing_weeing.contracts import DocumentRecord, Evidence, Incident

# 기존 호출자가 공개 인터페이스에서 구현 클래스를 가져갈 수 있도록 다시 노출한다.
from weeing_weeing.rag.retriever import HybridRetriever as HybridRetriever
from weeing_weeing.rag.store import VectorStore

# 색인 진행 단계 이름(예: parsing, chunking)을 받아 화면·로그 등에 전달하는 함수 형식.
ProgressCallback = Callable[[str], None]


class Indexer(Protocol):
    """문서 색인 구현체의 계약. 실제 파싱·청킹·저장은 DocumentIndexer가 수행한다."""

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
    """문자열 질문을 받아 출처가 있는 Evidence를 반환하는 검색 구현체의 계약."""

    def search(
        self, query: str, *, k: int = 5, filters: dict[str, Any] | None = None
    ) -> list[Evidence]:
        """관련도 순으로 최대 k개의 근거를 돌려준다. 없으면 빈 리스트다.

        HybridRetriever에 저장소를 주입해 사용한다. filters의 code는 저장소의
        codes 별칭이다(둘을 함께 쓰면 오류). 예: {"code": "BTT2-P01"}.
        나머지 키는 저장소 메타데이터 필터로 전달한다. 여러 키는 AND,
        리스트 값은 하나라도 일치하면 된다. 빈 리스트·None 값은 허용하지 않는다.
        query는 공백만 있는 문자열일 수 없고 k는 1 이상의 정수다.
        score는 원래의 RRF 점수다. 리랭킹을 켜면 반환 순서만 달라지므로
        score 내림차순을 보장하지 않는다. 확률·근거 충분성 임계값으로 쓰지 않는다.
        검색·리랭킹 실패는 예외로 전달한다.
        """
        ...


class InvalidDocumentError(ValueError):
    """문서를 색인할 수 없다(형식·내용·입력 정보 문제). 사용자에게 보여 줄 메시지를 담는다."""


# #56 업로드 API가 쓰던 이름. 매뉴얼 외 문서도 처리하므로 InvalidDocumentError로 통일했다.
InvalidManualError = InvalidDocumentError


@lru_cache(maxsize=1)
def _get_store() -> VectorStore:
    """설정에 맞는 저장소를 처음 한 번 만들고 색인기·검색기에 공유하는 내부 함수.

    lru_cache(maxsize=1)가 반환 객체 하나를 보관한다. 같은 프로세스의 색인·검색이
    Qdrant 로컬 폴더를 중복 개방하지 않도록 get_indexer()·get_retriever()가 함께 쓴다.
    """
    # 생성 시점에 가져와 interface와 factory의 상호 참조가 초기 import를 막지 않게 한다.
    from weeing_weeing.config import get_settings
    from weeing_weeing.rag.factory import build_store

    return build_store(get_settings())


@lru_cache(maxsize=1)
def get_retriever() -> Retriever:
    """프로세스에서 재사용할 검색기. RERANKER_MODEL이 있으면 리랭킹한다.

    api 또는 실행 스크립트에서 조립해 Agent에 주입한다.
    저장소·모델은 매 요청마다 생성하지 않는다. 공유 저장소를 호출 중 닫지 않는다.
    factory가 공유 저장소와 선택적 리랭커를 HybridRetriever에 연결한다.
    lru_cache가 완성된 검색기 객체를 보관해 이후 호출에도 같은 객체를 반환한다.
    """
    from weeing_weeing.config import get_settings
    from weeing_weeing.rag.factory import build_retriever

    return build_retriever(get_settings(), _get_store())


@lru_cache(maxsize=1)
def get_indexer() -> Indexer:
    """API 서버용 Indexer. 저장소(.env의 VECTOR_STORE 등)는 프로세스당 한 번만 조립한다.

    make index와 같은 Indexer·저장소 설정을 쓴다. 업로드 원본 옆에 검토용 미리보기를 남긴다.
    임베딩 모델은 첫 색인 때 올라온다.
    lru_cache가 색인기 객체를 재사용하며, 저장소는 get_retriever()와 공유한다.
    """
    from weeing_weeing.rag.indexer import DocumentIndexer

    return DocumentIndexer(_get_store(), write_previews=True)


# 문서 레지스트리(DB의 document 행) ↔ 색인. 구현은 rag/registry.py.
# DB를 읽고 쓰는 일은 api·실행 스크립트가 db.interface로 한다.
def seed_records(catalog_path: Path) -> list[DocumentRecord]:
    """카탈로그의 기준 문서 목록을 DB에 반영할 DocumentRecord 목록으로 변환한다.

    실제 변환은 registry.seed_records()에 위임한다. 이 함수가 DB에 직접 저장하지는
    않으며 호출자가 db.interface로 반영한다. 잘못된 카탈로그는 ValueError로 알린다.
    """
    from weeing_weeing.rag.registry import seed_records as load

    return load(catalog_path)


def upload_index_metadata(record: DocumentRecord, upload_dir: Path) -> dict[str, str]:
    """업로드 문서 기록으로부터 index_file()에 전달할 색인 메타데이터를 만든다.

    entry_from_record()가 원본 경로와 문서 정보를 정리하고, file_sha256()이 현재
    파일의 내용 해시를 구한다. index_metadata()는 make index와 동일한 형식으로
    조립해 업로드 색인과 재색인의 변경 감지 기준을 맞춘다.
    """
    from weeing_weeing.rag.catalog import file_sha256
    from weeing_weeing.rag.registry import entry_from_record
    from weeing_weeing.rag.sync import index_metadata

    entry = entry_from_record(record, upload_dir)
    return index_metadata(entry, file_sha256(Path(entry.path)))


def incident_query(incident: Incident) -> str:
    """Incident → Retriever.search에 넣을 질의문. 구현은 rag/query.py.

    짧은 코드 + 코드 이름 + 대응 문구. 예: BTT2-P03 →
    "P03 입구 장기 점유 발생 시 원인 점검과 현장 대응 절차"
    """
    from weeing_weeing.rag.query import incident_query as build

    return build(incident)
