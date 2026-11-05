"""센서 조회 조립. Agent는 DB를 import하지 않는다 (#105)."""

from datetime import timedelta

from weeing_weeing.agent.interface import SensorBatch, SensorReader
from weeing_weeing.db.interface import TelemetryRepository


def sensor_reader(repository: TelemetryRepository) -> SensorReader:
    def read(incident, start, end, *, limit):
        # 최신 시각을 먼저 고정한다. 조회 중 들어온 미래 표본을 섞지 않는다.
        latest = repository.latest(incident.asset_id, process_id=incident.process_id)
        watermark = latest.timestamp if latest else None
        rows = (
            repository.observations_between(
                incident.asset_id,
                start,
                min(end, watermark + timedelta(microseconds=1)),
                process_id=incident.process_id,
                limit=limit,
            )
            if watermark is not None and watermark >= start
            else []
        )
        rows = [
            (record, source) for record, source in rows if record.timestamp <= watermark
        ]
        return SensorBatch(
            [record for record, _ in rows],
            watermark,
            {record.timestamp: source for record, source in rows if source is not None},
        )

    return read
