from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from weeing_weeing.api.app import app
from weeing_weeing.contracts import Incident, Role, UserAccount
from weeing_weeing.db import interface as db

PASSWORD = "report-test-password"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from weeing_weeing.db import users

    monkeypatch.setattr(users, "SCRYPT_N", 2**10)
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
        == 403
    )
    assert client.get("/reports?scope=review", headers=auth(client)).status_code == 403
    assert (
        client.get("/incidents", headers=auth(client)).json()[0]["incident_id"]
        == "INC-1"
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
