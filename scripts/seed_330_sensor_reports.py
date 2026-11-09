"""22개 코드의 가상 사건·센서 한 표본·분석·승인 정비보고서 330건 생성."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from seed_5_sensor_reports import ORIGIN, seed_cases, validate_target
from seed_22_reports import index_cases
from seed_330_reports import build_entries

from weeing_weeing.contracts import (
    AnalysisResult,
    Incident,
    ReportFormData,
)
from weeing_weeing.contracts.analysis import (
    ActionCitation,
    CauseCandidate,
    CheckCitation,
    Evidence,
)
from weeing_weeing.contracts.incident import SensorEvidence
from weeing_weeing.contracts.telemetry import TelemetryRecord
from weeing_weeing.db import interface as db

# 기존 330건에서 사용한 에러 범위. M01/M04/M09/M19와 D 코드는 이 데이터 세트에서 제외한다.
EXPECTED_CODES = frozenset(
    [f"P{i:02d}" for i in range(1, 8)]
    + ["M02", "M03", "M05", "M06", "M07", "M08"]
    + [f"M{i:02d}" for i in range(10, 19)]
)


def build_cases():
    """기존 사례를 독립된 시연 사건과 단일 표본으로 만든다."""
    entries = build_entries()
    if len(entries) != 330 or {case[0] for case, _ in entries} != EXPECTED_CODES:
        raise ValueError("기대하는 22개 코드의 330건이 아닙니다.")
    cases = []
    for index, (case, sequence) in enumerate(entries):
        code, field, value, unit, threshold, cause, action, trial = case
        code = f"BTT2-{code}"
        incident_id = f"INC-SENSOR-BATCH-V1-{code}-{sequence:03d}"
        anchor = datetime(2024, 1, 1, 3, 12, 34, tzinfo=UTC) + timedelta(days=index)
        values = dict(
            infeed_present=False,
            outfeed_present=False,
            rpm=1015.0,
            dc_input_current_a=0.0918,
            dc_bus_voltage_v=24.0,
            motor_housing_temp_c=70.0,
            de_vibration_rms_g=0.06,
            de_kurtosis=4.8,
            nde_vibration_rms_g=0.055,
            nde_kurtosis=4.5,
        )
        # 이송시간과 창 통계는 센서 단일 행의 컬럼이 아니다. 가상 사건 근거에만 보존한다.
        if field in values:
            values[field] = value
        sample = TelemetryRecord(
            record_id=f"{incident_id}:0",
            timestamp=anchor,
            process_id="BAT-TRANSFER-01",
            asset_id="BLDC-001",
            schema_version="3.0.0",
            **values,
        )
        incident = Incident(
            incident_id=incident_id,
            process_id=sample.process_id,
            asset_id=sample.asset_id,
            codes=[code],
            severity="Error",
            first_detected_at=anchor,
            confirmed_at=anchor,
            last_detected_at=anchor,
            telemetry_provenance=ORIGIN,
            evidence=[
                SensorEvidence(
                    field=field,
                    value=value,
                    unit=unit,
                    threshold=threshold,
                    note="시연용 사건 판정 정보이며 단일 표본으로 시간 조건을 재현하지 않는다.",
                )
            ],
        )
        summary = (
            f"{code} 사건의 확정 시점 표본: 회전속도 {sample.rpm}rpm, "
            f"DC 입력전류 {sample.dc_input_current_a}A, 전압 {sample.dc_bus_voltage_v}V, "
            f"외함 온도 {sample.motor_housing_temp_c}℃, 구동측 진동 {sample.de_vibration_rms_g}g. "
            "단일 표본은 변화 추이나 지속 조건을 증명하지 않는다."
        )
        form = ReportFormData(
            actual_actions=action,
            action_at=anchor + timedelta(minutes=10),
            confirmed_cause=cause,
            cause_evidence=summary,
            trial_result="정상",
            trial_details=trial,
            resolution="해결",
            ai_assessment="부분 일치",
        )
        cases.append(
            {
                "incident": incident,
                "samples": [sample],
                "form": form,
                "summary": summary,
                "variant": (sequence - 1) // 3,
            }
        )
    return cases


# 서로 다른 가상 시연의 조사 방향. 과거 확인 원인 문장을 분석에 그대로 옮기지 않는다.
CHECKS = {
    "P": [
        ("트레이 위치·이송 상태", "트레이의 실제 위치와 정체·이송 상태를 확인한다."),
        (
            "광전센서 감지 상태",
            "입구·출구 센서의 감지 상태와 실제 트레이 위치를 대조한다.",
        ),
        (
            "벨트·가이드 간섭",
            "에너지를 차단한 뒤 벨트와 가이드의 간섭 여부를 확인한다.",
        ),
        ("운전 속도·설정 조건", "운전 속도와 승인된 이송 조건을 확인한다."),
        ("전후 공정의 흐름", "상위 투입과 후속 공정 수신 상태를 확인한다."),
    ],
    "M": [
        ("센서값·측정 위치", "독립 계측값과 센서 위치·부착 상태를 대조한다."),
        ("전원·연결 상태", "안전 절차에 따라 전원 조건과 연결 상태를 확인한다."),
        ("운전 부하·구동 조건", "운전 부하와 속도·설정 조건을 확인한다."),
        ("벨트·회전부 간섭", "에너지를 차단하고 벨트·회전부의 접촉과 정렬을 점검한다."),
        ("주변 환경·통풍", "설비 주변 환경과 통풍 상태를 확인한다."),
    ],
}


def build_analysis(case):
    """검증되지 않은 AI 결과가 아닌, 시연용 정적 권고와 출처를 만든다."""
    incident = case["incident"]
    category = "P" if incident.codes[0].startswith("BTT2-P") else "M"
    name, check = CHECKS[category][case["variant"]]
    source = Evidence(
        evidence_id=f"sensor-batch-guide-{category.lower()}",
        doc_id=f"SENSOR-BATCH-GUIDE-{category}",
        doc_version="1",
        title="정비이력 시연용 점검 가이드",
        text="시연용으로 작성한 점검 예시다. "
        + " ".join(item[1] for item in CHECKS[category])
        + " 접근 위험을 통제하고 정비 전 안전 절차와 필요한 승인을 확인한다.",
        citation="정비이력 생성용 시연 가이드 v1",
    )
    candidate = CauseCandidate(
        cause=name,
        inspection_priority="우선 확인",
        priority_reason="사건 코드에 대한 점검 시연에서 먼저 확인할 항목으로 설정했다.",
        basis="시연용 점검 가이드의 해당 항목을 참고한 점검 후보이다.",
        evidence_ids=[source.evidence_id],
        observations=[case["summary"]],
        unconfirmed=["현장 점검 전이며 실제 원인은 확인되지 않았다."],
    )
    checks = [
        "접근·접촉 위험을 통제하고 필요한 안전 절차를 확인한다.",
        check,
        "점검 결과와 설비의 공식 매뉴얼·승인 요건을 대조한다.",
    ]
    actions = [
        "점검 결과에 따라 사업장 절차와 담당자 승인 범위를 확인하고 후속 조치를 결정한다."
    ]
    return AnalysisResult(
        incident_id=incident.incident_id,
        status="OK",
        observed_facts=case["summary"],
        suspected_causes=[candidate],
        recommended_checks=checks,
        check_citations=[
            CheckCitation(check_index=i, evidence_ids=[source.evidence_id])
            for i in range(len(checks))
        ],
        recommended_actions=actions,
        action_citations=[
            ActionCitation(action_index=0, evidence_ids=[source.evidence_id])
        ],
        actions_requiring_approval=[
            "재가동·보호 해제 전 필요한 승인과 제조사 조건을 확인한다."
        ],
        approval_citations=[
            ActionCitation(action_index=0, evidence_ids=[source.evidence_id])
        ],
        evidence=[source],
        model="sample/sensor-fixture",
        prompt_version="sensor-batch-guidance-v1",
        generated_at=incident.confirmed_at + timedelta(seconds=1),
        limitations="LLM을 호출하지 않은 시연용 분석 예시이며 실제 현장 원인을 확정하지 않는다.",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="DB 접속 없이 JSON 미리보기")
    parser.add_argument("--apply", action="store_true", help="시연 DB에 330건 추가")
    parser.add_argument("--aws", action="store_true", help="서버 Docker 내부 DB")
    parser.add_argument(
        "--index", action="store_true", help="검색 색인(외부 임베딩 비용 가능)"
    )
    for role in ("author", "reviewer", "approver"):
        parser.add_argument(f"--{role}")
    args = parser.parse_args()
    cases = build_cases()
    if not args.apply:
        if args.aws or args.index:
            parser.error("--aws와 --index는 --apply가 필요합니다.")
        payload = json.dumps(
            [{**case, "analysis": build_analysis(case)} for case in cases],
            ensure_ascii=False,
            indent=2,
            default=lambda v: v.model_dump(mode="json"),
        )
        if args.output:
            args.output.write_text(payload + "\n", encoding="utf-8")
            print(f"330건 미리보기: {args.output}")
        else:
            print(payload)
        return
    if not all((args.author, args.reviewer, args.approver)) or args.output:
        parser.error(
            "--apply에는 세 시연 계정이 필요하며 --output과 함께 쓸 수 없습니다."
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
        results = seed_cases(
            *repos,
            args.author,
            args.reviewer,
            args.approver,
            cases=cases,
            analysis_builder=build_analysis,
        )
        print(
            f"보고서 {len(results)}건: 신규 {sum(r[2] == '생성' for r in results)}건, 기존 {sum(r[2] == '기존' for r in results)}건"
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
