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
        ("L2", Role.MAINT_LEAD),
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


def create(client, actor="I1", **overrides):
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
    response = client.post("/reports", json=payload, headers=auth(client, actor))
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
    doc = create(client, form_data={})
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
        client.post("/reports", json={}, headers=auth(client, "C1")).status_code == 403
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
    assert revised.status_code == 409
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
    assert client.post("/reports", json={}, headers=auth(client)).status_code == 422
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


def test_lead_author_submits_directly_to_control_and_revises_rejection(client):
    doc = create(client, actor="L1")
    saved = client.put(
        f"/reports/{doc['report_id']}/draft",
        headers=auth(client, "L1"),
        json={
            "incident_id": "INC-1",
            "form_data": doc["form_data"],
            "expected_revision": doc["revision"],
        },
    )
    assert saved.status_code == 200
    submitted = action(client, saved.json(), "submit", "L1")
    assert submitted.status_code == 200, submitted.text
    doc = submitted.json()
    assert doc["report_status"] == "REVIEWED"
    assert [(a["user"], a["decision"]) for a in doc["approval"]] == [("L1", "제출")]
    assert client.get("/reports?scope=review", headers=auth(client, "L1")).json() == []
    assert [
        r["report_id"]
        for r in client.get("/reports?scope=review", headers=auth(client, "C1")).json()
    ] == [doc["report_id"]]
    assert doc["index_status"] is None
    assert action(client, doc, "review", "L1").status_code == 403
    assert action(client, doc, "review", "L2").status_code == 409
    assert action(client, doc, "reject", "L2", comment="보완").status_code == 403
    rejected = action(client, doc, "reject", "C1", comment="보완 필요").json()
    assert rejected["report_status"] == "REJECTED" and rejected["index_status"] is None
    assert db.get_reports().pending_index_reports() == []
    revised = action(client, rejected, "revise", "L1")
    assert revised.status_code == 201
    doc = revised.json()
    assert doc["report_version"] == 2 and doc["report_status"] == "DRAFT"
    assert doc["index_status"] is None
    doc = action(client, doc, "submit", "L1").json()
    assert doc["report_status"] == "REVIEWED" and doc["index_status"] is None
    approved = action(client, doc, "approve", "C1").json()
    assert (
        approved["report_status"] == "APPROVED"
        and approved["index_status"] == "pending"
    )
    assert [a["user"] for a in approved["approval"]] == ["L1", "C1"]
    assert action(client, approved, "revise", "L1").status_code == 409
    assert [r.report_version for r in db.get_reports().pending_index_reports()] == [2]


def test_draft_delete_and_rejected_version_restore(client):
    doc = create(client)
    url = f"/reports/{doc['report_id']}/draft"
    assert (
        client.request(
            "DELETE",
            url,
            json={"expected_revision": doc["revision"]},
            headers=auth(client, "I2"),
        ).status_code
        == 403
    )
    assert (
        client.request(
            "DELETE",
            url,
            json={"expected_revision": doc["revision"] + 1},
            headers=auth(client),
        ).status_code
        == 409
    )
    submitted = action(client, doc, "submit").json()
    rejected = action(client, submitted, "reject", "L1", comment="사유 보존").json()
    draft = action(client, rejected, "revise").json()
    response = client.request(
        "DELETE",
        url,
        json={"expected_revision": draft["revision"]},
        headers=auth(client),
    )
    assert response.status_code == 200
    restored = response.json()["report"]
    assert restored["report_status"] == "REJECTED" and restored["report_version"] == 1
    assert restored["approval"][-1]["comment"] == "사유 보존"
    assert (
        client.get(
            f"/reports/{doc['report_id']}/versions/2", headers=auth(client)
        ).status_code
        == 404
    )
    assert action(client, restored, "revise").json()["report_version"] == 2

    other = create(client)
    deleted = client.request(
        "DELETE",
        f"/reports/{other['report_id']}/draft",
        json={"expected_revision": other["revision"]},
        headers=auth(client),
    )
    assert deleted.json() == {"status": "deleted", "report": None}
    assert (
        client.get(f"/reports/{other['report_id']}", headers=auth(client)).status_code
        == 404
    )
    assert create(client)["report_id"] != other["report_id"]


def test_approved_delete_requires_control_and_removes_actual_vector(
    client, monkeypatch
):
    from qdrant_client import QdrantClient

    from weeing_weeing.rag import interface as rag
    from weeing_weeing.rag.indexer import DocumentIndexer
    from weeing_weeing.rag.qdrant_store import QdrantVectorStore
    from weeing_weeing.rag.sparse import KiwiBm25Encoder

    class Embedder:
        dim = 3

        def embed_documents(self, texts):
            return [[1.0, 0.0, 0.0] for _ in texts]

        def embed_query(self, _):
            return [1.0, 0.0, 0.0]

    vector_client = QdrantClient(":memory:")
    store = QdrantVectorStore(
        vector_client,
        embedder=Embedder(),
        embedding_model="test",
        sparse_encoder=KiwiBm25Encoder(),
    )
    indexer = DocumentIndexer(store)
    monkeypatch.setattr(rag, "get_indexer", lambda: indexer)
    doc = create(client)
    for verb, actor in (("submit", "I1"), ("review", "L1"), ("approve", "C1")):
        doc = action(client, doc, verb, actor).json()
    assert process_pending_reports(db.get_reports(), lambda: indexer).indexed == 1
    assert len(store.documents()) == 1
    url = f"/reports/{doc['report_id']}"
    body = {"expected_revision": doc["revision"]}
    assert (
        client.request("DELETE", url, json=body, headers=auth(client, "L1")).status_code
        == 403
    )
    assert (
        client.request(
            "DELETE",
            url,
            json={"expected_revision": doc["revision"] + 1},
            headers=auth(client, "C1"),
        ).status_code
        == 409
    )
    assert len(store.documents()) == 1

    class BrokenIndexer:
        def delete_report(self, _):
            raise RuntimeError("backend unavailable")

    monkeypatch.setattr(rag, "get_indexer", lambda: BrokenIndexer())
    assert (
        client.request("DELETE", url, json=body, headers=auth(client, "C1")).status_code
        == 503
    )
    assert client.get(url, headers=auth(client)).status_code == 200
    assert len(store.documents()) == 1
    monkeypatch.setattr(rag, "get_indexer", lambda: indexer)
    response = client.request("DELETE", url, json=body, headers=auth(client, "C1"))
    assert response.status_code == 200 and response.json()["removed_chunks"] == 1
    assert store.documents() == {}
    assert client.get(url, headers=auth(client)).status_code == 404
    assert db.get_reports().pending_index_reports(include_failed=True) == []
    assert create(client)["report_id"] != doc["report_id"]


def test_approved_scope_filters_before_limit_and_includes_own_reports(client):
    approved = create(client)
    for verb, actor in (("submit", "I1"), ("review", "L1"), ("approve", "C1")):
        approved = action(client, approved, verb, actor).json()
    draft = create(client, actor="L1")
    submitted = action(client, draft, "submit", "L1").json()
    for actor in ("I1", "L1", "C1"):
        response = client.get(
            "/reports?scope=approved&limit=1", headers=auth(client, actor)
        )
        assert response.status_code == 200
        assert [report["report_id"] for report in response.json()] == [
            approved["report_id"]
        ]
    assert [
        report["report_id"]
        for report in client.get(
            "/reports?scope=mine", headers=auth(client, "L1")
        ).json()
    ] == [draft["report_id"]]
    assert [
        report["report_id"]
        for report in client.get(
            "/reports?scope=review", headers=auth(client, "C1")
        ).json()
    ] == [submitted["report_id"]]
    assert client.get("/reports?scope=review", headers=auth(client, "L1")).json() == []
    assert (
        client.get("/reports?scope=review", headers=auth(client, "I1")).status_code
        == 403
    )


def test_review_history_tracks_own_decisions_and_current_status(client):
    endpoint = "/reports/review-history"
    assert client.get(endpoint).status_code == 401
    assert client.get(endpoint, headers=auth(client, "I1")).status_code == 403
    assert client.get(endpoint, headers=auth(client, "L2")).json() == []

    doc = create(client)
    submitted = action(client, doc, "submit").json()
    reviewed = action(client, submitted, "review", "L1").json()
    rejected = action(client, reviewed, "reject", "C1", comment="시험 결과 보완").json()

    lead_history = client.get(endpoint, headers=auth(client, "L1")).json()
    control_history = client.get(endpoint, headers=auth(client, "C1")).json()
    assert len(lead_history) == len(control_history) == 1
    assert (lead_history[0]["decision"], lead_history[0]["review_version"]) == (
        "승인",
        1,
    )
    assert (control_history[0]["decision"], control_history[0]["review_version"]) == (
        "반려",
        1,
    )
    assert lead_history[0]["report"]["report_status"] == "REJECTED"
    assert lead_history[0]["report"]["report_version"] == 1
    assert client.get(endpoint, headers=auth(client, "L2")).json() == []

    revised = action(client, rejected, "revise").json()
    history = client.get(endpoint, headers=auth(client, "L1")).json()
    assert history[0]["review_version"] == 1
    assert history[0]["report"]["report_version"] == 2
    assert history[0]["report"]["report_status"] == "DRAFT"
    old = client.get(
        f"/reports/{doc['report_id']}/versions/1", headers=auth(client, "L1")
    ).json()
    assert old["report_status"] == "REJECTED"
    assert old["approval"][-1]["comment"] == "시험 결과 보완"

    submitted = action(client, revised, "submit").json()
    second_rejection = action(client, submitted, "reject", "L1", comment="보완").json()
    history = client.get(endpoint, headers=auth(client, "L1")).json()
    assert [(item["review_version"], item["decision"]) for item in history] == [
        (2, "반려"),
    ]
    old = client.get(
        f"/reports/{doc['report_id']}/versions/1", headers=auth(client, "L1")
    ).json()
    assert any(
        item["user"] == "L1" and item["decision"] == "승인" for item in old["approval"]
    )
    assert all(item["report"]["report_status"] == "REJECTED" for item in history)
    assert (
        client.get(endpoint + "?limit=1", headers=auth(client, "L1")).json()[0][
            "review_version"
        ]
        == 2
    )
    assert second_rejection["report_status"] == "REJECTED"


def test_lead_submission_is_not_review_history_and_resubmission_can_be_pending(client):
    endpoint = "/reports/review-history"
    own = create(client, actor="L1")
    own = action(client, own, "submit", "L1").json()
    assert client.get(endpoint, headers=auth(client, "L1")).json() == []
    rejected = action(client, own, "reject", "C1", comment="보완").json()
    revised = action(client, rejected, "revise", "L1").json()
    resubmitted = action(client, revised, "submit", "L1").json()
    history = client.get(endpoint, headers=auth(client, "C1")).json()
    pending = client.get("/reports?scope=review", headers=auth(client, "C1")).json()
    assert [(item["review_version"], item["decision"]) for item in history] == [
        (1, "반려")
    ]
    assert history[0]["report"]["report_status"] == "REVIEWED"
    assert history[0]["report"]["report_version"] == 2
    assert [item["report_id"] for item in pending] == [resubmitted["report_id"]]


def test_review_history_limit_applies_after_grouping_reports(client):
    first = create(client)
    first = action(client, first, "submit").json()
    first = action(client, first, "reject", "L1", comment="첫 반려").json()
    second = create(client)
    second = action(client, second, "submit").json()
    second = action(client, second, "reject", "L1", comment="다른 보고서").json()
    revised = action(client, first, "revise").json()
    revised = action(client, revised, "submit").json()
    revised = action(client, revised, "reject", "L1", comment="두 번째 반려").json()

    history = client.get(
        "/reports/review-history?limit=2", headers=auth(client, "L1")
    ).json()
    assert [item["report"]["report_id"] for item in history] == [
        first["report_id"],
        second["report_id"],
    ]
    assert [(item["review_version"], item["decision"]) for item in history] == [
        (2, "반려"),
        (1, "반려"),
    ]
    assert revised["report_status"] == "REJECTED"
