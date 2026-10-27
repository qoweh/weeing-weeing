"""#30: 과거 정비 이력은 사람 작성 사례를 코드별로 비교할 수 있어야 한다."""

import json
from collections import defaultdict
from pathlib import Path

from weeing_weeing.contracts import MaintenanceReport

DATA = Path(__file__).resolve().parents[2] / "data/history/synthetic_reports_v1.jsonl"
EXPECTED_CODES = {
    "BTT2-P01",
    "BTT2-P03",
    "BTT2-P06",
    "BTT2-M01",
    "BTT2-M02",
    "BTT2-M12",
    "BTT2-M14",
    "BTT2-M16",
}


def test_synthetic_history_has_varied_valid_approved_cases():
    lines = DATA.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 24
    assert all(line.strip() for line in lines)
    reports = [MaintenanceReport.model_validate(json.loads(line)) for line in lines]
    assert len({report.report_id for report in reports}) == len(reports)
    assert len({report.incident_id for report in reports}) == len(reports)

    by_code = defaultdict(list)
    for report in reports:
        assert report.report_status == "APPROVED"
        assert report.data_origin == "SYNTHETIC"
        assert report.report_version == 1
        assert report.incident_id == report.incident.incident_id
        assert report.process_id == report.incident.process_id
        assert report.asset_id == report.incident.asset_id
        assert report.incident.profile == "DEMO"
        assert report.incident.evidence
        assert report.ai_analysis is not None
        assert report.ai_analysis.incident_id == report.incident_id
        assert report.ai_analysis.model == "synthetic/example"
        assert report.maintenance is not None
        assert report.maintenance.confirmed_cause
        assert report.maintenance.actions_taken
        assert report.maintenance.test_run.result == "정상"
        assert [step.decision for step in report.approval] == ["제출", "승인", "승인"]
        assert [step.step for step in report.approval] == [1, 2, 3]
        assert all(step.user.startswith("SYN-") for step in report.approval)
        assert report.incident.codes and len(report.incident.codes) == 1
        by_code[report.incident.codes[0]].append(report)

    assert set(by_code) == EXPECTED_CODES
    for group in by_code.values():
        assert len(group) == 3
        assert len({r.maintenance.confirmed_cause for r in group}) == 3
        assert {r.maintenance.ai_assessment for r in group} == {
            "일치",
            "부분 일치",
            "불일치",
        }
