import importlib.util
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from weeing_weeing.contracts import IncidentStatus, Role, UserAccount
from weeing_weeing.db import interface as db
from weeing_weeing.db.models import Base


def test_cases_and_environment_checks(monkeypatch):
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "seed_330", scripts / "seed_330_reports.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    entries = module.build_entries()
    assert len(entries) == 330
    assert set(Counter(case[0] for case, _ in entries).values()) == {15}
    for code in {case[0] for case, _ in entries}:
        cases = [case for case, _ in entries if case[0] == code]
        assert len({case[5] for case in cases}) == 5
        assert len({(case[5], case[6], case[7]) for case in cases}) == 15
    # 사건 ID는 (코드, 순번)으로 만든다. 330건 모두 겹치지 않아야 DB 등록이 서로 덮이지 않는다.
    assert len({(case[0], sequence) for case, sequence in entries}) == 330
    local = SimpleNamespace(
        database_url="postgresql://user@localhost/db",
        vector_store="qdrant",
        qdrant_url="http://localhost:6333",
    )
    aws = SimpleNamespace(
        database_url="postgresql://user@postgres/db",
        vector_store="qdrant",
        qdrant_url="http://qdrant:6333",
    )
    module.validate_target(local, False)
    module.validate_target(aws, True)
    with pytest.raises(ValueError):
        module.validate_target(aws, False)
    with pytest.raises(ValueError):
        module.validate_target(local, True)


def test_batch_includes_existing_reports_and_indexes(monkeypatch, tmp_path):
    from weeing_weeing.db import users as user_module

    monkeypatch.setattr(user_module, "SCRYPT_N", 2**10)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    import seed_22_reports
    import seed_330_reports

    url = f"sqlite:///{tmp_path / 'batch.db'}"
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
        first = seed_22_reports.seed_cases(incidents, reports, users, "I1", "L1", "C1")
        assert len(first) == 22
        # 330건 구성은 위 테스트가 확인한다. DB 등록 흐름은 코드 2개(30건)로 본다.
        # M10은 1번 사례의 사건 ID가 따로 정해져 있어(INC-SAMPLE-M10-DUST-001) 포함한다.
        entries = [
            (case, sequence)
            for case, sequence in seed_330_reports.build_entries()
            if case[0] in {"P01", "M10"}
        ]
        assert len(entries) == 30
        batch = seed_22_reports.seed_cases(
            incidents, reports, users, "I1", "L1", "C1", entries=entries
        )
        assert Counter(row[2] for row in batch) == {"기존": 2, "생성": 28}
        assert len(reports.approved_reports()) == 22 + 28
        saved = incidents.list_incidents(limit=100)
        assert len(saved) == 22 + 28
        assert all(item.status == IncidentStatus.RECOVERED for item in saved)
        assert all(
            item.recovered_at is not None and item.recovered_at > item.last_detected_at
            for item in saved
        )

        class FakeIndexer:
            fail_once = True

            def index_report(self, report):
                if FakeIndexer.fail_once:
                    FakeIndexer.fail_once = False
                    raise RuntimeError("simulated failure")
                return 1

        assert seed_22_reports.index_cases(reports, batch, FakeIndexer) == (29, 1)
        assert seed_22_reports.index_cases(reports, batch, FakeIndexer) == (1, 0)
        again = seed_22_reports.seed_cases(
            incidents, reports, users, "I1", "L1", "C1", entries=entries
        )
        assert all(row[2] == "기존" for row in again)
        assert seed_22_reports.index_cases(reports, again, FakeIndexer) == (0, 0)
    finally:
        for repo in (users, reports, incidents):
            repo._engine.dispose()
        engine.dispose()
