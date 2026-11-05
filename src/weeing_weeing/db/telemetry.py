"""센서 1초 데이터(telemetry) 저장·조회(#63).

같은 설비·같은 시각의 줄은 한 번만 저장한다(uq_telemetry_asset_time). 같은 CSV를 다시
재생하거나 송신기가 재전송해도 중복이 쌓이지 않고, 저장된 줄 수만 돌려준다.
"""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select

from weeing_weeing.contracts import TelemetryRecord
from weeing_weeing.contracts.telemetry import COLUMNS, TelemetryProvenance
from weeing_weeing.db.models import TelemetryRow
from weeing_weeing.db.session import Repository, utc

# SQLite는 문장 하나에 바인딩 변수 32766개까지. 15칼럼 × 500줄이면 넉넉하다.
BATCH = 500
KEY = ["asset_id", "timestamp", "process_id"]


def _values(
    record: TelemetryRecord, provenance: TelemetryProvenance | None = None
) -> dict:
    values = record.model_dump()
    values["timestamp"] = utc(record.timestamp)
    values["provenance"] = provenance.model_dump(mode="json") if provenance else None
    return values


def _record(row: TelemetryRow) -> TelemetryRecord:
    values = {name: getattr(row, name) for name in COLUMNS}
    values["timestamp"] = utc(values["timestamp"])
    return TelemetryRecord(**values)


class SqlTelemetry(Repository):
    def save_many(
        self,
        records: Iterable[TelemetryRecord],
        *,
        provenance: TelemetryProvenance | None = None,
    ) -> int:
        """여러 줄을 저장하고 새로 저장된 줄 수를 돌려준다. 이미 있는 시각은 건너뛴다."""
        rows = [_values(r, provenance) for r in records]
        saved = 0
        with self._transaction() as session:
            for start in range(0, len(rows), BATCH):
                statement = (
                    self._insert(TelemetryRow)
                    .values(rows[start : start + BATCH])
                    .on_conflict_do_nothing(index_elements=KEY)
                    # rowcount는 PostgreSQL 다중 행 INSERT에서 -1이 될 수 있어 RETURNING으로 센다.
                    .returning(TelemetryRow.id)
                )
                saved += len(session.execute(statement).all())
        return saved

    def between(
        self,
        asset_id: str,
        start: datetime,
        end: datetime,
        *,
        process_id: str | None = None,
        limit: int = 10_000,
    ) -> list[TelemetryRecord]:
        """[start, end) 구간을 시각순으로. 사건 전후 조회·HMI 그래프용."""
        return [
            record
            for record, _ in self.observations_between(
                asset_id,
                start,
                end,
                process_id=process_id,
                limit=limit,
            )
        ]

    def observations_between(
        self,
        asset_id,
        start,
        end,
        *,
        process_id=None,
        limit=10_000,
    ) -> list[tuple[TelemetryRecord, TelemetryProvenance | None]]:
        """원본과 같은 행의 출처를 함께 읽는다. 과거 행의 출처는 추측하지 않는다."""
        query = (
            select(TelemetryRow)
            .where(
                TelemetryRow.asset_id == asset_id,
                TelemetryRow.timestamp >= utc(start),
                TelemetryRow.timestamp < utc(end),
            )
            .order_by(TelemetryRow.timestamp)
            .limit(limit)
        )
        if process_id is not None:
            query = query.where(TelemetryRow.process_id == process_id)
        with self._transaction() as session:
            return [
                (
                    _record(row),
                    TelemetryProvenance.model_validate(row.provenance)
                    if row.provenance
                    else None,
                )
                for row in session.scalars(query)
            ]

    def latest(
        self, asset_id: str, *, process_id: str | None = None
    ) -> TelemetryRecord | None:
        """가장 최근 한 줄(HMI 현재값)."""
        query = (
            select(TelemetryRow)
            .where(TelemetryRow.asset_id == asset_id)
            .order_by(TelemetryRow.timestamp.desc())
            .limit(1)
        )
        if process_id is not None:
            query = query.where(TelemetryRow.process_id == process_id)
        with self._transaction() as session:
            row = session.scalars(query).first()
            return None if row is None else _record(row)
