from datetime import timedelta
from pathlib import Path

import pytest

from weeing_weeing.contracts import Role, UserAccount
from weeing_weeing.db import interface as db
from weeing_weeing.db.models import Base


@pytest.fixture
def seed_module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    import seed_5_sensor_reports

    return seed_5_sensor_reports


def test_cases_have_one_sample_and_complete_recommendations(seed_module):
    cases = seed_module.build_cases()
    assert len(cases) == 5
    assert len({case["incident"].incident_id for case in cases}) == 5
    for case in cases:
        assert len(case["samples"]) == 1
        sample = case["samples"][0]
        assert sample.timestamp == case["incident"].confirmed_at
        assert sample.motor_housing_temp_c == case["incident"].evidence[0].value
        analysis = seed_module.build_analysis(case)
        assert analysis.status == "OK"
        assert analysis.suspected_causes and analysis.recommended_checks
        assert analysis.recommended_actions and analysis.evidence
        assert case["form"].confirmed_cause not in str(analysis.model_dump())


def test_reports_show_event_sensor_and_analysis_and_rerun_is_safe(
    seed_module, tmp_path, monkeypatch
):
    from weeing_weeing.api.reports import incident_report_context
    from weeing_weeing.db import users as user_module

    monkeypatch.setattr(user_module, "SCRYPT_N", 2**10)
    url = f"sqlite:///{tmp_path / 'sensors.db'}"
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
            actor = UserAccount(employee_no=employee, name="시연 계정", role=role)
            users.create_user(actor, "fake-test-password-only")
            actors.append(actor)
        for getter, repo in (
            ("get_incidents", incidents),
            ("get_reports", reports),
            ("get_telemetry", telemetry),
            ("get_analysis_jobs", jobs),
        ):
            monkeypatch.setattr(db, getter, lambda repo=repo: repo)
        results = seed_module.seed_cases(*repos, "I1", "L1", "C1")
        assert len(results) == 5
        for case, (_, report_id, state) in zip(seed_module.build_cases(), results):
            assert state == "생성"
            context = incident_report_context(
                case["incident"].incident_id, actors[0], reports, report_id
            )
            assert context["document"].data_origin == "SYNTHETIC"
            assert context["document"].report_status == "APPROVED"
            assert context["analysis"].status == "OK"
            assert context["analysis"].recommended_checks
            assert (
                context["telemetry"].motor_housing_temp_c
                == case["samples"][0].motor_housing_temp_c
            )
            anchor = case["incident"].confirmed_at
            observations = telemetry.observations_between(
                "BLDC-001",
                anchor,
                anchor + timedelta(seconds=1),
                process_id="BAT-TRANSFER-01",
            )
            assert len(observations) == 1
            assert observations[0][1].origin == "SIMULATION"
        assert len(reports.approved_reports()) == 5
        assert all(
            row[2] == "기존" for row in seed_module.seed_cases(*repos, "I1", "L1", "C1")
        )
    finally:
        for repo in repos:
            repo._engine.dispose()
        engine.dispose()


def test_preview_does_not_open_database_or_settings(seed_module, monkeypatch, tmp_path):
    import json

    from weeing_weeing import config

    def forbidden(*args, **kwargs):
        raise AssertionError("미리보기는 DB나 설정을 읽으면 안 됩니다")

    monkeypatch.setattr(config, "get_settings", forbidden)
    monkeypatch.setattr(db, "open_incidents", forbidden)
    output = tmp_path / "preview.json"
    monkeypatch.setattr("sys.argv", ["seed_5_sensor_reports", "--output", str(output)])
    seed_module.main()
    cases = json.loads(output.read_text())
    assert len(cases) == 5
    assert sum(len(case["samples"]) for case in cases) == 5


@pytest.mark.parametrize(
    "database_url", ["sqlite:///storage/dev.db", "postgresql://fake@localhost/demo"]
)
def test_local_registration_needs_no_qdrant(seed_module, database_url):
    from types import SimpleNamespace

    settings = SimpleNamespace(
        database_url=database_url,
        vector_store="qdrant",
        qdrant_url="http://remote.invalid:6333",
    )
    seed_module.validate_target(settings, False)
    with pytest.raises(ValueError):
        seed_module.validate_target(settings, False, index=True)


def test_recommendations_are_distinct_and_preserve_common_safety(seed_module):
    cases = seed_module.build_cases()
    results = [seed_module.build_analysis(case) for case in cases]
    assert len({result.suspected_causes[0].cause for result in results}) == 5
    assert len({result.recommended_checks[2] for result in results}) == 5
    assert len({result.recommended_actions[0] for result in results}) == 5
    for case, result in zip(cases, results):
        assert "위험을 통제" in result.recommended_checks[0]
        assert "독립 계측기" in result.recommended_checks[1]
        assert case["form"].confirmed_cause not in str(result.model_dump())
        assert len(result.check_citations) == len(result.recommended_checks)
