"""승인된 정비 보고서의 사람 작성 칸을 검색용 사례 한 단위로 바꾼다."""

from zoneinfo import ZoneInfo

from weeing_weeing.contracts import MaintenanceReport, ReportStatus
from weeing_weeing.rag.store import Chunk, make_chunk_id


def report_chunk(report: MaintenanceReport) -> Chunk:
    """AI 추정·결재 정보는 본문과 메타데이터 어느 쪽에도 넣지 않는다."""
    if report.report_status != ReportStatus.APPROVED:
        raise ValueError("최종 승인된 보고서만 색인할 수 있습니다.")
    if report.maintenance is None:
        raise ValueError("사람이 작성한 정비 내용이 없습니다.")
    if report.incident_id != report.incident.incident_id:
        raise ValueError("보고서와 사건 ID가 일치하지 않습니다.")

    # 검색에 필요한 사람 작성 항목만 선택한다. 보고서 전체 JSON은 LLM에 보내지 않는다.
    maintenance = report.maintenance
    lines = [
        f"설비 ID: {report.asset_id}",
        f"고장 코드: {', '.join(report.incident.codes)}",
    ]
    for label, value in (
        ("원인 분류", maintenance.cause_category),
        ("확인 원인", maintenance.confirmed_cause),
    ):
        if value and value.strip():
            lines.append(f"{label}: {value.strip()}")
    lines.extend(
        f"실제 조치 ({action.at.astimezone(ZoneInfo('Asia/Seoul')).isoformat()}): {action.action.strip()}"
        for action in maintenance.actions_taken
        if action.action.strip()
    )
    if maintenance.parts_replaced:
        lines.append(f"교체 부품: {', '.join(maintenance.parts_replaced)}")
    if maintenance.ai_assessment:
        lines.append(f"AI 의견에 대한 현장 평가: {maintenance.ai_assessment}")
    if len(lines) == 2:
        raise ValueError("색인할 사람 작성 원인·조치가 없습니다.")

    # 합성 데이터가 실제 정비 사실로 받아들여지지 않게 인용과 메타데이터에 표시한다.
    citation = f"{report.report_id} 정비 이력"
    if report.data_origin == "SYNTHETIC":
        citation += " (가상 사례)"
    version = str(report.report_version)
    return Chunk(
        chunk_id=make_chunk_id(report.report_id, version, 1),
        doc_id=report.report_id,
        doc_version=version,
        text="\n".join(lines),
        metadata={
            "doc_type": "report",
            "status": "approved",
            "codes": list(report.incident.codes),
            "data_origin": report.data_origin,
            "asset_id": report.asset_id,
            "action_dates": sorted(
                {
                    action.at.astimezone(ZoneInfo("Asia/Seoul")).date().isoformat()
                    for action in maintenance.actions_taken
                }
            ),
            "citation": citation,
            "title": f"{report.report_id} 정비 이력",
        },
    )
