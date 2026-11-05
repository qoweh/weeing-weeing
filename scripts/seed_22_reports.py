"""매뉴얼 기반 시연 사례 22건을 로컬 DB에 등록한다. 실제 정비 기록은 아니다."""

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
from weeing_weeing.rag import interface as rag

# 코드, 센서 필드, 값, 단위, 판정 근거, 확인 원인, 수행 조치, 시험 결과
CASES = [
    (
        "P01",
        "outfeed_present",
        False,
        None,
        "트레이 이송 16초 초과 및 출구 미도착",
        "입구 가이드 간섭으로 트레이 이동이 지연됐다.",
        "에너지 차단 후 걸린 트레이를 제거하고 가이드 간섭을 조정했다.",
        "시험 트레이 5개의 입출구 대응과 이송시간을 확인했다.",
    ),
    (
        "P02",
        "transfer_time_s",
        13.5,
        "s",
        "유효 이송시간 14초 미만이 5회 중 3회",
        "운전 레시피의 속도 설정이 승인값보다 높았다.",
        "승인된 속도 설정을 복원하고 실제 회전을 독립 계측과 비교했다.",
        "5회 연속 입출구 대응과 정상 이송시간을 확인했다.",
    ),
    (
        "P03",
        "infeed_present",
        True,
        None,
        "입구 센서 점유 5초 초과",
        "입구 가이드에 트레이가 걸려 센서 앞 점유가 지속됐다.",
        "에너지를 차단하고 트레이 걸림을 제거한 후 가이드 간섭을 확인했다.",
        "센서 해제 상태 2초 이상과 시험 이송 시 정상 감지·해제를 확인했다.",
    ),
    (
        "P04",
        "outfeed_present",
        True,
        None,
        "출구 센서 점유 5초 초과",
        "후속 공정 수신 대기로 출구 트레이가 정체됐다.",
        "후속 공정 담당자와 수신 조건을 확인하고 정체된 트레이를 정리했다.",
        "후속 설비 수신과 출구 센서 해제 상태가 2초 이상 유지됨을 확인했다.",
    ),
    (
        "P05",
        "infeed_present",
        False,
        None,
        "연속 투입 기대 중 입구 에지 10초 초과 없음",
        "상위 공급 장치의 대기로 투입 간격이 길어졌다.",
        "상위 설비의 공급 상태를 점검하고 정상 투입 조건을 복원했다.",
        "입구 투입 간격이 5회 연속 정상 범위인지 확인했다.",
    ),
    (
        "P06",
        "outfeed_present",
        False,
        None,
        "재공·운전·수신 가능 상태에서 출구 에지 16초 초과 없음",
        "출구 센서 감지면 오염으로 트레이 통과 에지가 누락됐다.",
        "트레이 실제 배출과 센서 표시·입력을 대조하고 감지면을 청소했다.",
        "재공 추적을 재동기화하고 시험 트레이 5개의 출구 감지를 확인했다.",
    ),
    (
        "P07",
        "transfer_time_range_s",
        2.5,
        "s",
        "유효 이송시간 변동이 두 비중첩 창에서 반복",
        "벨트 장력 불균일로 트레이별 이송시간 편차가 커졌다.",
        "에너지 차단 후 벨트와 풀리를 점검하고 장력을 조정했다.",
        "같은 적재·레시피 조건의 두 비중첩 시험 창에서 이송시간을 확인했다.",
    ),
    (
        "M02",
        "rpm",
        985,
        "rpm",
        "운전 중 990 rpm 이하 3초 지속",
        "벨트 접촉부의 간섭으로 동일 적재 조건에서 회전 속도가 저하됐다.",
        "에너지 차단 후 접촉부를 정렬하고 벨트 상태를 점검했다.",
        "동일 적재 조건에서 실제 회전과 목표 속도가 일치함을 확인했다.",
    ),
    (
        "M03",
        "rpm",
        1045,
        "rpm",
        "운전 중 1040 rpm 이상 3초 지속",
        "승인된 값보다 높은 목표 속도 설정이 적용돼 있었다.",
        "독립 속도계로 실제 회전을 대조하고 승인된 레시피 값을 복원했다.",
        "운전 속도가 정상 범위에 유지되는 것을 확인했다.",
    ),
    (
        "M05",
        "dc_input_current_a",
        0.078,
        "A",
        "DC 입력전류 0.080967 A 이하 3초 지속",
        "전류 측정 신호의 스케일 설정이 실제 센서와 달랐다.",
        "센서 배선과 영점을 확인하고 승인된 측정 스케일을 복원했다.",
        "같은 운전 조건에서 전류 측정값이 정상 범위에 들어오는지 확인했다.",
    ),
    (
        "M06",
        "dc_input_current_a",
        0.11,
        "A",
        "DC 입력전류 0.103165 A 이상 3초 지속",
        "벨트 전달부 간섭으로 동일 적재 조건의 저항이 증가했다.",
        "에너지 차단 후 전달부 간섭을 제거하고 벨트 장력을 확인했다.",
        "같은 속도·적재 조건에서 전류와 드라이버 알람을 확인했다.",
    ),
    (
        "M07",
        "dc_bus_voltage_v",
        17.5,
        "V",
        "DC 버스전압 18 V 이하 1초 지속",
        "드라이버 입력 단자의 접속이 느슨해 전압이 저하됐다.",
        "전기 담당자가 전원을 차단하고 단자 접속을 정비한 뒤 전원 출력과 입력을 비교했다.",
        "드라이버 입력 전압이 정상 범위로 복귀해 10초 이상 유지되는 것을 확인했다.",
    ),
    (
        "M08",
        "dc_bus_voltage_v",
        28,
        "V",
        "DC 버스전압 27 V 이상 1초 지속",
        "전원 출력 설정값이 승인된 운전 범위를 벗어났다.",
        "전기 담당자가 전원 설정과 측정 위치를 확인하고 승인된 출력값으로 복원했다.",
        "입력 전압이 정상 범위에서 10초 이상 유지되고 보호 알람 조건을 확인했다.",
    ),
    (
        "M10",
        "motor_housing_temp_c",
        95,
        "℃",
        "모터 외함 온도 90℃ 이상 10초 지속",
        "모터 방열구에 분진이 쌓여 열이 원활하게 배출되지 않았다.",
        "접근 위험을 통제한 뒤 온도와 센서 위치를 확인하고 방열구 분진을 청소했다.",
        "외함 온도가 정상 범위에서 10초 이상 유지되고 고온 알람이 재발하지 않았다.",
    ),
    (
        "M11",
        "de_vibration_rms_g",
        0.03,
        "g",
        "구동측 진동 RMS 0.036356 g 이하 3초 지속",
        "구동측 진동 센서 장착이 느슨해 측정 상태가 변했다.",
        "센서 장착과 배선을 확인하고 안전 절차에 따라 센서를 다시 고정했다.",
        "같은 속도·하중에서 구동측 진동 측정값과 센서 상태를 확인했다.",
    ),
    (
        "M12",
        "de_vibration_rms_g",
        0.095,
        "g",
        "구동측 진동 RMS 0.088661 g 이상 3초 지속",
        "구동측 풀리 정렬 불량으로 벨트 접촉이 발생했다.",
        "에너지 차단 후 풀리와 벨트 정렬을 조정했다.",
        "같은 속도·하중 조건에서 진동과 접촉 여부를 재확인했다.",
    ),
    (
        "M13",
        "de_kurtosis",
        2.7,
        None,
        "구동측 첨도 2.8836 이하 3초 지속",
        "구동측 특징값 계산 설정이 승인된 정의와 달랐다.",
        "원시 파형과 첨도 계산 정의를 대조하고 승인된 설정을 복원했다.",
        "같은 계산 창에서 구동측 첨도와 원시 파형을 확인했다.",
    ),
    (
        "M14",
        "de_kurtosis",
        8.2,
        None,
        "구동측 첨도 7.7727 이상 3초 지속",
        "트레이 투입 시 충격이 구동측 가이드 접촉과 겹쳤다.",
        "에너지 차단 후 가이드 접촉을 조정하고 투입 시각과 파형을 대조했다.",
        "동일 계산 창의 첨도와 반복 충격이 줄어든 것을 확인했다.",
    ),
    (
        "M15",
        "nde_vibration_rms_g",
        0.04,
        "g",
        "반구동측 진동 RMS 0.044261 g 이하 3초 지속",
        "반구동측 센서 장착 상태가 느슨했다.",
        "센서 장착과 배선을 확인하고 안전 절차에 따라 다시 고정했다.",
        "같은 속도·하중 조건에서 반구동측 진동 측정값을 확인했다.",
    ),
    (
        "M16",
        "nde_vibration_rms_g",
        0.075,
        "g",
        "반구동측 진동 RMS 0.068554 g 이상 3초 지속",
        "반구동측 가드와 회전부 사이에 간헐적 접촉이 있었다.",
        "에너지 차단 후 가드 간격을 조정하고 접촉 흔적을 확인했다.",
        "동일 운전 조건에서 진동과 가드 접촉 여부를 재확인했다.",
    ),
    (
        "M17",
        "nde_kurtosis",
        2.5,
        None,
        "반구동측 첨도 2.7413 이하 3초 지속",
        "반구동측 특징값의 필터 설정이 변경됐다.",
        "신호 경로와 필터 설정을 점검하고 승인된 조건으로 복원했다.",
        "같은 계산 창에서 반구동측 첨도와 신호 상태를 확인했다.",
    ),
    (
        "M18",
        "nde_kurtosis",
        6.5,
        None,
        "반구동측 첨도 6.0248 이상 3초 지속",
        "반구동측 가이드의 반복 접촉으로 충격 피크가 나타났다.",
        "에너지 차단 후 가이드 접촉부를 조정하고 원시 파형을 확인했다.",
        "같은 조건의 파형과 첨도를 비교해 반복 충격 해소를 확인했다.",
    ),
]


def seed_cases(incidents, reports, users, author, reviewer, approver, *, entries=None):
    if len({author, reviewer, approver}) != 3:
        raise ValueError("시연 계정 세 개가 서로 달라야 합니다.")
    for employee, role in (
        (author, "현장 점검자"),
        (reviewer, "보전 팀장"),
        (approver, "관제 담당자"),
    ):
        user = users.get_user(employee)
        if not user or not user.is_active or user.role != role:
            raise ValueError(f"활성 {role} 시연 계정을 확인하세요: {employee}")
    results = []
    rows = entries if entries is not None else [(case, 1) for case in CASES]
    for index, (case, sequence) in enumerate(rows):
        code, field, value, unit, threshold, cause, action, trial = case
        code = f"BTT2-{code}"
        incident_id = (
            "INC-SAMPLE-M10-DUST-001"
            if code == "BTT2-M10" and sequence == 1
            else f"INC-SAMPLE-{code}-{sequence:03d}"
        )
        existing = incidents.get_incident(incident_id)
        if existing is not None:
            approved = reports.incident_approved_reports(author, incident_id)
            if existing.codes != [code] or len(approved) != 1:
                raise ValueError(
                    f"{incident_id}: 기존 사건이 미완성이거나 예상과 다릅니다. 확인 후 재시도하세요."
                )
            results.append((code, approved[0].report_id, "기존"))
            continue
        now = datetime.now(UTC)
        start = now - timedelta(days=len(rows) - index, minutes=30)
        incident = Incident(
            incident_id=incident_id,
            process_id="BAT-TRANSFER-01",
            asset_id="BLDC-001",
            codes=[code],
            severity="Error",
            first_detected_at=start,
            confirmed_at=start + timedelta(seconds=60),
            last_detected_at=start + timedelta(seconds=60),
            evidence=[
                SensorEvidence(field=field, value=value, unit=unit, threshold=threshold)
            ],
        )
        incidents.save_incident(incident)
        section, page = (
            ("03 이송·광전 현장 대응 절차", 4)
            if code[5] == "P"
            else (
                ("04 기동·속도·DC 입력전류 대응", 5)
                if int(code[6:]) <= 6
                else ("05 공급전압·외함 온도 대응", 6)
                if int(code[6:]) <= 10
                else ("06 진동·충격·특정 측 변화 대응", 7)
            )
        )
        evidence = Evidence(
            evidence_id=f"sample-manual-{code}",
            doc_id="BTT-MANUAL",
            doc_version="2.0",
            title="BTT-MANUAL_v2.0.pdf",
            page=page,
            section=section,
            text=action,
            citation=f"BTT-MANUAL v2.0 PDF {page}쪽",
        )
        # Do not present fictional maintenance actions as verbatim manual excerpts.
        if page == 4:
            evidence.text = (
                "트레이 위치와 후속 설비 수신 상태를 확인한다."
                if code in ("BTT2-P01", "BTT2-P06")
                else "센서 앞 물체 유무와 실제 출력 상태를 먼저 대조한다."
                if code in ("BTT2-P03", "BTT2-P04")
                else "목표속도·감속비·벨트 이송 조건·투입 프로그램 변경을 확인한다."
            )
        elif page == 5:
            evidence.text = {
                "BTT2-M02": "목표속도·기동 유예·부하·전압·실제 회전 측정 비교.",
                "BTT2-M03": "실제 과속인지 독립 측정으로 확인 후 설정 수정.",
                "BTT2-M05": "무부하·동력 분리·센서 스케일·배선·영점 확인.",
                "BTT2-M06": "간섭·과적재·벨트 장력·베어링/전달부 저항 후보 조사.",
            }[code]
        elif page == 6:
            evidence.text = {
                "BTT2-M07": "전원 출력과 드라이버 입력 측정값 비교",
                "BTT2-M08": "전원 설정·실측 확인, 감속·정지 시점과 연관성 조사.",
                "BTT2-M10": "온도 실측·위치 대조 후 부하·방열·주변 온도·기계 마찰 점검.",
            }[code]
        else:
            evidence.text = (
                "장착 풀림·센서 분리·감도·필터·데이터 경로와 Pearson/초과첨도 정의를 확인한다."
                if code in ("BTT2-M11", "BTT2-M13", "BTT2-M15", "BTT2-M17")
                else "체결·정렬·벨트/전달부·접촉 여부를 조사하고"
                if code in ("BTT2-M12", "BTT2-M16")
                else "트레이 투입시각과 충격이 겹치는지"
            )
        analysis = AnalysisResult(
            incident_id=incident_id,
            status="OK",
            observed_facts=f"{threshold}; {field}={value}",
            suspected_causes=[
                CauseCandidate(
                    cause=cause,
                    likelihood="미평가",
                    basis="해당 매뉴얼의 점검 항목을 참고한다.",
                    evidence_ids=[evidence.evidence_id],
                )
            ],
            recommended_checks=[action],
            evidence=[evidence],
            model="sample/manual",
            generated_at=start + timedelta(minutes=1),
        )
        incidents.save_analysis(analysis)
        doc = reports.create_draft(
            author,
            ReportDraft(
                incident_id=incident_id,
                data_origin="LIVE",
                form_data=ReportFormData(
                    actual_actions=action,
                    action_at=start + timedelta(minutes=10),
                    replaced_parts="없음",
                    confirmed_cause=cause,
                    ai_assessment="부분 일치",
                    trial_result="정상",
                    resolution="해결",
                    trial_details=trial,
                ),
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
        results.append((code, doc.report_id, "생성"))
        print(f"{code}: {doc.report_id} 생성 완료", flush=True)
    return results


def index_cases(reports, results, indexer_factory):
    """이번 사례의 대기·실패 작업만 등록한다. 완료된 작업은 건너뛴다."""
    indexed = failed = 0
    indexer = None
    for _, report_id, _ in results:
        with reports.locked_index_job(report_id, include_failed=True) as work:
            if work is None:
                continue
            try:
                if indexer is None:
                    indexer = indexer_factory()
                if indexer.index_report(work.report) != 1:
                    raise ValueError("보고서 색인 건수가 올바르지 않습니다.")
            except Exception as exc:
                work.finish(False)
                failed += 1
                print(f"{report_id}: 검색 등록 실패 ({type(exc).__name__})", flush=True)
            else:
                work.finish(True)
                indexed += 1
    return indexed, failed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--author", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--approver", required=True)
    args = parser.parse_args()
    settings = get_settings()
    url = settings.database_url
    if urlsplit(url).hostname not in ("localhost", "127.0.0.1", "::1"):
        raise SystemExit("로컬 PostgreSQL에서만 실행할 수 있습니다.")
    if (
        settings.vector_store == "qdrant"
        and settings.qdrant_url
        and urlsplit(settings.qdrant_url).hostname
        not in ("localhost", "127.0.0.1", "::1")
    ):
        raise SystemExit("로컬 Qdrant에서만 실행할 수 있습니다.")
    incidents, reports, users = (
        db.open_incidents(url),
        db.open_reports(url),
        db.open_users(url),
    )
    try:
        results = seed_cases(
            incidents, reports, users, args.author, args.reviewer, args.approver
        )
        print(
            f"완료: {len(results)}건 (신규 {sum(row[2] == '생성' for row in results)}건, 기존 {sum(row[2] == '기존' for row in results)}건)"
        )
        indexed, failed = index_cases(reports, results, rag.get_indexer)
        print(f"검색 등록 완료 {indexed}건, 실패 {failed}건 (기존 등록은 건너뜀)")
        if failed:
            raise SystemExit(
                "검색 등록에 실패했습니다. 원인 확인 후 같은 명령을 다시 실행하세요."
            )
    finally:
        rag.close_rag_resources()
        for repo in (incidents, reports, users):
            repo._engine.dispose()


if __name__ == "__main__":
    main()
