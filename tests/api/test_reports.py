from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from weeing_weeing.api.app import app
from weeing_weeing.api.report_index import process_pending_reports
from weeing_weeing.contracts import Incident, Role, UserAccount
from weeing_weeing.db import interface as db

PASSWORD = "report-test-password"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from weeing_weeing.api import reports as report_api
    from weeing_weeing.db import users

    monkeypatch.setattr(users, "SCRYPT_N", 2**10)
    monkeypatch.setattr(report_api, "run_pending_reports", lambda: None)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'reports.db'}")
    for employee, role in (
        ("I1", Role.INSPECTOR),
        ("I2", Role.INSPECTOR),
        ("L1", Role.MAINT_LEAD),
        ("C1", Role.CONTROL),
    ):
        db.get_users().create_user(
            UserAccount(employee_no=employee, name=employee, role=role), PASSWORD
        )
    db.get_incidents().save_incident(
        Incident(
            incident_id="INC-1",
            process_id="P1",
            asset_id="A1",
            codes=["BTT2-P03"],
            severity="Error",
            first_detected_at=datetime.now(timezone.utc),
            last_detected_at=datetime.now(timezone.utc),
        )
    )
    with TestClient(app) as client:
        yield client


def auth(client, employee="I1"):
    response = client.post(
        "/auth/login", json={"employee_no": employee, "password": PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create(client, **overrides):
    payload = {
        "incident_id": "INC-1",
        "data_origin": "SYNTHETIC",
        "form_data": {
            "actual_actions": "센서 청소",
            "action_at": "2026-10-28T09:00:00+09:00",
            "confirmed_cause": "오염",
            "trial_details": "빈 이송 시험",
            "trial_result": "정상",
        },
    } | overrides
    response = client.post("/reports", json=payload, headers=auth(client))
    assert response.status_code == 201, response.text
    return response.json()


def action(client, doc, verb, actor="I1", **extra):
    return client.post(
        f"/reports/{doc['report_id']}/{verb}",
        headers=auth(client, actor),
        json={"expected_revision": doc["revision"], **extra},
    )


def test_login_draft_reload_and_ownership(client):
    assert client.get("/reports").status_code == 401
    doc = create(client, incident_id=None, form_data={})
    assert doc["author_id"] == "I1" and doc["report"] is None
    assert (
        client.get(f"/reports/{doc['report_id']}", headers=auth(client)).json() == doc
    )
    assert client.get("/reports", headers=auth(client, "I2")).json() == []
    assert (
        client.get(
            f"/reports/{doc['report_id']}", headers=auth(client, "I2")
        ).status_code
        == 200
    )
    assert client.get("/reports?scope=review", headers=auth(client)).status_code == 403
    assert (
        client.get("/incidents", headers=auth(client)).json()[0]["incident_id"]
        == "INC-1"
    )


def test_common_read_includes_drafts_rejections_and_old_versions_but_not_write(client):
    doc = create(client)
    path = f"/reports/{doc['report_id']}"
    other = auth(client, "I2")
    assert client.get(path).status_code == 401
    assert client.get("/reports?scope=all").status_code == 401
    assert client.get(path, headers=other).status_code == 200
    assert [
        r["report_id"] for r in client.get("/reports?scope=all", headers=other).json()
    ] == [doc["report_id"]]
    assert (
        client.put(
            path + "/draft", headers=other, json={"expected_revision": doc["revision"]}
        ).status_code
        == 403
    )
    doc = action(client, doc, "submit").json()
    rejected = action(client, doc, "reject", "L1", comment="보완 필요").json()
    assert client.get(path, headers=other).json()["report_status"] == "REJECTED"
    assert action(client, rejected, "revise", "I2").status_code == 403
    revised = action(client, rejected, "revise").json()
    assert revised["report_version"] == 2
    assert client.get(path, headers=other).json()["report_status"] == "DRAFT"
    assert (
        client.get(path + "/versions/1", headers=other).json()["report_status"]
        == "REJECTED"
    )


def test_spoofed_metadata_and_wrong_roles_are_rejected(client):
    assert (
        client.post(
            "/reports", json={"author_id": "C1"}, headers=auth(client)
        ).status_code
        == 422
    )
    assert (
        client.post("/reports", json={}, headers=auth(client, "L1")).status_code == 403
    )
    doc = create(client)
    submitted = action(client, doc, "submit").json()
    assert action(client, submitted, "approve", "C1").status_code == 409
    assert action(client, submitted, "review", "I2").status_code == 403


def test_end_to_end_approval_and_revision(client):
    doc = create(client)
    for verb, actor in (("submit", "I1"), ("review", "L1"), ("approve", "C1")):
        response = action(client, doc, verb, actor)
        assert response.status_code == 200, response.text
        doc = response.json()
    assert doc["report_status"] == "APPROVED" and doc["index_status"] == "pending"
    assert [a["user"] for a in doc["approval"]] == ["I1", "L1", "C1"]
    assert doc["report"]["maintenance"]["actions_taken"][0]["by"] == "I1"
    revised = action(client, doc, "revise")
    assert revised.status_code == 201
    assert revised.json()["report_version"] == 2
    old = client.get(f"/reports/{doc['report_id']}/versions/1", headers=auth(client))
    assert old.json()["report"] == doc["report"]


def test_save_conflict_and_rejected_version_remains_read_only(client):
    doc = create(client)
    body = {
        "expected_revision": doc["revision"],
        "incident_id": "INC-1",
        "form_data": {
            "actual_actions": "수정",
            "action_at": "2026-10-28T09:00:00+09:00",
            "confirmed_cause": "오염",
            "trial_details": "시험",
        },
    }
    path = f"/reports/{doc['report_id']}/draft"
    saved = client.put(path, json=body, headers=auth(client))
    assert saved.status_code == 200
    assert client.put(path, json=body, headers=auth(client)).status_code == 409
    submitted = action(client, saved.json(), "submit").json()
    assert action(client, submitted, "reject", "L1").status_code == 422
    rejected = action(client, submitted, "reject", "L1", comment="결과 보완")
    assert rejected.status_code == 200
    assert (
        client.put(
            path,
            json={**body, "expected_revision": rejected.json()["revision"]},
            headers=auth(client),
        ).status_code
        == 409
    )


def test_incomplete_submission_and_unknown_incident_are_422(client):
    draft = create(client, form_data={})
    assert action(client, draft, "submit").status_code == 422
    response = client.post(
        "/reports", json={"incident_id": "missing"}, headers=auth(client)
    )
    assert response.status_code == 422
    assert client.get("/reports/missing", headers=auth(client)).status_code == 404


def test_final_approval_background_indexes_and_failure_can_be_retried(
    client, monkeypatch
):
    from weeing_weeing.api import reports as report_api

    indexed = []

    class FakeIndexer:
        def index_report(self, report):
            indexed.append(report.report_id)
            return 1

    def index_now():
        return process_pending_reports(db.get_reports(), FakeIndexer)

    monkeypatch.setattr(report_api, "run_pending_reports", index_now)
    doc = create(client)
    for verb, actor in (("submit", "I1"), ("review", "L1"), ("approve", "C1")):
        response = action(client, doc, verb, actor)
        assert response.status_code == 200, response.text
        doc = response.json()
    assert indexed == [doc["report_id"]]
    refreshed = client.get(f"/reports/{doc['report_id']}", headers=auth(client)).json()
    assert refreshed["index_status"] == "indexed"

    class BrokenIndexer:
        def index_report(self, report):
            raise RuntimeError("벡터 저장 실패")

    monkeypatch.setattr(
        report_api,
        "run_pending_reports",
        lambda: process_pending_reports(db.get_reports(), BrokenIndexer),
    )
    other = create(client)
    for verb, actor in (("submit", "I1"), ("review", "L1"), ("approve", "C1")):
        response = action(client, other, verb, actor)
        assert response.status_code == 200, response.text
        other = response.json()
    failed = client.get(f"/reports/{other['report_id']}", headers=auth(client)).json()
    assert failed["index_status"] == "failed"
    result = process_pending_reports(db.get_reports(), FakeIndexer, retry_failed=True)
    assert result.indexed == 1 and result.failed == 0
    assert indexed == [doc["report_id"], other["report_id"]]
