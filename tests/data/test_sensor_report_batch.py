from collections import Counter
from datetime import timedelta
from pathlib import Path

import pytest

from weeing_weeing.contracts import Role, UserAccount
from weeing_weeing.db import interface as db
from weeing_weeing.db.models import Base


@pytest.fixture
def batch(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    import seed_330_sensor_reports

    return seed_330_sensor_reports


def test_all_cases_cover_original_codes_with_one_matching_sensor(batch):
    cases = batch.build_cases()
    assert len(cases) == 330
    assert len({c["incident"].incident_id for c in cases}) == 330
    assert len({c["samples"][0].timestamp for c in cases}) == 330
    counts = Counter(c["incident"].codes[0] for c in cases)
    assert set(counts) == {f"BTT2-{code}" for code in batch.EXPECTED_CODES}
    assert set(counts.values()) == {15}
    assert not set(counts) & {"BTT2-M01", "BTT2-M04", "BTT2-M09", "BTT2-M19"}
    assert cases == batch.build_cases()
    for case in cases:
        incident = case["incident"]
        assert incident.incident_id.startswith("INC-SENSOR-BATCH-V1-")
        assert incident.telemetry_provenance.origin == "SIMULATION"
        assert len(case["samples"]) == 1
        sample = case["samples"][0]
        assert sample.timestamp == incident.confirmed_at
        evidence = incident.evidence[0]
        if evidence.field in type(sample).model_fields:
            assert getattr(sample, evidence.field) == evidence.value
        assert "단일 표본" in evidence.note
        result = batch.build_analysis(case)
        assert result.status == "OK"
        assert (
            result.suspected_causes
            and result.recommended_checks
            and result.recommended_actions
        )
        assert result.evidence[0].doc_id.startswith("SENSOR-BATCH-GUIDE-")
        assert case["form"].confirmed_cause not in str(result.model_dump())
        assert case["form"].actual_actions not in str(result.model_dump())
        assert len(result.check_citations) == len(result.recommended_checks)


def test_register_all_codes_report_snapshot_and_retry(batch, monkeypatch, tmp_path):
    from weeing_weeing.api.reports import incident_report_context
    from weeing_weeing.db import users as user_module

    monkeypatch.setattr(user_module, "SCRYPT_N", 2**10)
    url = f"sqlite:///{tmp_path / 'reports.db'}"
    engine = db.open_engine(url)
    Base.metadata.create_all(engine)
    repos = [
        opener(url)
        for opener in (
            db.open_incidents,
            db.open_reports,
            db.open_users,
            db.open_telemetry,
            db.open_analysis_jobs,
        )
    ]
    incidents, reports, users, telemetry, jobs = repos
    try:
        actors = []
        for employee, role in (
            ("I1", Role.INSPECTOR),
            ("L1", Role.MAINT_LEAD),
            ("C1", Role.CONTROL),
        ):
            actor = UserAccount(employee_no=employee, name="시험", role=role)
            users.create_user(actor, "fixture-test-password")
            actors.append(actor)
        for getter, repo in (
            ("get_incidents", incidents),
            ("get_reports", reports),
            ("get_telemetry", telemetry),
            ("get_analysis_jobs", jobs),
        ):
            monkeypatch.setattr(db, getter, lambda repo=repo: repo)
        all_cases = batch.build_cases()
        cases = all_cases
        assert len(cases) == 330
        results = batch.seed_cases(
            *repos, "I1", "L1", "C1", cases=cases, analysis_builder=batch.build_analysis
        )
        assert len(results) == 330 and all(item[2] == "생성" for item in results)
        for case, (_, report_id, _) in zip(cases, results):
            context = incident_report_context(
                case["incident"].incident_id, actors[0], reports, report_id
            )
            assert context["document"].data_origin == "SYNTHETIC"
            assert context["document"].report_status == "APPROVED"
            assert context["analysis"] == batch.build_analysis(case)
            assert context["telemetry"] == case["samples"][0]
            assert context["telemetry_notes"] == []
            anchor = case["incident"].confirmed_at
            rows = telemetry.observations_between(
                "BLDC-001",
                anchor,
                anchor + timedelta(seconds=1),
                process_id="BAT-TRANSFER-01",
            )
            assert len(rows) == 1 and rows[0][1].origin == "SIMULATION"
        again = batch.seed_cases(
            *repos, "I1", "L1", "C1", cases=cases, analysis_builder=batch.build_analysis
        )
        assert all(item[2] == "기존" for item in again)

        class FakeIndexer:
            def index_report(self, report):
                assert report.data_origin == "SYNTHETIC"
                return 1

        assert batch.index_cases(reports, results, FakeIndexer) == (330, 0)
        assert batch.index_cases(reports, again, FakeIndexer) == (0, 0)
    finally:
        for repo in repos:
            repo._engine.dispose()
        engine.dispose()
