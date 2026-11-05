import importlib.util
from pathlib import Path

import pytest

from weeing_weeing.contracts import Role, UserAccount
from weeing_weeing.db import interface as db
from weeing_weeing.db.models import Base


def test_22_reports_are_approved_and_repeat_is_safe(tmp_path, monkeypatch):
    from weeing_weeing.db import users as user_module

    monkeypatch.setattr(user_module, "SCRYPT_N", 2**10)
    spec = importlib.util.spec_from_file_location(
        "seed_22", Path(__file__).resolve().parents[2] / "scripts/seed_22_reports.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    url = f"sqlite:///{tmp_path / 'seed.db'}"
    engine = db.open_engine(url)
    Base.metadata.create_all(engine)
    users, reports, incidents = (
        db.open_users(url),
        db.open_reports(url),
        db.open_incidents(url),
    )
    try:
        for employee, role in (
            ("I1", Role.INSPECTOR),
            ("L1", Role.MAINT_LEAD),
            ("C1", Role.CONTROL),
        ):
            users.create_user(
                UserAccount(employee_no=employee, name=employee, role=role),
                "test-password-123",
            )
        results = module.seed_cases(incidents, reports, users, "I1", "L1", "C1")
        assert len(results) == len({row[0] for row in results}) == 22
        assert all(row[2] == "생성" for row in results)
        assert len(reports.approved_reports()) == 22
        assert len(reports.pending_index_reports(limit=100)) == 22

        class FakeIndexer:
            def index_report(self, report):
                assert report.report_status == "APPROVED"
                return 1

        assert module.index_cases(reports, results, FakeIndexer) == (22, 0)
        assert reports.pending_index_reports(limit=100) == []
        assert module.index_cases(reports, results, FakeIndexer) == (0, 0)
        assert all(
            row[2] == "기존"
            for row in module.seed_cases(incidents, reports, users, "I1", "L1", "C1")
        )
        assert len(reports.approved_reports()) == 22
        with pytest.raises(ValueError, match="서로 달라야"):
            module.seed_cases(incidents, reports, users, "I1", "I1", "C1")
    finally:
        for repo in (users, reports, incidents):
            repo._engine.dispose()
        engine.dispose()
