"""Bounded telemetry cleanup while preserving all incident evidence windows."""

from datetime import datetime, timedelta

from sqlalchemy import delete, select, text

from weeing_weeing.db.models import IncidentRow, TelemetryRow
from weeing_weeing.db.session import Repository, utc

RETENTION = timedelta(minutes=3)
MARGIN = timedelta(seconds=30)
BATCH_SIZE = 1000


class TelemetryRetention(Repository):
    def clean_batch(self, now: datetime, after_id: int = 0) -> tuple[int, int]:
        """Return deleted count and cursor; a zero cursor completes one scan."""
        now = utc(now)
        with self._transaction() as session:
            if self._engine.dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            elif self._engine.dialect.name == "postgresql":
                if not session.scalar(
                    text("SELECT pg_try_advisory_xact_lock(981302104)")
                ):
                    return 0, after_id
                session.execute(text("SET LOCAL lock_timeout = '2s'"))
                # Prevent an incident from appearing between the evidence check and delete.
                session.execute(text("LOCK TABLE incident IN SHARE ROW EXCLUSIVE MODE"))
            rows = session.execute(
                select(
                    TelemetryRow.id,
                    TelemetryRow.timestamp,
                    TelemetryRow.process_id,
                    TelemetryRow.asset_id,
                )
                .where(
                    TelemetryRow.id > after_id, TelemetryRow.stored_at < now - RETENTION
                )
                .order_by(TelemetryRow.id)
                .limit(BATCH_SIZE)
            ).all()
            if not rows:
                return 0, 0
            pairs = {(row.process_id, row.asset_id) for row in rows}
            incidents = session.execute(
                select(
                    IncidentRow.process_id,
                    IncidentRow.asset_id,
                    IncidentRow.first_detected_at,
                    IncidentRow.recovered_at,
                ).where(
                    IncidentRow.process_id.in_({p for p, _ in pairs}),
                    IncidentRow.asset_id.in_({a for _, a in pairs}),
                )
            ).all()
            windows = {}
            for process, asset, start, end in incidents:
                windows.setdefault((process, asset), []).append(
                    (utc(start) - MARGIN, utc(end) + MARGIN if end else None)
                )
            removable = []
            for row in rows:
                sample_time = utc(row.timestamp)
                if not any(
                    start <= sample_time and (end is None or sample_time <= end)
                    for start, end in windows.get((row.process_id, row.asset_id), [])
                ):
                    removable.append(row.id)
            if removable:
                session.execute(
                    delete(TelemetryRow).where(TelemetryRow.id.in_(removable))
                )
            return len(removable), rows[-1].id
