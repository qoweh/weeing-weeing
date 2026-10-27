"""모듈 사이에서 주고받는 데이터 계약.

모든 모듈은 서로의 내부 구현이 아니라 이 패키지의 모델로만 소통한다.
나중에 모듈을 별도 서비스로 떼어낼 때 이 모델이 그대로 HTTP JSON 스키마가 된다.

- telemetry: 센서 1초 집계 한 줄 (공통 데이터 규격 v3, 15컬럼)
- codes: 룰 코드와 판정 등급 (BTT-RULE v2.0)
- incident: 이상 사건 기록
- analysis: RAG 검색 근거와 AI 분석 결과
- report: 정비 보고서와 결재
- document: 문서 레지스트리 한 줄(색인 대상 문서와 업로드 처리 상태)

바꿀 때는 docs/CONTRACTS.md를 함께 고치고, 사용하는 모듈 담당자에게 알린다.
"""

from weeing_weeing.contracts.analysis import AnalysisResult, CauseCandidate, Evidence
from weeing_weeing.contracts.codes import CODES, RULE_VERSION, Severity
from weeing_weeing.contracts.document import DocumentRecord
from weeing_weeing.contracts.incident import Incident, IncidentStatus, SensorEvidence
from weeing_weeing.contracts.report import MaintenanceReport, ReportStatus, Role
from weeing_weeing.contracts.telemetry import SCHEMA_VERSION, TelemetryRecord

__all__ = [
    "CODES",
    "RULE_VERSION",
    "SCHEMA_VERSION",
    "AnalysisResult",
    "CauseCandidate",
    "DocumentRecord",
    "Evidence",
    "Incident",
    "IncidentStatus",
    "MaintenanceReport",
    "ReportStatus",
    "Role",
    "SensorEvidence",
    "Severity",
    "TelemetryRecord",
]
