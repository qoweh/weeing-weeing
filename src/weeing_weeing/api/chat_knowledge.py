"""#88: API가 DB·공유 RAG를 조립하는 공통 문서 검색 구현. 인증은 호출 API 책임이다."""

import hashlib
import json
import math
import time
from functools import lru_cache
from zoneinfo import ZoneInfo

from weeing_weeing.agent.interface import (
    InvalidChatQueryError,
    LlmTimeoutError,
    get_chat_service,
)
from weeing_weeing.contracts import (
    ChatDocumentSource,
    ChatHistorySource,
    ChatReportSource,
    ChatSearchConditions,
    DocumentRecord,
    MaintenanceReport,
)
from weeing_weeing.contracts.chat_tools import (
    ChatHistoryQuery,
    ChatHistoryResult,
    ChatSearchHit,
    ChatSearchQuery,
)
from weeing_weeing.db.interface import (
    DocumentRepository,
    ReportRepository,
    get_documents,
    get_reports,
)
from weeing_weeing.rag.interface import (
    MetadataRetriever,
    get_retriever,
    report_search_hit,
)

SEOUL = ZoneInfo("Asia/Seoul")


class _Budget:
    """DB·검색 호출이 끝날 때마다 전체 검색 시간 예산을 넘었는지 확인한다."""

    def __init__(self, seconds: float):
        if not math.isfinite(seconds) or seconds <= 0:
            raise LlmTimeoutError("검색 시간 초과")
        self.end = time.monotonic() + seconds

    def check(self):
        if time.monotonic() >= self.end:
            raise LlmTimeoutError("검색 시간 초과")


class DatabaseChatKnowledge:
    """직책 ACL 없이 현재 문서·최신 승인 보고서만 검색한다.

    기간은 한국 시간의 실제 조치일(양 끝 포함), 건수는 보고서 수다.
    DB/벡터 클라이언트 자체 타임아웃 외에 호출 전후 전체 예산을 검사한다.
    로컬 임베딩 호출은 실행 중 강제 중단할 수 없다.
    """

    def __init__(
        self,
        retriever: MetadataRetriever,
        documents: DocumentRepository,
        reports: ReportRepository,
    ):
        self.retriever = retriever
        self.documents = documents
        self.reports = reports

    def _documents(self) -> list[DocumentRecord]:
        """현재 등록된 승인 문서만 고른다. 같은 문서의 구버전 보관 목록은 아니다."""
        return [
            r
            for r in self.documents.listed()
            if r.doc_type in {"manual", "sop", "rule"}
            and r.doc_status == "approved"
            and r.status == "completed"
        ]

    def _reports(self) -> list[MaintenanceReport]:
        """각 보고서의 최신 승인 판을 읽는다. 오래전에 작성된 보고서도 대상이다."""
        # DB도 제한하지만 외부 구현체를 주입하는 경우에도 정책을 유지한다.
        return [
            r
            for r in self.reports.approved_reports()
            if r.report_status == "APPROVED" and r.maintenance is not None
        ]

    @staticmethod
    def _validate(conditions: ChatSearchConditions, *, manual: bool):
        """자료에 없는 필터는 무시하지 않고 재질문할 수 있는 입력 오류로 구분한다."""
        if conditions.model is not None and not manual:
            raise InvalidChatQueryError(
                "정비 보고서에 설비 모델 정보가 없어 모델 조건을 지원하지 않습니다. 설비 ID를 지정해 주세요."
            )
        if manual and (conditions.date_from or conditions.date_to):
            raise InvalidChatQueryError(
                "매뉴얼에는 정비 조치일이 없습니다. 기간은 정비이력 조회에 사용해 주세요."
            )

    def validate_query(self, query: ChatSearchQuery, *, timeout_s: float) -> None:
        """Claude가 추출한 설비·모델 조건을 DB의 실제 등록 값과 대조한다."""
        budget = _Budget(timeout_s)
        self._validate(query.conditions, manual=query.kind == "MANUAL")
        if query.kind == "MANUAL":
            records = self._documents()
            for key in ("asset_id", "model"):
                value = getattr(query.conditions, key)
                if value is not None and not any(
                    r.extra.get(key) == value for r in records
                ):
                    raise InvalidChatQueryError(
                        f"등록 문서의 {key}에서 확인할 수 없는 조건입니다. 조건을 확인해 주세요."
                    )
        else:
            # 미등록 ID와 기간 내 0건을 구분한다. 승인 사례가 없어도 등록 문서의 설비는 유효하다.
            asset = query.conditions.asset_id
            if asset is not None:
                known = {r.asset_id for r in self._reports()}
                known.update(r.extra.get("asset_id") for r in self._documents())
                if asset not in known:
                    raise InvalidChatQueryError(
                        "등록 자료에 없는 설비 ID입니다. 설비 ID를 확인해 주세요."
                    )
        budget.check()

    def _matching_reports(self, query: ChatHistoryQuery) -> list[MaintenanceReport]:
        """최신 승인 판 전체에서 설비·코드·실제 조치일에 맞는 보고서를 고른다."""
        self._validate(query.conditions, manual=False)
        conditions = query.conditions
        reports = self._reports()
        if conditions.asset_id is not None:
            known = {r.asset_id for r in reports}
            known.update(r.extra.get("asset_id") for r in self._documents())
            if conditions.asset_id not in known:
                raise InvalidChatQueryError(
                    "등록 자료에 없는 설비 ID입니다. 설비 ID를 확인해 주세요."
                )
        selected = []
        for report in reports:
            if (
                conditions.asset_id is not None
                and report.asset_id != conditions.asset_id
            ):
                continue
            if query.code and query.code not in report.incident.codes:
                continue
            dates = [
                a.at.astimezone(SEOUL).date() for a in report.maintenance.actions_taken
            ]
            # 조치가 여러 번이어도 기간에 드는 조치가 하나 이상이면 보고서 1건으로 센다.
            if conditions.date_from or conditions.date_to:
                if not any(
                    (conditions.date_from is None or d >= conditions.date_from)
                    and (conditions.date_to is None or d <= conditions.date_to)
                    for d in dates
                ):
                    continue
            selected.append(report)
        # 조치일 없는 보고서는 기간 조회에서 제외한다. 사건 발생일로 대체하지 않는다.
        return sorted(
            selected,
            key=lambda r: (
                max(
                    (a.at for a in r.maintenance.actions_taken),
                    default=r.incident.first_detected_at,
                ),
                r.report_id,
            ),
            reverse=True,
        )

    def search(
        self, query: ChatSearchQuery, *, timeout_s: float
    ) -> list[ChatSearchHit]:
        """DB로 검색 대상을 좁힌 뒤 RAG 유사 검색을 실행하고 서버 출처를 붙인다."""
        budget = _Budget(timeout_s)
        self.validate_query(query, timeout_s=timeout_s)
        if query.kind == "MANUAL":
            records = {
                r.doc_id: r
                for r in self._documents()
                if all(
                    getattr(query.conditions, key) is None
                    or r.extra.get(key) == getattr(query.conditions, key)
                    for key in ("asset_id", "model")
                )
            }
            versions = {key: r.doc_version for key, r in records.items()}
            reports = {}
        else:
            reports = {
                r.report_id: r
                for r in self._matching_reports(
                    ChatHistoryQuery(conditions=query.conditions, code=query.code)
                )
            }
            records = {}
            versions = {key: str(r.report_version) for key, r in reports.items()}
        # 이 매핑은 사용자 권한 목록이 아니라 현재 판·승인·검색 조건을 통과한 대상이다.
        # 특정 구버전을 지정하는 입력은 없으며, 과거 개정판으로 자동 대체하지 않는다.
        if not versions:
            budget.check()
            return []
        filters = {
            "doc_type": ["manual", "sop", "rule"]
            if query.kind == "MANUAL"
            else "report",
            "status": "approved",
        }
        if query.code:
            filters["code"] = query.code
        budget.check()
        found = self.retriever.search_hits(
            query.query, k=query.conditions.limit, filters=filters, versions=versions
        )
        budget.check()
        results = []
        for hit in found:
            chunk = hit.chunk
            if versions.get(chunk.doc_id) != chunk.doc_version:
                continue
            if query.kind == "MAINTENANCE_HISTORY":
                # 벡터 본문이 아니라 DB 승인 판에서 최소 본문을 재생성한다.
                result = report_search_hit(reports[chunk.doc_id])
            else:
                record = records[chunk.doc_id]
                if chunk.metadata.get("source_sha256") != record.source_sha256:
                    continue  # 같은 버전의 파일 교체·색인 지연도 감지한다.
                page = chunk.metadata.get("page")
                section = chunk.metadata.get("section")
                page = page if type(page) is int and page >= 1 else None
                section = section.strip() if isinstance(section, str) else None
                if page is None and not section:
                    continue  # 위치를 추측해서 만들지 않는다.
                result = ChatSearchHit(
                    source=ChatDocumentSource(
                        source_id=f"{chunk.chunk_id}:{record.source_sha256}",
                        title=record.title,
                        doc_id=record.doc_id,
                        doc_version=record.doc_version,
                        page=page,
                        section=section or None,
                    ),
                    text=chunk.text[:8000],
                )
            if self.is_searchable(
                result.source, timeout_s=max(budget.end - time.monotonic(), 0)
            ):
                if result.source.source_id not in {r.source.source_id for r in results}:
                    results.append(result)
        budget.check()
        return results

    def query_history(
        self, query: ChatHistoryQuery, *, timeout_s: float
    ) -> ChatHistoryResult:
        """유사도 없이 DB 전체 대상에서 정확한 보고서 수와 제한된 목록을 반환한다."""
        budget = _Budget(timeout_s)
        reports = self._matching_reports(query)
        # 전체 승인 판·사람 작성 내용을 해시한다. AI/결재/사번은 출처 본문에 노출하지 않는다.
        snapshot = hashlib.sha256(
            json.dumps(
                [
                    [
                        r.report_id,
                        r.report_version,
                        r.asset_id,
                        r.incident.codes,
                        r.data_origin,
                        r.maintenance.model_dump(mode="json"),
                    ]
                    for r in reports
                ],
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        selection = query.model_dump_json()
        source_id = (
            "history:" + hashlib.sha256((selection + snapshot).encode()).hexdigest()
        )
        source = ChatHistorySource(
            source_id=source_id,
            title="최신 승인 정비 보고서 DB 조회",
            conditions=query.conditions,
            code=query.code,
            total=len(reports),
            synthetic_total=sum(r.data_origin == "SYNTHETIC" for r in reports),
            snapshot=snapshot,
        )
        # total은 전체 보고서 수, limit은 화면·LLM에 전달할 목록 길이에만 적용한다.
        items = [report_search_hit(r) for r in reports[: query.conditions.limit]]
        budget.check()
        return ChatHistoryResult(
            source=source, reports=items, truncated=len(reports) > len(items)
        )

    def is_searchable(self, source, *, timeout_s: float) -> bool:
        """검색 이후 자료가 바뀌지 않았는지 재검사한다. 직책별 열람 권한 검사는 아니다."""
        budget = _Budget(timeout_s)
        if isinstance(source, ChatHistorySource):
            # 0건이 1건이 되는 경우도 잡기 위해 집계 대상 전체의 스냅샷을 다시 비교한다.
            current = self.query_history(
                ChatHistoryQuery(conditions=source.conditions, code=source.code),
                timeout_s=timeout_s,
            )
            result = current.source == source
        elif isinstance(source, ChatDocumentSource):
            # 판 번호가 같아도 파일이 바뀌면 이전 본문을 인용하지 못하도록 해시도 대조한다.
            result = any(
                r.doc_id == source.doc_id
                and r.doc_version == source.doc_version
                and source.source_id.endswith(":" + r.source_sha256)
                for r in self._documents()
            )
        elif isinstance(source, ChatReportSource):
            result = any(
                r.report_id == source.report_id
                and r.report_version == source.report_version
                and (r.data_origin == "SYNTHETIC") == source.synthetic
                for r in self._reports()
            )
        else:
            result = False
        budget.check()
        return result


@lru_cache(maxsize=1)
def get_chat_knowledge() -> DatabaseChatKnowledge:
    """API·CLI에서 공통 DB와 RAG를 한 번 조립한다. 사용자 직책 ACL은 없다."""
    return DatabaseChatKnowledge(get_retriever(), get_documents(), get_reports())


def build_chat_service(*, client=None, knowledge=None):
    """실제 검색기와 기존 Claude를 잇는 실행 진입점. 인증·대화 API는 #91에서 사용한다."""
    return get_chat_service(
        knowledge if knowledge is not None else get_chat_knowledge(), client=client
    )
