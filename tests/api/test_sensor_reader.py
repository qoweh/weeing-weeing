"""실제 SQLite 조회로 공정·설비·종료 경계 격리를 확인한다."""

from datetime import timedelta
from types import SimpleNamespace

from weeing_weeing.agent import interface as agent
from weeing_weeing.api import analysis
from weeing_weeing.api.sensor_window import sensor_reader
from weeing_weeing.contracts import Incident, TelemetryRecord
from weeing_weeing.db import interface as db


def test_reader_scopes_process_asset_and_half_open_time(tmp_path, sample_rows):
    repo = db.open_telemetry(f"sqlite:///{tmp_path / 'sensor.db'}")
    row = TelemetryRecord.model_validate(sample_rows[0])
    incident = Incident(
        incident_id="test",
        asset_id=row.asset_id,
        process_id=row.process_id,
        codes=["BTT2-P03"],
        severity="Error",
        first_detected_at=row.timestamp,
        last_detected_at=row.timestamp,
    )
    other = row.model_copy(update={"process_id": "another"})
    other_asset = row.model_copy(update={"asset_id": "another"})
    later = row.model_copy(update={"timestamp": row.timestamp + timedelta(seconds=1)})
    try:
        repo.save_many([row, other, other_asset, later])
        batch = sensor_reader(repo)(incident, row.timestamp, later.timestamp, limit=2)
        assert batch.records == [row]
        assert batch.available_through == later.timestamp
        empty = incident.model_copy(update={"asset_id": "absent"})
        batch = sensor_reader(repo)(empty, row.timestamp, later.timestamp, limit=2)
        assert batch.records == [] and batch.available_through is None
    finally:
        repo._engine.dispose()


def test_default_worker_injects_sensor_tool_and_saves_verified_result(
    tmp_path, sample_rows, monkeypatch
):
    url = f"sqlite:///{tmp_path / 'analysis-sensor.db'}"
    jobs = db.open_analysis_jobs(url)
    sensors = db.open_telemetry(url)
    row = TelemetryRecord.model_validate(sample_rows[0])
    item = Incident(
        incident_id="INC-sensor-integration",
        asset_id=row.asset_id,
        process_id=row.process_id,
        codes=["BTT2-P03"],
        severity="Error",
        first_detected_at=row.timestamp,
        last_detected_at=row.timestamp,
    )

    class FakeLlm:
        provider, model_name, last_usage = "fake", "sensor-integration", None

        def __init__(self):
            self.turn = 0

        def create(self, **kwargs):
            self.turn += 1
            if self.turn == 1:
                assert "get_sensor_window" in [tool["name"] for tool in kwargs["tools"]]
                name = "get_sensor_window"
                data = {"before_seconds": 0, "after_seconds": 0, "fields": ["rpm"]}
            else:
                name = "submit_analysis"
                data = {
                    "observed_facts": "임의 숫자 999999",
                    "suspected_causes": [],
                    "status": "INSUFFICIENT_EVIDENCE",
                    "sensor_claims": [
                        {
                            "window_id": "window-1",
                            "field": "rpm",
                            "statistic": "mean",
                            "value": row.rpm,
                        }
                    ],
                }
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use", id=str(self.turn), name=name, input=data
                    )
                ],
                stop_reason="tool_use",
            )

    monkeypatch.setattr(analysis, "get_retriever", lambda: object())
    monkeypatch.setattr(db, "get_telemetry", lambda: sensors)
    monkeypatch.setattr(agent, "get_llm_client", lambda settings, **kwargs: FakeLlm())
    try:
        worker = analysis.AnalysisService(repository=lambda: jobs)
        worker.ingest(row, [item])
        assert worker.process_one()
        job = jobs.latest_job(item.incident_id)
        assert job["status"] == "COMPLETED"
        result = jobs.latest_analysis(item.incident_id)
        assert result.prompt_version == "incident-analyst-v3"
        assert f"rpm.mean={row.rpm}" in result.observed_facts
        assert "999999" not in result.observed_facts
    finally:
        sensors._engine.dispose()
        jobs._engine.dispose()


def test_latest_watermark_clips_query_before_concurrent_new_samples(sample_rows):
    row = TelemetryRecord.model_validate(sample_rows[0])
    incident = Incident(
        incident_id="clip",
        asset_id=row.asset_id,
        process_id=row.process_id,
        codes=["BTT2-P03"],
        severity="Error",
        first_detected_at=row.timestamp,
        last_detected_at=row.timestamp,
    )
    calls = []

    class Repository:
        def latest(self, asset_id, *, process_id):
            assert asset_id == incident.asset_id and process_id == incident.process_id
            return row

        def observations_between(self, asset_id, start, end, *, process_id, limit):
            calls.append((start, end, limit))
            return [(row, None)]

    sensor_reader(Repository())(
        incident, row.timestamp, row.timestamp + timedelta(seconds=30), limit=513
    )
    assert calls == [(row.timestamp, row.timestamp + timedelta(microseconds=1), 513)]
