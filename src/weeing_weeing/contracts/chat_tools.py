"""자유 대화 공통 검색 도구 입력·출력. 직책별 열람 ACL 없이 조건·출처 상태를 검증한다."""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from weeing_weeing.contracts.chat import (
    ChatDocumentSource,
    ChatHistorySource,
    ChatIncidentSource,
    ChatModel,
    ChatReportSource,
    ChatSearchConditions,
    NonEmpty,
)
from weeing_weeing.contracts.codes import CODES
from weeing_weeing.contracts.incident import SensorEvidence


class ChatSearchQuery(ChatModel):
    query: str = Field(min_length=1, max_length=2000)
    kind: Literal["MANUAL", "MAINTENANCE_HISTORY"]
    conditions: ChatSearchConditions = Field(default_factory=ChatSearchConditions)
    code: NonEmpty | None = None

    @model_validator(mode="after")
    def _known_code(self) -> Self:
        if self.code is not None and self.code not in CODES:
            raise ValueError("정의되지 않은 설비 오류 코드")
        return self


class ChatSearchHit(ChatModel):
    """검색기가 필터·최신 승인/개정 상태를 검사해 만든 공통 근거 하나.

    실제 문서 위치·보고서 가상 여부는 서버 메타데이터에서 얻고 LLM이 만들지 않는다.
    검색 결과에 점수가 있다는 이유만으로 관련 근거라고 간주하지 않는다(#74·#75).
    """

    source: Annotated[
        ChatDocumentSource | ChatReportSource, Field(discriminator="kind")
    ]
    text: Annotated[NonEmpty, Field(max_length=8000)]


class ChatHistoryQuery(ChatModel):
    """정확한 DB 조회. query 문자열 유사도는 전체 목록·건수 조건으로 사용하지 않는다."""

    conditions: ChatSearchConditions = Field(default_factory=ChatSearchConditions)
    code: NonEmpty | None = None

    @model_validator(mode="after")
    def _known_code(self) -> Self:
        if self.code is not None and self.code not in CODES:
            raise ValueError("정의되지 않은 설비 오류 코드")
        return self


class ChatHistoryResult(ChatModel):
    source: ChatHistorySource
    reports: list[ChatSearchHit] = Field(default_factory=list, max_length=20)
    truncated: bool = Field(strict=True)

    @model_validator(mode="after")
    def _result(self) -> Self:
        if any(hit.source.kind != "REPORT" for hit in self.reports):
            raise ValueError("이력 목록에는 보고서 출처만 사용")
        if len({hit.source.source_id for hit in self.reports}) != len(self.reports):
            raise ValueError("보고서 출처 중복")
        if len(self.reports) != min(self.source.total, self.source.conditions.limit):
            raise ValueError("전체 건수·목록 개수 불일치")
        if self.truncated != (self.source.total > len(self.reports)):
            raise ValueError("목록 생략 여부 불일치")
        return self


class ChatIncidentItem(ChatModel):
    """사번·결재·PLC 문맥 없이 알림의 관측 사실만 전달한다."""

    incident_id: NonEmpty
    process_id: NonEmpty
    asset_id: NonEmpty
    codes: list[NonEmpty] = Field(min_length=1)
    severity: Literal["Warning", "Error"]
    status: Literal["OPEN", "ACKNOWLEDGED", "RECOVERED", "CLOSED"]
    first_detected_at: AwareDatetime
    confirmed_at: AwareDatetime | None = None
    last_detected_at: AwareDatetime
    recovered_at: AwareDatetime | None = None
    evidence: list[SensorEvidence] = Field(default_factory=list)


class ChatIncidentResult(ChatModel):
    source: ChatIncidentSource
    incidents: list[ChatIncidentItem] = Field(default_factory=list, max_length=20)
    truncated: bool = Field(strict=True)
    latest_recovered_only: bool = Field(strict=True)

    @model_validator(mode="after")
    def _selection(self) -> Self:
        if [item.incident_id for item in self.incidents] != self.source.incident_ids:
            raise ValueError("출처와 사건 목록 불일치")
        if self.truncated != (self.source.total > len(self.incidents)):
            raise ValueError("사건 목록 생략 여부 불일치")
        query = self.source.query
        latest = (
            query.state == "RECOVERED"
            and query.time_from is None
            and query.time_to is None
            and query.incident_id is None
        )
        if self.latest_recovered_only != latest or (latest and query.limit != 1):
            raise ValueError("최근 회복 사건 선택 정책 불일치")
        statuses = (
            {"OPEN", "ACKNOWLEDGED"}
            if query.state == "ACTIVE"
            else {"RECOVERED", "CLOSED"}
        )
        for item in self.incidents:
            at = (
                item.first_detected_at if query.state == "ACTIVE" else item.recovered_at
            )
            if (
                item.status not in statuses
                or at is None
                or (query.asset_id is not None and item.asset_id != query.asset_id)
                or (query.severity is not None and item.severity != query.severity)
                or (query.code is not None and query.code not in item.codes)
                or (
                    query.incident_id is not None
                    and item.incident_id != query.incident_id
                )
                or (query.time_from is not None and at < query.time_from)
                or (query.time_to is not None and at > query.time_to)
            ):
                raise ValueError("조회 조건과 사건 불일치")
        return self
