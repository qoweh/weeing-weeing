from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from weeing_weeing.api.app import app
from weeing_weeing.api.report_index import process_pending_reports
from weeing_weeing.contracts import (
    AnalysisResult,
    Incident,
    IncidentStatus,
    Role,
    Severity,
    TelemetryRecord,
    UserAccount,
)
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


def add_incident(incident_id):
    original = db.get_incidents().get_incident("INC-1")
    db.get_incidents().save_incident(
        Incident.model_validate(original.model_dump() | {"incident_id": incident_id})
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


def test_incident_report_context_returns_own_draft_and_matching_sensor(client):
    incident = db.get_incidents().get_incident("INC-1")
    timestamp = incident.first_detected_at
    record = TelemetryRecord(
        record_id="context-test",
        timestamp=timestamp,
        process_id="P1",
        asset_id="A1",
        schema_version="3.0.0",
        infeed_present=False,
        outfeed_present=True,
        rpm=1001,
        dc_input_current_a=0.1,
        dc_bus_voltage_v=24,
        motor_housing_temp_c=95,
        de_vibration_rms_g=0.06,
        de_kurtosis=4,
        nde_vibration_rms_g=0.05,
        nde_kurtosis=4,
    )
    db.get_telemetry().save_many(
        [
            record,
            record.model_copy(
                update={
                    "record_id": "future",
                    "timestamp": timestamp + timedelta(seconds=1),
                    "rpm": 2000,
                }
            ),
        ]
    )
    draft = create(client, "I1", form_data={})
    response = client.get("/incidents/INC-1/report-context", headers=auth(client, "I1"))
    assert response.status_code == 200
    assert response.json()["draft"]["report_id"] == draft["report_id"]
    assert response.json()["telemetry"]["rpm"] == 1001
    assert (
        client.get(
            "/incidents/INC-1/report-context", headers=auth(client, "I2")
        ).json()["draft"]
        is None
    )
    assert (
        client.get(
            "/incidents/INC-1/report-context", headers=auth(client, "C1")
        ).json()["draft"]
        is None
    )
    assert client.get("/incidents/INC-1/report-context").status_code == 401
    assert (
        client.get(
            "/incidents/missing/report-context", headers=auth(client)
        ).status_code
        == 404
    )


def test_report_context_uses_error_input_not_warning_or_recovered_values(
    client, sample_rows
):
    original = db.get_incidents().get_incident("INC-1")
    start = original.first_detected_at
    warning = original.model_copy(
        update={
            "codes": ["BTT2-M08"],
            "severity": Severity.WARNING,
            "confirmed_at": start,
        }
    )
    frame = TelemetryRecord.model_validate(sample_rows[0]).model_copy(
        update={
            "record_id": "warning",
            "process_id": "P1",
            "asset_id": "A1",
            "timestamp": start,
            "dc_bus_voltage_v": 25.7,
        }
    )
    jobs = db.get_analysis_jobs()
    jobs.record_frame(frame, [warning])
    error_time = start + timedelta(seconds=25)
    error_frame = frame.model_copy(
        update={
            "record_id": "error",
            "timestamp": error_time,
            "dc_bus_voltage_v": 27.603,
            "rpm": 0.0,
            "infeed_present": False,
            "outfeed_present": True,
        }
    )
    error = warning.model_copy(
        update={"severity": Severity.ERROR, "last_detected_at": error_time}
    )
    jobs.record_frame(error_frame, [error])
    job_id, snapshot = jobs.claim()
    analysis = AnalysisResult(
        incident_id="INC-1",
        status="INSUFFICIENT_EVIDENCE",
        observed_facts="가짜 분석: API 호출 없음",
        model="fake/no-api",
        generated_at=error_time + timedelta(seconds=1),
    )
    jobs.finish(job_id, analysis)
    draft = create(client, "I1", form_data={})
    recovered = error.model_copy(
        update={
            "status": IncidentStatus.RECOVERED,
            "last_detected_at": start + timedelta(seconds=60),
        }
    )
    jobs.record_frame(
        frame.model_copy(
            update={
                "record_id": "recovered",
                "timestamp": recovered.last_detected_at,
                "dc_bus_voltage_v": 24.0,
            }
        ),
        [recovered],
    )
    db.get_telemetry().save_many(
        [
            error_frame.model_copy(
                update={
                    "record_id": "wrong-process",
                    "process_id": "OTHER",
                    "dc_bus_voltage_v": 999.0,
                }
            ),
            error_frame.model_copy(
                update={
                    "record_id": "future",
                    "timestamp": error_time + timedelta(seconds=0.5),
                    "dc_bus_voltage_v": 888.0,
                }
            ),
        ]
    )
    response = client.get(
        f"/incidents/INC-1/report-context?report_id={draft['report_id']}",
        headers=auth(client),
    )
    assert response.status_code == 200
    context = response.json()
    assert context["incident"]["status"] == "RECOVERED"
    assert context["analysis_incident"] == snapshot.model_dump(mode="json")
    assert context["analysis"] == analysis.model_dump(mode="json")
    assert context["document"]["revision"] == draft["revision"]
    assert context["document"]["ai_analysis"] == context["analysis"]
    assert context["telemetry"]["record_id"] == "error"
    assert context["telemetry"]["dc_bus_voltage_v"] == 27.603
    assert (
        context["telemetry"]["rpm"] == 0
        and context["telemetry"]["infeed_present"] is False
    )
    assert context["telemetry_notes"] == []
    db.get_incidents().save_analysis(
        analysis.model_copy(
            update={
                "observed_facts": "나중에 저장된 다른 분석",
                "generated_at": analysis.generated_at + timedelta(seconds=60),
            }
        )
    )
    old_report_context = client.get(
        f"/incidents/INC-1/report-context?report_id={draft['report_id']}",
        headers=auth(client),
    ).json()
    assert old_report_context["analysis"] == analysis.model_dump(mode="json")
    assert old_report_context["telemetry"]["record_id"] == "error"
    assert (
        client.get(
            f"/incidents/INC-1/report-context?report_id={draft['report_id']}",
            headers=auth(client, "I2"),
        ).status_code
        == 200
    )
    add_incident("INC-other")
    assert (
        client.get(
            f"/incidents/INC-other/report-context?report_id={draft['report_id']}",
            headers=auth(client),
        ).status_code
        == 409
    )


def test_report_context_does_not_invent_input_for_legacy_analysis(client):
    db.get_incidents().save_analysis(
        AnalysisResult(
            incident_id="INC-1",
            status="INSUFFICIENT_EVIDENCE",
            observed_facts="스냅샷 없는 과거 분석",
            model="fake/no-api",
            generated_at=datetime.now(timezone.utc),
        )
    )
    context = client.get("/incidents/INC-1/report-context", headers=auth(client)).json()
    assert context["analysis_incident"] is None
    assert context["telemetry"] is None
    assert context["telemetry_anchor"] is None
    assert "입력 스냅샷" in context["telemetry_notes"][0]


def test_incident_overview_separates_recovery_from_report_approval(client):
    headers = auth(client)
    incident = db.get_incidents().get_incident("INC-1")
    recovered = Incident.model_validate(
        incident.model_dump()
        | {"status": "RECOVERED", "recovered_at": incident.first_detected_at}
    )
    db.get_incidents().save_incident(recovered)
    warning = Incident.model_validate(
        incident.model_dump()
        | {"incident_id": "INC-warning", "codes": ["BTT2-D05"], "severity": "Warning"}
    )
    db.get_incidents().save_incident(warning)

    def overview():
        response = client.get("/incidents/overview", headers=headers)
        assert response.status_code == 200
        return response.json()

    assert client.get("/incidents/overview").status_code == 401
    initial = overview()
    assert len(initial) == 1
    assert initial[0]["incident"]["status"] == "RECOVERED"
    assert initial[0]["has_approved_report"] is False
    report = create(client)
    for verb, actor in (("submit", "I1"), ("review", "L1")):
        response = action(client, report, verb, actor)
        assert response.status_code == 200
        report = response.json()
        assert overview()[0]["has_approved_report"] is False
    response = action(client, report, "approve", "C1")
    assert response.status_code == 200
    assert overview()[0]["has_approved_report"] is True
    assert overview()[0]["incident"]["status"] == "RECOVERED"
    approved = response.json()
    db.get_reports().delete_approved(
        "C1",
        approved["report_id"],
        expected_revision=approved["revision"],
        delete_vector=lambda _: 0,
    )
    assert overview()[0]["has_approved_report"] is False


def test_incident_overview_keeps_previous_error_when_severity_decreases(client):
    incident = db.get_incidents().get_incident("INC-1")
    sample = TelemetryRecord(
        record_id="severity-test",
        timestamp=incident.first_detected_at,
        process_id=incident.process_id,
        asset_id=incident.asset_id,
        schema_version="3.0.0",
        infeed_present=False,
        outfeed_present=False,
        rpm=1015,
        dc_input_current_a=0.09,
        dc_bus_voltage_v=24,
        motor_housing_temp_c=95,
        de_vibration_rms_g=0.06,
        de_kurtosis=5,
        nde_vibration_rms_g=0.055,
        nde_kurtosis=4.5,
    )
    db.get_analysis_jobs().record_frame(sample, [incident])
    downgraded = Incident.model_validate(
        incident.model_dump() | {"severity": "Warning"}
    )
    db.get_incidents().save_incident(downgraded)
    result = client.get("/incidents/overview", headers=auth(client)).json()
    assert len(result) == 1
    assert result[0]["incident"]["severity"] == "Warning"
    assert result[0]["has_approved_report"] is False


def test_incident_overview_reports_each_approval_stage(client):
    headers = auth(client)

    def overview():
        return client.get("/incidents/overview", headers=headers).json()[0]

    assert overview()["report_status"] is None
    assert overview()["report_id"] is None
    report = create(client)
    assert overview()["report_status"] == "DRAFT"
    assert overview()["report_id"] == report["report_id"]
    report = action(client, report, "submit").json()
    assert overview()["report_status"] == "SUBMITTED"
    report = action(client, report, "reject", "L1", comment="보완 필요").json()
    assert overview()["report_status"] == "REJECTED"
    report = action(client, report, "revise").json()
    assert overview()["report_status"] == "DRAFT"
    report = action(client, report, "submit").json()
    report = action(client, report, "review", "L1").json()
    assert overview()["report_status"] == "REVIEWED"
    report = action(client, report, "approve", "C1").json()
    assert report["report_status"] == "APPROVED"
    assert overview()["report_status"] == "APPROVED"


def test_duplicate_report_rejected_for_other_author_until_draft_deleted(client):
    first = create(client)
    duplicate = client.post(
        "/reports",
        headers=auth(client, "L1"),
        json={"incident_id": "INC-1", "form_data": {}},
    )
    assert duplicate.status_code == 409
    assert "이미 보고서" in duplicate.json()["detail"]
    deleted = client.request(
        "DELETE",
        f"/reports/{first['report_id']}/draft",
        headers=auth(client),
        json={"expected_revision": first["revision"]},
    )
    assert deleted.status_code == 200
    assert create(client, "L1")["incident_id"] == "INC-1"


def test_delete_incident_removes_linked_data_and_prevents_recreation(
    client, monkeypatch, sample_rows
):
    from weeing_weeing.rag import interface as rag

    incident = db.get_incidents().get_incident("INC-1")
    frame = TelemetryRecord.model_validate(sample_rows[0]).model_copy(
        update={
            "record_id": "delete-test",
            "timestamp": incident.first_detected_at,
            "process_id": incident.process_id,
            "asset_id": incident.asset_id,
        }
    )
    jobs = db.get_analysis_jobs().record_frame(frame, [incident])
    assert len(jobs) == 1
    claimed = db.get_analysis_jobs().claim()
    assert claimed is not None
    path = "/incidents/INC-1"
    assert client.delete(path).status_code == 401
    assert client.delete(path, headers=auth(client, "I1")).status_code == 403
    db.get_users().create_user(
        UserAccount(
            employee_no="S1", name="관리자", role=Role.SITE_MANAGER, is_admin=True
        ),
        PASSWORD,
    )
    assert client.delete(path, headers=auth(client, "S1")).status_code == 403
    assert client.delete(path, headers=auth(client, "C1")).status_code == 409
    result = AnalysisResult(
        incident_id="INC-1",
        status="INSUFFICIENT_EVIDENCE",
        observed_facts="test",
        model="fake",
        generated_at=datetime.now(timezone.utc),
    )
    db.get_analysis_jobs().finish(claimed[0], result)
    report = create(client)
    for verb, actor in (("submit", "I1"), ("review", "L1"), ("approve", "C1")):
        report = action(client, report, verb, actor).json()

    class BrokenIndexer:
        def delete_report(self, _report_id):
            raise RuntimeError("vector unavailable")

    monkeypatch.setattr(rag, "get_indexer", lambda: BrokenIndexer())
    assert client.delete(path, headers=auth(client, "C1")).status_code == 503
    assert db.get_incidents().get_incident("INC-1") is not None
    assert (
        client.get(f"/reports/{report['report_id']}", headers=auth(client)).status_code
        == 200
    )

    deleted_ids = []

    class Indexer:
        def delete_report(self, report_id):
            deleted_ids.append(report_id)
            return 1

    monkeypatch.setattr(rag, "get_indexer", lambda: Indexer())
    response = client.delete(path, headers=auth(client, "C1"))
    assert response.status_code == 200
    assert response.json() == {
        "status": "deleted",
        "deleted_reports": 1,
        "removed_chunks": 1,
    }
    assert deleted_ids == [report["report_id"]]
    assert (
        client.get(f"/reports/{report['report_id']}", headers=auth(client)).status_code
        == 404
    )
    assert db.get_analysis_jobs().latest_job("INC-1") is None
    assert db.get_analysis_jobs().latest_analysis("INC-1") is None
    assert db.get_incidents().get_incident("INC-1") is None
    assert db.get_analysis_jobs().record_frame(frame, [incident]) == []
    assert db.get_incidents().get_incident("INC-1") is None
    with pytest.raises(db.UnknownIncidentError):
        db.get_incidents().save_incident(incident)
    assert db.get_telemetry().between(
        "A1", frame.timestamp, frame.timestamp + timedelta(seconds=1), process_id="P1"
    )
    assert client.delete(path, headers=auth(client, "C1")).status_code == 404


def test_incident_without_report_can_be_deleted_without_vector_connection(
    client, monkeypatch
):
    from weeing_weeing.rag import interface as rag

    def unavailable():
        raise AssertionError("벡터 저장소를 불필요하게 열면 안 됩니다")

    monkeypatch.setattr(rag, "get_indexer", unavailable)
    response = client.delete("/incidents/INC-1", headers=auth(client, "C1"))
    assert response.status_code == 200
    assert response.json() == {
        "status": "deleted",
        "deleted_reports": 0,
        "removed_chunks": 0,
    }


def test_delete_incident_removes_actual_qdrant_report_and_handles_legacy_duplicates(
    client, monkeypatch
):
    from qdrant_client import QdrantClient
    from sqlalchemy import update

    from weeing_weeing.db.models import ReportRow
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
    approved = create(client)
    for verb, actor in (("submit", "I1"), ("review", "L1"), ("approve", "C1")):
        approved = action(client, approved, verb, actor).json()
    assert process_pending_reports(db.get_reports(), lambda: indexer).indexed == 1
    assert len(store.documents()) == 1

    # 이전 정책에서 같은 사건에 여러 보고서가 만들어진 DB를 보존해 검증한다.
    add_incident("INC-2")
    legacy = create(client, "L1", incident_id="INC-2")
    with db.get_reports()._transaction() as session:
        session.execute(
            update(ReportRow)
            .where(ReportRow.report_id == legacy["report_id"])
            .values(incident_id="INC-1")
        )
    result = client.delete("/incidents/INC-1", headers=auth(client, "C1"))
    assert result.status_code == 200
    assert result.json()["deleted_reports"] == 2
    assert store.documents() == {}
    for report_id in (approved["report_id"], legacy["report_id"]):
        assert (
            client.get(f"/reports/{report_id}", headers=auth(client)).status_code == 404
        )
    assert db.get_incidents().get_incident("INC-2") is not None
    vector_client.close()


def test_incident_approved_reports_excludes_drafts(client):
    path = "/incidents/INC-1/approved-reports"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=auth(client, "I2")).json() == []
    first = create(client, "I1")
    assert client.get(path, headers=auth(client, "I2")).json() == []
    for verb, actor in (("submit", "I1"), ("review", "L1"), ("approve", "C1")):
        response = action(client, first, verb, actor)
        assert response.status_code == 200
        first = response.json()
    result = client.get(path, headers=auth(client, "I2")).json()
    assert [(item["report_id"], item["report_version"]) for item in result] == [
        (first["report_id"], 1)
    ]
    assert (
        client.get(
            "/incidents/missing/approved-reports", headers=auth(client)
        ).status_code
        == 404
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
    add_incident("INC-2")
    other = create(client, incident_id="INC-2")
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

    add_incident("INC-2")
    other = create(client, incident_id="INC-2")
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
    assert create(client, incident_id="INC-2")["report_id"] != other["report_id"]


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
    add_incident("INC-2")
    draft = create(client, actor="L1", incident_id="INC-2")
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
    add_incident("INC-2")
    second = create(client, incident_id="INC-2")
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
