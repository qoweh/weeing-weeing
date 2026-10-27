"""매뉴얼 v2.0에 맞춰 #30의 가상 정비 이력 24건을 재생성한다.

실제 센서 로그나 실측 보고서가 아니다. 데이터 파일을 고친 뒤에는 이 스크립트의
사례 정의도 함께 고쳐 동일한 결과가 생성되도록 유지한다.
"""

from datetime import datetime, timedelta, timezone

from weeing_weeing.config import PROJECT_ROOT
from weeing_weeing.contracts import AnalysisResult, Incident, MaintenanceReport
from weeing_weeing.contracts.analysis import CauseCandidate, Evidence
from weeing_weeing.contracts.incident import SensorEvidence
from weeing_weeing.contracts.report import (
    ActionTaken,
    ApprovalStep,
    MaintenanceRecord,
    TrialRun,
)

OUTPUT = PROJECT_ROOT / "data/history/synthetic_reports_v1.jsonl"
KST = timezone(timedelta(hours=9))

# 코드마다 확인된 원인이 다른 3건. 값은 룰 임계값을 설명하기 위한 가상 수치다.
# (원인 분류, 확인 원인, 실제 조치, 관측값, 사람의 AI 평가)
CASES = {
    "BTT2-P01": (
        (
            "기계 간섭",
            "트레이 측면이 입구 가이드에 걸려 이동이 지연됨",
            "에너지 차단 후 가이드 간섭을 제거하고 위치를 조정함",
            18.4,
            "일치",
        ),
        (
            "동력 전달",
            "벨트 장력이 느슨해 트레이가 미끄러짐",
            "벨트와 풀리 상태를 확인하고 장력을 조정함",
            17.8,
            "부분 일치",
        ),
        (
            "후속 공정",
            "후속 수신 대기로 트레이가 출구에서 정체됨",
            "후속 공정의 수신 조건을 확인하고 대기를 해소함",
            19.2,
            "불일치",
        ),
    ),
    "BTT2-P03": (
        (
            "트레이 간섭",
            "트레이가 입구 가이드에 비스듬히 걸려 센서 앞에 남음",
            "에너지 차단 후 트레이를 제거하고 가이드 정렬을 확인함",
            6.2,
            "일치",
        ),
        (
            "센서 오염",
            "물체가 없는데 광전센서 렌즈 오염으로 출력이 유지됨",
            "센서 감지면을 세척하고 물체 유무에 따른 출력을 시험함",
            6.8,
            "부분 일치",
        ),
        (
            "투입 간격",
            "연속 밀착 투입으로 입구 센서가 정상 해제되지 않음",
            "투입 간격을 복원하고 단일 트레이 통과를 확인함",
            5.7,
            "불일치",
        ),
    ),
    "BTT2-P06": (
        (
            "출구 센서",
            "트레이는 배출됐으나 출구 광전센서의 광축 이탈로 에지가 누락됨",
            "센서 장착과 광축을 조정하고 출구 에지를 대조함",
            17.4,
            "불일치",
        ),
        (
            "트레이 간섭",
            "트레이가 연결부 가이드에 걸려 출구에 도달하지 못함",
            "에너지 차단 후 연결부 간섭을 제거하고 가이드를 조정함",
            18.1,
            "일치",
        ),
        (
            "추적 누락",
            "실제 출구 통과는 있었으나 입력 에지 수집 순번이 누락됨",
            "원천 에지와 수집 순번을 대조하고 추적 큐를 재동기화함",
            17.9,
            "부분 일치",
        ),
    ),
    "BTT2-M01": (
        (
            "전원 접속",
            "기동 요구 중 드라이버 입력 단자 접촉 불량이 확인됨",
            "전원 차단 후 입력 단자를 재체결하고 기동을 시험함",
            0.0,
            "일치",
        ),
        (
            "기계 구속",
            "트레이 간섭으로 구동축이 회전하지 못함",
            "에너지 차단 후 걸림을 제거하고 무부하 기동을 시험함",
            76.0,
            "부분 일치",
        ),
        (
            "운전 문맥",
            "정상 정지 요구가 남아 있어 RUN 후에도 속도 지령이 전달되지 않음",
            "정지 요구와 기동 순서를 확인하고 승인된 조건에서 재시험함",
            0.0,
            "불일치",
        ),
    ),
    "BTT2-M02": (
        (
            "벨트 마찰",
            "같은 적재 조건에서 벨트 접촉부 마찰 증가가 확인됨",
            "에너지 차단 후 접촉부를 정렬하고 정상 적재로 속도를 재측정함",
            986.0,
            "일치",
        ),
        (
            "장력 설정",
            "벨트 장력이 과도해 목표 속도 도달이 지연됨",
            "벨트 장력을 조정한 뒤 무부하와 적재 조건을 비교함",
            982.0,
            "부분 일치",
        ),
        (
            "목표 속도",
            "운전 레시피 목표 속도가 낮게 설정된 것이 확인됨",
            "승인된 레시피 설정을 복원하고 독립 속도계를 대조함",
            988.0,
            "불일치",
        ),
    ),
    "BTT2-M12": (
        (
            "체결",
            "구동측 센서 고정 볼트의 풀림이 현장 점검에서 확인됨",
            "에너지 차단 후 센서 장착을 재체결하고 같은 조건에서 재측정함",
            0.094,
            "불일치",
        ),
        (
            "정렬",
            "구동측 풀리 정렬 불량과 벨트 접촉이 현장 점검에서 확인됨",
            "풀리 정렬을 조정하고 같은 속도와 하중에서 진동을 재측정함",
            0.097,
            "부분 일치",
        ),
        (
            "기계 간섭",
            "구동측 가드와 회전부의 간헐적 접촉 흔적이 확인됨",
            "에너지 차단 후 접촉부 간격을 조정하고 재측정함",
            0.091,
            "일치",
        ),
    ),
    "BTT2-M14": (
        (
            "트레이 충격",
            "트레이 투입 시각과 구동측 충격 피크가 일치함",
            "투입 간격을 조정하고 같은 계산 창에서 첨도를 재확인함",
            8.1,
            "부분 일치",
        ),
        (
            "센서 장착",
            "구동측 센서 고정 불량으로 비정상 피크가 생김",
            "센서를 재부착하고 원시 파형과 첨도를 함께 확인함",
            8.4,
            "불일치",
        ),
        (
            "국부 접촉",
            "구동측 가이드에 반복 접촉 흔적이 확인됨",
            "에너지 차단 후 접촉부를 조정하고 반복 충격이 사라졌는지 확인함",
            8.0,
            "일치",
        ),
    ),
    "BTT2-M16": (
        (
            "장착",
            "반구동측 센서 체결 풀림이 현장 점검에서 확인됨",
            "센서를 재체결하고 같은 하중에서 RMS를 재측정함",
            0.071,
            "불일치",
        ),
        (
            "벨트 정렬",
            "반구동측 풀리와 벨트의 편심 접촉이 확인됨",
            "에너지 차단 후 풀리 정렬을 조정하고 진동을 재측정함",
            0.073,
            "부분 일치",
        ),
        (
            "가드 간섭",
            "반구동측 가드와 구동부의 접촉 흔적이 확인됨",
            "에너지 차단 후 가드 간격을 조정하고 진동을 재측정함",
            0.070,
            "일치",
        ),
    ),
}

SENSORS = {
    "BTT2-P01": ("outfeed_present", False, None, "이송시간 >16초, 출구 미도착"),
    "BTT2-P03": ("infeed_present", True, None, "입구 true >5초"),
    "BTT2-P06": ("outfeed_present", False, None, "재공·RUN 중 출구 무에지 >16초"),
    "BTT2-M01": ("rpm", None, "rpm", "RUN 후 3초 미도달 또는 운전 중 <=100 rpm"),
    "BTT2-M02": ("rpm", None, "rpm", "3초 지속, B=990 rpm 이하"),
    "BTT2-M12": ("de_vibration_rms_g", None, "g", "3초 지속, C=0.088661 g 이상"),
    "BTT2-M14": ("de_kurtosis", None, None, "3초 지속, C=7.7727 이상"),
    "BTT2-M16": ("nde_vibration_rms_g", None, "g", "3초 지속, C=0.068554 g 이상"),
}

MANUAL_SECTIONS = {
    "BTT2-P01": (
        "03 이송·광전 현장 대응 절차",
        "실제 재공과 출구 센서, 후속 공정 수신을 대조한다.",
    ),
    "BTT2-P03": (
        "03 이송·광전 현장 대응 절차",
        "센서 앞 물체 유무와 실제 출력 상태를 먼저 대조한다.",
    ),
    "BTT2-P06": (
        "03 이송·광전 현장 대응 절차",
        "트레이 위치와 출구 센서 표시 및 입력 에지를 대조한다.",
    ),
    "BTT2-M01": (
        "04 기동·속도·DC 입력전류 대응",
        "정지 요구, 전원, 드라이버 알람, 동력 연결, 기계 구속 순서로 확인한다.",
    ),
    "BTT2-M02": (
        "04 기동·속도·DC 입력전류 대응",
        "목표 속도와 부하, 실제 회전을 비교하고 전달부를 점검한다.",
    ),
    "BTT2-M12": (
        "06 진동·충격·특정 측 변화 대응",
        "센서 장착, 정렬, 접촉 여부를 조사하고 필요하면 원시 파형을 분석한다.",
    ),
    "BTT2-M14": (
        "06 진동·충격·특정 측 변화 대응",
        "투입시각과 충격을 대조하고 파형 포화와 특징 계산 창을 확인한다.",
    ),
    "BTT2-M16": (
        "06 진동·충격·특정 측 변화 대응",
        "센서 장착, 정렬, 접촉 여부를 조사하고 필요하면 원시 파형을 분석한다.",
    ),
}


def make_reports() -> list[MaintenanceReport]:
    reports = []
    for code_index, (code, cases) in enumerate(CASES.items(), start=1):
        field, bool_value, unit, threshold = SENSORS[code]
        section, guidance = MANUAL_SECTIONS[code]
        for case_index, (category, cause, action, value, assessment) in enumerate(
            cases, start=1
        ):
            number = (code_index - 1) * 3 + case_index
            start = datetime(2026, 9, number, 9, tzinfo=KST)
            incident_id = f"INC-SYN-202609{number:02d}"
            report_id = f"RPT-SYN-202609{number:02d}"
            incident = Incident(
                incident_id=incident_id,
                process_id="BAT-TRANSFER-01",
                asset_id="BLDC-001",
                codes=[code],
                severity="Error",
                status="CLOSED",
                first_detected_at=start,
                confirmed_at=start + timedelta(seconds=20),
                last_detected_at=start + timedelta(minutes=2),
                recovered_at=start + timedelta(minutes=12),
                evidence=[
                    SensorEvidence(
                        field=field,
                        value=bool_value if bool_value is not None else value,
                        unit=unit,
                        threshold=threshold,
                        observed=(
                            f"가상 관측: {value}초 동안 조건 지속"
                            if code.startswith("BTT2-P")
                            else "가상 관측: 같은 운전 조건에서 임계 지속시간 충족"
                        ),
                        note="합성 사례이며 실측·원시 파형 자료가 아님",
                    )
                ],
                profile="DEMO",
                config_version="SYNTHETIC-HISTORY-v1",
                plc_context={"run_cmd": True, "data_origin": "SYNTHETIC"},
                reason="가상 정비 이력. 실제 설비 사고나 AI 분석 결과가 아님.",
            )
            inspector = "SYN-I-001"
            evidence_id = f"SYN-MANUAL-{code}-{case_index}"
            ai_guess = (
                cause
                if assessment == "일치"
                else category
                if assessment == "부분 일치"
                else cases[0][1]
            )
            analysis = AnalysisResult(
                incident_id=incident_id,
                status="OK",
                observed_facts=f"가상 관측: {code}, {field}={bool_value if bool_value is not None else value}",
                suspected_causes=[
                    CauseCandidate(
                        cause=ai_guess,
                        likelihood="중",
                        basis=f"{code} 관측과 매뉴얼의 점검 항목",
                        evidence_ids=[evidence_id],
                    )
                ],
                recommended_checks=[guidance],
                evidence=[
                    Evidence(
                        evidence_id=evidence_id,
                        doc_id="BTT-MANUAL",
                        doc_version="2.0",
                        section=section,
                        text=guidance,
                        citation=f"BTT-MANUAL v2.0 {section}",
                    )
                ],
                limitations="가상 예시. 실제 모델 실행·센서 실측·진단 결과가 아님.",
                model="synthetic/example",
                generated_at=start + timedelta(minutes=3),
            )
            reports.append(
                MaintenanceReport(
                    report_id=report_id,
                    incident_id=incident_id,
                    process_id=incident.process_id,
                    asset_id=incident.asset_id,
                    report_status="APPROVED",
                    report_version=1,
                    data_origin="SYNTHETIC",
                    incident=incident,
                    ai_analysis=analysis,
                    maintenance=MaintenanceRecord(
                        cause_category=category,
                        confirmed_cause=cause,
                        ai_assessment=assessment,
                        actions_taken=[
                            ActionTaken(
                                at=start + timedelta(minutes=8),
                                action=action,
                                by=inspector,
                            )
                        ],
                        test_run=TrialRun(
                            result="정상",
                            checked_window="가상 시험: 원인 제거 후 센서·구동 상태 및 트레이 통과 확인",
                        ),
                        remarks="합성 사례. 실제 센서 원본·작업 기록·승인 서명이 아닌 RAG 테스트 자료.",
                    ),
                    approval=[
                        ApprovalStep(
                            step=1,
                            role="현장 점검자",
                            user=inspector,
                            decision="제출",
                            at=start + timedelta(minutes=20),
                        ),
                        ApprovalStep(
                            step=2,
                            role="보전 팀장",
                            user="SYN-L-001",
                            decision="승인",
                            at=start + timedelta(minutes=25),
                        ),
                        ApprovalStep(
                            step=3,
                            role="관제 담당자",
                            user="SYN-C-001",
                            decision="승인",
                            at=start + timedelta(minutes=30),
                        ),
                    ],
                )
            )
    return reports


def main() -> None:
    reports = make_reports()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        "\n".join(report.model_dump_json() for report in reports) + "\n",
        encoding="utf-8",
    )
    print(f"{OUTPUT.relative_to(PROJECT_ROOT)}: {len(reports)} synthetic reports")


if __name__ == "__main__":
    main()
