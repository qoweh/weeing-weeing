import importlib.util
from pathlib import Path

import pytest

from weeing_weeing.contracts import Role, UserAccount
from weeing_weeing.db import interface as db
from weeing_weeing.db.models import Base


def test_seed_creates_approved_report_and_rejects_duplicate(tmp_path, monkeypatch):
    from weeing_weeing.db import users as user_module

    monkeypatch.setattr(user_module, "SCRYPT_N", 2**10)
    spec = importlib.util.spec_from_file_location(
        "seed_one_report",
        Path(__file__).resolve().parents[2] / "scripts/seed_one_report.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    url = f"sqlite:///{tmp_path / 'seed.db'}"
    engine = db.open_engine(url)
    Base.metadata.create_all(engine)
    users = db.open_users(url)
    reports = db.open_reports(url)
    incidents = db.open_incidents(url)
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
        doc = module.seed(incidents, reports, users, "I1", "L1", "C1")
        assert doc.report_status == "APPROVED"
        assert doc.index_status == "pending"
        assert len(doc.approval) == 3
        assert doc.ai_analysis.model == "sample/manual"
        assert reports.approved_reports()[0].incident.codes == ["BTT2-M10"]
        with pytest.raises(ValueError, match="이미 있습니다"):
            module.seed(incidents, reports, users, "I1", "L1", "C1")
    finally:
        for repo in (users, reports, incidents):
            repo._engine.dispose()
        engine.dispose()
