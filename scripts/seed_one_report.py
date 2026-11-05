"""로컬 테스트용 고온 사건과 승인 보고서 한 건을 준비한다.

실제 센서 측정·LLM 호출·사람의 조치가 아니라 미리 작성한 사례다.
실행은 사용자의 환경에서만 하며, 실제 계정 대신 시연 계정을 지정한다.
"""

import argparse
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from weeing_weeing.config import get_settings
from weeing_weeing.contracts import (
    AnalysisResult,
    Incident,
    ReportDraft,
    ReportFormData,
)
from weeing_weeing.contracts.analysis import CauseCandidate, Evidence
from weeing_weeing.contracts.incident import SensorEvidence
from weeing_weeing.db import interface as db

INCIDENT_ID = "INC-SAMPLE-M10-DUST-001"


def seed(incidents, reports, users, author, reviewer, approver):
    """기존 저장소로 한 건을 만들며, 기존 사건이 있으면 덮어쓰지 않는다."""
    if len({author, reviewer, approver}) != 3:
        raise ValueError("작성자와 결재자는 서로 다른 시연 계정이어야 합니다.")
    for employee, role in (
        (author, "현장 점검자"),
        (reviewer, "보전 팀장"),
        (approver, "관제 담당자"),
    ):
        user = users.get_user(employee)
        if user is None or not user.is_active or user.role != role:
            raise ValueError(f"활성 {role} 시연 계정을 확인하세요: {employee}")
    if incidents.get_incident(INCIDENT_ID) is not None:
        raise ValueError("샘플 사건이 이미 있습니다. 중복 등록을 중단합니다.")
    now = datetime.now(UTC)
    incident = Incident(
        incident_id=INCIDENT_ID,
        process_id="BAT-TRANSFER-01",
        asset_id="BLDC-001",
        codes=["BTT2-M10"],
        severity="Error",
        first_detected_at=now - timedelta(minutes=30),
        confirmed_at=now - timedelta(minutes=29, seconds=50),
        last_detected_at=now - timedelta(minutes=29, seconds=50),
        evidence=[
            SensorEvidence(
                field="motor_housing_temp_c",
                value=95.0,
                unit="℃",
                threshold="90℃ 이상 10초",
            )
        ],
    )
    incidents.save_incident(incident)
    evidence = Evidence(
        evidence_id="sample-manual-m10",
        doc_id="BTT-MANUAL",
        doc_version="2.0",
        title="BTT-MANUAL_v2.0.pdf",
        page=6,
        section="05 공급전압·외함 온도 대응",
        text="접근·접촉 위험 통제, 온도 실측·위치 대조 후 부하·방열·주변 온도·기계 마찰 점검.",
        citation="BTT-MANUAL v2.0 PDF 6쪽",
    )
    incidents.save_analysis(
        AnalysisResult(
            incident_id=INCIDENT_ID,
            status="OK",
            observed_facts="모터 외함 온도 95℃ 감지",
            suspected_causes=[
                CauseCandidate(
                    cause="방열 상태 저하",
                    likelihood="미평가",
                    basis="매뉴얼은 방열 상태 점검을 권고한다.",
                    evidence_ids=[evidence.evidence_id],
                )
            ],
            recommended_checks=[
                "접근 위험을 통제하고 온도 실측 및 위치 대조 후 방열 상태를 확인한다."
            ],
            evidence=[evidence],
            model="sample/manual",
            generated_at=now - timedelta(minutes=25),
        )
    )
    doc = reports.create_draft(
        author,
        ReportDraft(
            incident_id=INCIDENT_ID,
            data_origin="LIVE",
            form_data=ReportFormData(
                actual_actions="모터 주변 접근 위험을 통제한 뒤 외함 온도와 센서 부착 상태를 확인했다. 방열구의 분진을 청소하고 주변 공기 흐름을 확인했다.",
                action_at=now - timedelta(minutes=15),
                replaced_parts="없음",
                confirmed_cause="방열구에 쌓인 분진으로 방열이 원활하지 않았다.",
                ai_assessment="부분 일치",
                trial_result="정상",
                resolution="해결",
                trial_details="청소 후 외함 온도가 정상 범위로 내려왔고 10초 이상 유지되는 동안 고온 알람이 재발하지 않았다.",
            ),
        ),
    )
    for actor, action in (
        (author, "submit"),
        (reviewer, "review"),
        (approver, "approve"),
    ):
        doc = reports.transition(
            actor, doc.report_id, action, expected_revision=doc.revision
        )
    return doc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--author", required=True, help="현장 점검 시연 계정 사번")
    parser.add_argument("--reviewer", required=True, help="보전 팀장 시연 계정 사번")
    parser.add_argument("--approver", required=True, help="관제 담당 시연 계정 사번")
    args = parser.parse_args()
    url = get_settings().database_url
    parsed = urlsplit(url)
    if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise SystemExit("로컬 PostgreSQL에서만 실행할 수 있습니다.")
    incidents = db.open_incidents(url)
    reports = db.open_reports(url)
    users = db.open_users(url)
    try:
        doc = seed(incidents, reports, users, args.author, args.reviewer, args.approver)
        print(
            f"사건 {doc.incident_id} / 보고서 {doc.report_id} / 상태 {doc.report_status} / 검색 등록 {doc.index_status}"
        )
        print(
            "검색 등록: make index-reports (실패 시 make index-reports ARGS=--retry-failed)"
        )
    finally:
        incidents._engine.dispose()
        reports._engine.dispose()
        users._engine.dispose()


if __name__ == "__main__":
    main()
