from datetime import UTC, datetime, timedelta

from alembic import command
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from weeing_weeing.db.migrate import alembic_config, upgrade
from weeing_weeing.db.models import Base, IncidentRow, TelemetryRow
from weeing_weeing.db.retention import TelemetryRetention

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def sensor(id, seconds, *, age=240, asset="A", process="P"):
    return TelemetryRow(
        id=id,
        record_id=str(id),
        timestamp=NOW + timedelta(seconds=seconds),
        stored_at=NOW - timedelta(seconds=age),
        asset_id=asset,
        process_id=process,
        schema_version="3.0.0",
        infeed_present=False,
        outfeed_present=False,
        rpm=1000,
        dc_bus_voltage_v=24,
        de_vibration_rms_g=0.1,
        de_kurtosis=3,
        nde_vibration_rms_g=0.1,
        nde_kurtosis=3,
    )


def incident(id, start, end, asset="A"):
    return IncidentRow(
        incident_id=id,
        process_id="P",
        asset_id=asset,
        status="RECOVERED" if end else "OPEN",
        severity="Error",
        codes=[],
        first_detected_at=NOW + timedelta(seconds=start),
        last_detected_at=NOW,
        recovered_at=NOW + timedelta(seconds=end) if end is not None else None,
        rule_version="test",
        data={},
        updated_at=NOW,
    )


def test_retention_boundaries_open_incident_and_arrival_time():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                incident("closed", -100, -60),
                incident("open", -100, None, asset="B"),
                sensor(1, -131),
                sensor(2, -130),
                sensor(3, -30),
                sensor(4, -29),
                sensor(5, -200, age=179),
                sensor(6, 0, asset="B"),
                sensor(7, -130, asset="C"),
            ]
        )
        session.commit()
    deleted, cursor = TelemetryRetention(engine).clean_batch(NOW)
    assert deleted == 3
    assert cursor == 7
    with Session(engine) as session:
        assert session.scalars(
            select(TelemetryRow.id).order_by(TelemetryRow.id)
        ).all() == [2, 3, 5, 6]
    assert TelemetryRetention(engine).clean_batch(NOW, cursor) == (0, 0)


def test_existing_rows_receive_grace_period_during_migration(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.sqlite'}")
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0013")
        connection.exec_driver_sql(
            "INSERT INTO telemetry (record_id, timestamp, process_id, asset_id, schema_version, "
            "infeed_present, outfeed_present, rpm, dc_bus_voltage_v, de_vibration_rms_g, "
            "de_kurtosis, nde_vibration_rms_g, nde_kurtosis) "
            "VALUES ('old', '2020-01-01', 'P', 'A', '3.0.0', 0, 0, 1, 24, 0.1, 3, 0.1, 3)"
        )
    before = datetime.now(UTC) - timedelta(seconds=2)
    upgrade(engine)
    with Session(engine) as session:
        row = session.scalar(select(TelemetryRow))
        assert row.stored_at.replace(tzinfo=UTC) >= before
    assert TelemetryRetention(engine).clean_batch(datetime.now(UTC))[0] == 0


def test_batches_advance_past_protected_rows(monkeypatch):
    monkeypatch.setattr("weeing_weeing.db.retention.BATCH_SIZE", 2)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                incident("active", -200, None),
                sensor(1, -190),
                sensor(2, -180),
                sensor(3, -170),
                sensor(4, -300),
                sensor(5, -300, asset="other"),
            ]
        )
        session.commit()
    retention = TelemetryRetention(engine)
    assert retention.clean_batch(NOW) == (0, 2)
    assert retention.clean_batch(NOW, 2) == (1, 4)
    assert retention.clean_batch(NOW, 4) == (1, 5)
    assert retention.clean_batch(NOW, 5) == (0, 0)
