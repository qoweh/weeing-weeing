"""센서 연결 시험용 M10 가상 보고서 5건. 기본은 JSON 미리보기이며 DB 변경은 --apply."""

import argparse
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from seed_22_reports import index_cases

from weeing_weeing.contracts import (
    AnalysisResult,
    Incident,
    IncidentStatus,
    ReportDraft,
    ReportFormData,
)
from weeing_weeing.contracts.analysis import (
    ActionCitation,
    CauseCandidate,
    CheckCitation,
    Evidence,
)
from weeing_weeing.contracts.incident import SensorEvidence
from weeing_weeing.contracts.telemetry import TelemetryProvenance, TelemetryRecord
from weeing_weeing.db import interface as db

ORIGIN = TelemetryProvenance(origin="SIMULATION")
# 온도·전류·진동의 조합은 비교 기능 시험용 설정이며 물리 모델이나 진단 규칙이 아니다.
SCENARIOS = [
    (
        "방열구 분진",
        "방열구에 분진 축적을 확인했다.",
        "격리 후 방열구 분진을 청소했다.",
        94,
        0.092,
        0.060,
    ),
    (
        "주변 열원",
        "모터 인근 임시 열원을 확인했다.",
        "안전 확보 후 주변 열원을 제거했다.",
        92,
        0.091,
        0.055,
    ),
    (
        "벨트 접촉",
        "벨트와 가이드의 접촉 흔적을 확인했다.",
        "격리 후 가이드 간섭을 조정했다.",
        96,
        0.093,
        0.078,
    ),
    (
        "하중 증가",
        "승인된 조건보다 무거운 시험 트레이가 투입된 것을 확인했다.",
        "시험 하중을 승인된 조건으로 복원했다.",
        95,
        0.0935,
        0.065,
    ),
    (
        "센서 위치",
        "센서가 지정 위치를 벗어나 인접 고온 부위에 부착된 것을 확인했다.",
        "격리·냉각 후 센서를 지정 위치에 다시 고정했다.",
        93,
        0.092,
        0.058,
    ),
]


def build_cases():
    """재실행에도 같은 ID·시각·값을 사용한다. 표본은 실측값이 아니다."""
    cases = []
    for number, (title, cause, action, peak, current, vibration) in enumerate(
        SCENARIOS, 1
    ):
        anchor = datetime(2026, 8, 10 + number, 3, 12, 34, tzinfo=UTC)
        case_id = f"INC-SENSOR-TEST-V3-M10-{number:03d}"
        samples = [
            TelemetryRecord(
                record_id=f"{case_id}:0",
                timestamp=anchor,
                process_id="BAT-TRANSFER-01",
                asset_id="BLDC-001",
                schema_version="3.0.0",
                infeed_present=False,
                outfeed_present=False,
                rpm=1015,
                dc_input_current_a=current,
                dc_bus_voltage_v=24,
                motor_housing_temp_c=peak,
                de_vibration_rms_g=vibration,
                de_kurtosis=4.5,
                nde_vibration_rms_g=0.055,
                nde_kurtosis=4.3,
            )
        ]
        incident = Incident(
            incident_id=case_id,
            process_id="BAT-TRANSFER-01",
            asset_id="BLDC-001",
            codes=["BTT2-M10"],
            severity="Error",
            first_detected_at=anchor,
            confirmed_at=anchor,
            last_detected_at=anchor,
            telemetry_provenance=ORIGIN,
            evidence=[
                SensorEvidence(
                    field="motor_housing_temp_c",
                    value=peak,
                    unit="℃",
                    threshold="고온 이상",
                )
            ],
        )
        summary = (
            f"확정 시점 외함 온도 {peak}℃, DC 입력전류 {current}A, "
            f"구동측 진동 RMS {vibration}g, 회전속도 1015rpm, 전압 24V."
        )
        form = ReportFormData(
            actual_actions=f"접근·접촉 위험 통제 및 필요한 승인 절차 확인. {action}",
            action_at=anchor + timedelta(minutes=10),
            confirmed_cause=f"{cause}",
            cause_evidence=summary,
            trial_result="정상",
            trial_details="정비 후 담당자가 회복 상태를 확인했다.",
            resolution="해결",
        )
        cases.append(
            {
                "title": title,
                "incident": incident,
                "samples": samples,
                "form": form,
                "summary": summary,
            }
        )
    return cases


def without_fixture_labels(value):
    """이 생성기의 초기 표시 문구 차이만 허용한다. 출처 필드는 바꾸지 않는다."""
    if isinstance(value, str):
        value = re.sub(
            r"\[가상\s*(?:시연|설정|현장\s*확인\s*설정|센서\s*시험)\]\s*", "", value
        )
        return re.sub(r"\s*\(가상\s*설정\)", "", value)
    if isinstance(value, dict):
        return {key: without_fixture_labels(item) for key, item in value.items()}
    if isinstance(value, list):
        return [without_fixture_labels(item) for item in value]
    return value


def build_analysis(case):
    """실제 모델·현장 결과를 사용하지 않는 명시적 시연 가이드."""
    incident = case["incident"]
    source = Evidence(
        evidence_id="sensor-fixture-m10-guide-v2",
        doc_id="SENSOR-FIXTURE-M10-GUIDE",
        doc_version="2",
        title="M10 센서 연결 시연용 점검 가이드",
        text=(
            "접근·접촉 위험을 먼저 통제한다. 독립 계측 온도와 센서 부착 위치를 대조한다. "
            "방열구·통풍 경로·주변 열원을 점검한다. 부하·벨트·가이드 접촉은 에너지 차단 후 확인한다. "
            "정상 회복은 즉시 단정하지 않고 온도 추이와 재발 여부를 관찰한다. "
            "재가동·보호 해제 전 승인 요건은 사업장 절차와 제조사 조건을 확인한다. "
            "이 자료는 시험용으로 작성한 가이드이며 승인된 현장 SOP나 실제 검색 결과가 아니다."
        ),
        citation="센서 시험 데이터에 포함된 점검 가이드 v2",
    )
    observations = [case["summary"]]
    # 시연별 비교를 위한 점검 계획이다. 현장에서 확인한 원인을 분석 입력으로 사용하지 않는다.
    plans = {
        "방열구 분진": (
            "방열구·통풍 경로",
            "고온 사건에서 통풍 경로의 상태를 우선 구분한다.",
            "방열구에 먼지나 장애물이 있는지 확인한다.",
            "통풍 경로의 오염·막힘 여부는 현장에서 확인해야 한다.",
            "방열구와 주변 통풍 경로의 오염·장애물 유무를 확인한다.",
            "오염이나 장애물이 발견되면 안전 절차에 따라 정비 방법을 결정한다.",
        ),
        "주변 열원": (
            "주변 온도·열원",
            "고온 사건에서 설치 장소의 주변 온도와 열 영향을 먼저 살펴본다.",
            "모터 주변의 온도와 인접 설비의 열원 유무를 확인한다.",
            "주변 온도와 열원의 존재 여부는 별도 측정이 필요하다.",
            "모터 주변 온도와 인접 열원의 위치·운전 상태를 확인한다.",
            "주변 열 영향이 확인되면 담당자와 설치 환경 개선 방안을 검토한다.",
        ),
        "벨트 접촉": (
            "벨트·가이드 접촉",
            "고온과 함께 기록된 진동 값을 고려해 구동부 접촉 여부를 점검한다.",
            "에너지를 차단하고 벨트·가이드의 정렬과 접촉 흔적을 확인한다.",
            "진동 수치만으로 접촉이나 마찰을 확정할 수 없다.",
            "에너지 차단 후 벨트와 가이드의 접촉 흔적·정렬 상태를 확인한다.",
            "접촉이 확인되면 승인된 절차에 따라 정렬·조정 필요성을 검토한다.",
        ),
        "하중 증가": (
            "운전 부하·이송 조건",
            "기록된 전류와 온도를 참고해 당시 운전 부하와 이송 조건을 살펴본다.",
            "당시 트레이 하중과 설비 운전 조건을 확인한다.",
            "기록된 전류만으로 과부하를 확정할 수 없다.",
            "이상 당시 트레이 하중과 운전 조건을 허용 범위와 비교한다.",
            "운전 조건에 차이가 있으면 담당자와 승인된 설정을 확인한다.",
        ),
        "센서 위치": (
            "온도 센서 부착·열접촉",
            "기록된 외함 온도의 신뢰성을 확인하기 위해 측정 위치를 먼저 대조한다.",
            "독립 계측 온도와 센서 지정 위치·열접촉 상태를 대조한다.",
            "센서 장착 상태와 독립 계측 결과는 아직 확인되지 않았다.",
            "독립 계측 온도와 센서 지정 부착 위치·열접촉 상태를 대조한다.",
            "부착 상태에 문제가 확인되면 안전 절차에 따라 점검·조정을 검토한다.",
        ),
    }
    name, reason, _check, missing, focus_check, focus_action = plans[case["title"]]
    candidates = [
        CauseCandidate(
            cause=name,
            inspection_priority="우선 확인",
            priority_reason=reason,
            basis="M10 시연용 점검 가이드에서 관련 확인 항목을 선정했다.",
            evidence_ids=[source.evidence_id],
            observations=observations,
            unconfirmed=[missing],
        ),
        CauseCandidate(
            cause="온도 실측 및 관련 운전 조건",
            inspection_priority="후속 확인",
            priority_reason="우선 점검 결과와 독립 계측을 함께 비교해 다른 가능성을 확인한다.",
            basis="시연용 가이드에서 온도 실측과 운전 조건 대조를 안내한다.",
            evidence_ids=[source.evidence_id],
            observations=[],
            unconfirmed=[
                "독립 계측 결과와 주변 온도·운전 조건은 별도 확인이 필요하다."
            ],
        ),
    ]
    checks = [
        "접근·접촉 위험을 통제하고, 발열·팽창·누액·연기 등이 있으면 해당 비상 절차를 확인한다.",
        "독립 계측기로 외함 온도를 측정하고 센서의 지정 부착 위치·열접촉 상태와 대조한다.",
        focus_check,
        "필요한 경우 에너지 차단과 잔류 위험 확인 후 부하·벨트·가이드 접촉 상태를 점검한다.",
    ]
    actions = [
        focus_action,
        "조치 후 충분한 관찰 시간을 두고 온도 추이와 동일 알람 재발 여부를 확인한다.",
    ]
    approvals = [
        "재가동·보호 해제 전 사업장 승인 절차와 제조사 해제 조건을 확인하고 필요한 승인을 받는다."
    ]
    return AnalysisResult(
        incident_id=incident.incident_id,
        status="OK",
        observed_facts=observations[0],
        suspected_causes=candidates,
        recommended_checks=checks,
        check_citations=[
            CheckCitation(check_index=i, evidence_ids=[source.evidence_id])
            for i in range(len(checks))
        ],
        recommended_actions=actions,
        action_citations=[
            ActionCitation(action_index=i, evidence_ids=[source.evidence_id])
            for i in range(len(actions))
        ],
        actions_requiring_approval=approvals,
        approval_citations=[
            ActionCitation(action_index=0, evidence_ids=[source.evidence_id])
        ],
        additional_checks=[
            "주변 온도·하중 조건·독립 계측 결과와 제조사 허용 외함 온도"
        ],
        evidence=[source],
        model="sample/sensor-fixture",
        prompt_version="sensor-fixture-guidance-v3",
        generated_at=incident.confirmed_at + timedelta(seconds=1),
        limitations="LLM을 호출하지 않은 시연용 분석 예시이며 실제 현장 원인 확정을 의미하지 않는다.",
    )


def seed_cases(
    incidents,
    reports,
    users,
    telemetry,
    jobs,
    author,
    reviewer,
    approver,
    *,
    cases=None,
    analysis_builder=None,
):
    """5건만 추가한다. 기존 건은 검증 후 건너뛰며 미완성 건은 덮어쓰지 않는다."""
    from weeing_weeing.contracts import Role

    if len({author, reviewer, approver}) != 3:
        raise ValueError("작성·검토·승인 계정은 서로 달라야 합니다.")
    for employee, role in (
        (author, Role.INSPECTOR),
        (reviewer, Role.MAINT_LEAD),
        (approver, Role.CONTROL),
    ):
        user = users.get_user(employee)
        if not user or not user.is_active or user.role != role:
            raise ValueError("활성 시연 계정의 역할을 확인하세요.")
    results = []
    for case in build_cases() if cases is None else cases:
        snapshot = case["incident"]
        make_analysis = analysis_builder or build_analysis
        existing = incidents.get_incident(snapshot.incident_id)
        if existing:
            approved = reports.incident_approved_reports(author, snapshot.incident_id)
            if len(approved) != 1:
                raise ValueError(
                    "기존 시험 사례가 미완성이거나 다른 자료입니다. 상태를 확인하세요."
                )
            document = reports.get_report(author, approved[0].report_id)
            observations = telemetry.observations_between(
                snapshot.asset_id,
                case["samples"][0].timestamp,
                case["samples"][-1].timestamp + timedelta(seconds=1),
                process_id=snapshot.process_id,
            )
            if (
                document.data_origin != "SYNTHETIC"
                or without_fixture_labels(document.form_data.model_dump())
                != case["form"].model_dump()
                or document.ai_analysis is None
                or document.ai_analysis.model != "sample/sensor-fixture"
                or jobs.analysis_input(document.ai_analysis) is None
                or without_fixture_labels(
                    jobs.analysis_input(document.ai_analysis).model_dump()
                )
                != snapshot.model_dump()
                or [record for record, _ in observations] != case["samples"]
                or any(origin != ORIGIN for _, origin in observations)
            ):
                raise ValueError(
                    "기존 시험 사례의 내용·센서가 다릅니다. 덮어쓰지 않습니다."
                )
            if document.ai_analysis != make_analysis(case):
                raise ValueError("기존 시험 분석이 다릅니다. 덮어쓰지 않습니다.")
            results.append((snapshot.codes[0], approved[0].report_id, "기존"))
            continue
        # 기존 센서와 충돌하면 전체 사례 쓰기 전에 중단한다. 시연값으로 실측을 덮지 않는다.
        for sample in case["samples"]:
            if telemetry.between(
                sample.asset_id,
                sample.timestamp,
                sample.timestamp + timedelta(microseconds=1),
                process_id=sample.process_id,
            ):
                raise ValueError(
                    "시험 시각에 기존 센서 표본이 있습니다. 별도 시연 DB를 사용하세요."
                )
        telemetry.save_many(case["samples"], provenance=ORIGIN)
        incidents.save_incident(
            snapshot.model_copy(
                update={
                    "status": IncidentStatus.RECOVERED,
                    "recovered_at": snapshot.confirmed_at + timedelta(minutes=30),
                }
            )
        )
        analysis = make_analysis(case)
        jobs.save_analysis_with_input(analysis, snapshot)
        doc = reports.create_draft(
            author,
            ReportDraft(
                incident_id=snapshot.incident_id,
                data_origin="SYNTHETIC",
                form_data=case["form"],
            ),
        )
        for actor, operation in (
            (author, "submit"),
            (reviewer, "review"),
            (approver, "approve"),
        ):
            doc = reports.transition(
                actor, doc.report_id, operation, expected_revision=doc.revision
            )
        results.append((snapshot.codes[0], doc.report_id, "생성"))
    return results


def validate_target(settings, aws, *, index=False):
    """등록에는 DB만 검사한다. 검색 저장소는 --index일 때만 필요하다."""
    database = urlsplit(settings.database_url)
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    postgres = database.scheme in {"postgresql", "postgresql+psycopg", "postgres"}
    local_sqlite = (
        database.scheme == "sqlite"
        and not database.netloc
        and bool(database.path.strip("/"))
    )
    if aws:
        if not postgres or database.hostname != "postgres":
            raise ValueError("--aws는 서버 Docker 내부의 postgres DB에서만 사용합니다.")
    elif not (local_sqlite or postgres and database.hostname in local_hosts):
        raise ValueError(
            "로컬 등록은 SQLite 파일 또는 localhost/127.0.0.1의 PostgreSQL이 필요합니다. "
            "현재 DATABASE_URL이 로컬 DB를 가리키는지 사용자 터미널에서 확인하세요. "
            "--aws는 로컬 실행 오류를 우회하는 옵션이 아닙니다."
        )
    if not index:
        return
    qdrant_host = urlsplit(settings.qdrant_url).hostname
    if aws:
        if settings.vector_store != "qdrant" or qdrant_host != "qdrant":
            raise ValueError("서버 색인에는 Docker 내부의 qdrant가 필요합니다.")
    elif (
        settings.vector_store == "qdrant"
        and settings.qdrant_url
        and qdrant_host not in local_hosts
    ):
        raise ValueError(
            "로컬 색인은 로컬 Qdrant만 허용합니다. 등록만 하려면 --index를 빼세요."
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, help="DB에 접속하지 않고 JSON 파일로 미리보기"
    )
    parser.add_argument(
        "--apply", action="store_true", help="시연 DB에 사건·센서·보고서를 추가"
    )
    parser.add_argument("--aws", action="store_true")
    parser.add_argument(
        "--index",
        action="store_true",
        help="검색 색인 실행. 외부 임베딩 비용이 발생할 수 있음",
    )
    for role in ("author", "reviewer", "approver"):
        parser.add_argument(f"--{role}")
    args = parser.parse_args()
    if not args.apply:
        if args.index or args.aws:
            parser.error("--index/--aws는 --apply와 함께 사용하세요.")
        payload = json.dumps(
            [{**case, "analysis": build_analysis(case)} for case in build_cases()],
            ensure_ascii=False,
            indent=2,
            default=lambda v: v.model_dump(mode="json"),
        )
        if args.output:
            args.output.write_text(payload + "\n", encoding="utf-8")
            print(f"가상 사례 5건 미리보기: {args.output}")
        else:
            print(payload)
        return
    if not all((args.author, args.reviewer, args.approver)) or args.output:
        parser.error(
            "--apply에는 작성·검토·승인 계정이 필요하며 --output은 함께 사용할 수 없습니다."
        )
    from weeing_weeing.config import get_settings
    from weeing_weeing.rag import interface as rag

    settings = get_settings()
    validate_target(settings, args.aws, index=args.index)
    repos = [
        opener(settings.database_url)
        for opener in (
            db.open_incidents,
            db.open_reports,
            db.open_users,
            db.open_telemetry,
            db.open_analysis_jobs,
        )
    ]
    try:
        results = seed_cases(*repos, args.author, args.reviewer, args.approver)
        print(
            f"보고서 {len(results)}건: 신규 {sum(row[2] == '생성' for row in results)}건, 기존 {sum(row[2] == '기존' for row in results)}건"
        )
        if args.index:
            indexed, failed = index_cases(repos[1], results, rag.get_indexer)
            print(f"검색 등록 {indexed}건, 실패 {failed}건")
            if failed:
                raise SystemExit(1)
    finally:
        rag.close_rag_resources()
        for repo in repos:
            repo._engine.dispose()


if __name__ == "__main__":
    main()
