"""센서 한 행의 수치·시간 패턴을 검사하고 이상 관측 목록을 반환한다.

입력은 시간 순서의 TelemetryRecord다. 0.5초 재생과 1초 CSV 모두 표본 수가
아닌 timestamp 차이로 계산한다. 출력은 list[AnomalyObservation]이며, 코드·등급
판정과 Incident 생성·갱신·회복은 이 파일에서 수행하지 않는다.
빈 구간에서 관측을 시작하고 입구·출구 신호는 누락 없이 전달된다고 가정한다.
RUN 상태에서는 별도의 동기화 호출 없이 FIFO 추적을 수행한다.

수치 검사는 BTT-RULE v2.0 4절 A 정상 범위 밖의 시점별 관측을 반환한다.
Warning/Error 지속시간 확정 및 운전 조건에 따른 사건 판단은 후속 처리 책임이다.
광전 검사는 6·7절의 FIFO, 14~16초 이송, 5초 주기 투입 간격(허용오차는 설정값), 점유 >3초를 사용한다.
이 초기 기준은 생성자에서 조정할 수 있으며 실제 설비에 맞춰 승인해야 한다.
"""

from collections.abc import Mapping
from datetime import datetime
from math import isfinite

from weeing_weeing.contracts import SensorEvidence, TelemetryRecord
from weeing_weeing.detector.detection_models import (
    DEFAULT_NUMERIC_RANGES,
    DetectionContext,
    NumericRange,
    _SensorState,
    _Tray,
)
from weeing_weeing.detector.observation import AnomalyObservation, CheckName


class AnomalyDetector:
    """센서 판정만 담당한다. 외부용 Detector(Incident 반환) 구현체와 구분한다."""

    def __init__(
        self,
        *,
        numeric_ranges: Mapping[str, NumericRange] | None = None,
        transfer_range_s: tuple[float, float] = (14.0, 16.0),
        infeed_interval_range_s: tuple[float, float] = (4.5, 5.5),
        occupancy_limit_s: float = 3.0,
        max_sample_gap_s: float = 2.0,
    ) -> None:
        """검사 기준을 설정한다. 빈 numeric_ranges={}는 수치 검사를 비활성화한다."""
        self.numeric_ranges = dict(
            DEFAULT_NUMERIC_RANGES if numeric_ranges is None else numeric_ranges
        )
        unknown = set(self.numeric_ranges) - DEFAULT_NUMERIC_RANGES.keys()
        if unknown:
            raise ValueError(f"수치 센서가 아닌 필드: {sorted(unknown)}")
        for lower, upper in (transfer_range_s, infeed_interval_range_s):
            if not (isfinite(lower) and isfinite(upper) and 0 <= lower <= upper):
                raise ValueError(
                    "시간 범위는 유한한 0 이상 수치로 하한 <= 상한이어야 함"
                )
        for value in (occupancy_limit_s, max_sample_gap_s):
            if not isfinite(value) or value <= 0:
                raise ValueError("점유 제한과 최대 표본 간격은 유한한 양수여야 함")
        self.transfer_range_s = transfer_range_s
        self.infeed_interval_range_s = infeed_interval_range_s
        self.occupancy_limit_s = occupancy_limit_s
        self.max_sample_gap_s = max_sample_gap_s
        self._states: dict[tuple[str, str], _SensorState] = {}

    def evaluate(
        self, record: TelemetryRecord, context: DetectionContext | None = None
    ) -> list[AnomalyObservation]:
        """한 행의 모든 검사를 독립 수행한다. 정상 또는 판정 불가만 있으면 [].

        같은 마지막 레코드의 재수신은 무시한다. 시간 역행·충돌은 추적을 끊고
        ValueError로 알린다. 이송 검사는 RUN 상태이면 자동으로 수행한다.
        """
        context = context or DetectionContext()
        key = (record.process_id, record.asset_id)
        state = self._states.setdefault(key, _SensorState())
        previous = state.previous
        if previous is not None:
            if record == previous:
                return []
            if (
                record.record_id == previous.record_id
                or record.timestamp <= previous.timestamp
            ):
                self._states[key] = _SensorState()
                raise ValueError("레코드 ID 충돌 또는 증가하지 않는 timestamp")
            gap_s = (record.timestamp - previous.timestamp).total_seconds()
            if gap_s > self.max_sample_gap_s:
                # 공백 동안 점유·엣지의 연속성을 알 수 없으므로 현재 행부터 재관측한다.
                state = self._states[key] = _SensorState()

        observations = self._check_numeric(record)
        observations.extend(self._check_photoelectric(record, state, context))
        state.previous = record
        return observations

    def _check_numeric(self, record: TelemetryRecord) -> list[AnomalyObservation]:
        """정상 범위를 벗어난 센서를 모두 반환한다. 결측·NaN·무한대는 제외한다."""

        observations = []
        for name, normal in self.numeric_ranges.items():
            value = getattr(record, name)
            # 없는 전류·온도를 0으로 채워 하한 이상으로 오판하지 않는다.
            if value is None or not isfinite(value):
                continue
            if value < normal.lower or value > normal.upper:
                criterion = f"x < {normal.lower} 또는 x > {normal.upper}"
                observations.append(
                    self._build_observation(
                        record=record,
                        check_name="numeric_range",
                        fields=[name],
                        description=f"{name}={value}: 정상 관측 범위 이탈",
                        criterion=criterion,
                        observed_value=value,
                        lower_bound=normal.lower,
                        upper_bound=normal.upper,
                        unit=normal.unit,
                    )
                )
        return observations

    def _check_photoelectric(
        self, record: TelemetryRecord, state: _SensorState, context: DetectionContext
    ) -> list[AnomalyObservation]:
        """상승·하강 엣지를 기록하고 점유·투입·이송 검사를 연결한다."""
        previous = state.previous
        rising: set[str] = set()
        for name in ("infeed_present", "outfeed_present"):
            present = getattr(record, name)
            was_present = getattr(previous, name) if previous is not None else None
            if present and was_present is not True:
                state.occupied_since[name] = record.timestamp
                # 최초 true는 관측 시작일 뿐, 새 트레이의 상승 엣지가 아니다.
                if was_present is False:
                    rising.add(name)
            elif not present:
                state.occupied_since.pop(name, None)
                if was_present is True:
                    state.last_falling[name] = record.timestamp

        observations = self._check_occupancy(record, state)
        if context.run_cmd is not True:
            state.pending.clear()
            state.last_rising.clear()
            return observations

        observations.extend(self._check_infeed_interval(record, state, rising))
        observations.extend(self._check_transfer(record, state, rising))
        # 엣지 간격 계산이 끝난 뒤 갱신해야 직전 상승 시각을 잃지 않는다.
        for name in rising:
            state.last_rising[name] = record.timestamp
        return observations

    def _check_occupancy(
        self, record: TelemetryRecord, state: _SensorState
    ) -> list[AnomalyObservation]:
        """입구·출구의 연속 true 시간을 각각 검사한다. 최초 점유는 관측 하한이다."""
        observations = []
        for name, check in (
            ("infeed_present", "infeed_occupancy"),
            ("outfeed_present", "outfeed_occupancy"),
        ):
            started_at = state.occupied_since.get(name)
            if started_at is None:
                continue
            elapsed = (record.timestamp - started_at).total_seconds()
            if elapsed > self.occupancy_limit_s:
                observations.append(
                    self._build_observation(
                        record=record,
                        check_name=check,
                        fields=[name],
                        description=f"{name}: 관측된 연속 점유 {elapsed:g}초 이상",
                        criterion=f"연속 true > {self.occupancy_limit_s:g}초",
                        observed_value=elapsed,
                        upper_bound=self.occupancy_limit_s,
                        unit="s",
                        started_at=started_at,
                    )
                )
        return observations

    def _check_infeed_interval(
        self,
        record: TelemetryRecord,
        state: _SensorState,
        rising: set[str],
    ) -> list[AnomalyObservation]:
        """운전 중에는 항상 완료된 투입 간격과 다음 투입 지연을 검사한다.

        호출부에서 RUN 여부를 확인한다. run_cmd가 False/None이면 상승 이력이
        초기화되므로 운전 재개 후 첫 상승 엣지부터 새 투입 간격을 계산한다.
        """
        started_at = state.last_rising.get("infeed_present")
        if started_at is None:
            return []
        elapsed = (record.timestamp - started_at).total_seconds()
        lower, upper = self.infeed_interval_range_s
        completed = "infeed_present" in rising
        if (completed and elapsed < lower) or elapsed > upper:
            return [
                self._build_observation(
                    record=record,
                    check_name="infeed_interval",
                    fields=["infeed_present"],
                    description=f"투입 간격 {elapsed:g}초"
                    if completed
                    else f"다음 투입 없이 {elapsed:g}초",
                    criterion=f"투입 간격 < {lower:g}초 또는 > {upper:g}초",
                    observed_value=elapsed,
                    lower_bound=lower,
                    upper_bound=upper,
                    unit="s",
                    started_at=started_at,
                )
            ]
        return []

    def _check_transfer(
        self,
        record: TelemetryRecord,
        state: _SensorState,
        rising: set[str],
    ) -> list[AnomalyObservation]:
        """진입 순서대로 반드시 나온다는 가정으로 FIFO 대응을 계속한다.

        지연 트레이도 가장 오래된 입구와 대응하고, 나머지 큐는 유지한다.
        같은 시각에는 출구를 시간 초과보다 먼저 처리한다.
        """
        observations = []
        lower, upper = self.transfer_range_s
        if "outfeed_present" in rising:
            if not state.pending:
                # 대응 입구가 없는 출구는 이상만 전달한다. 같은 행의 새 입구와
                # 이후 트레이도 계속 처리하므로 여기서 반환하거나 추적을 중단하지 않는다.
                observations.append(
                    self._build_observation(
                        record=record,
                        check_name="signal_pattern",
                        fields=["infeed_present", "outfeed_present"],
                        description="대응하는 입구 상승 엣지 없이 출구 상승 엣지 관측",
                        criterion="출구와 대응할 입구 이벤트가 FIFO에 있어야 함",
                    )
                )
            else:
                # 지연 여부와 무관하게 가장 오래된 트레이 하나만 꺼낸다.
                # 이후 입구 처리도 계속해 출구와 동시 발생한 새 트레이를 놓치지 않는다.
                tray = state.pending.popleft()
                elapsed = (record.timestamp - tray.entered_at).total_seconds()
                if elapsed < lower or elapsed > upper:
                    observations.append(
                        self._build_observation(
                            record=record,
                            check_name="transfer_time",
                            fields=["infeed_present", "outfeed_present"],
                            description=f"트레이 {tray.seq}: 관측된 FIFO 대응 이송시간 {elapsed:g}초",
                            criterion=f"이송시간 < {lower:g}초 또는 > {upper:g}초",
                            observed_value=elapsed,
                            lower_bound=lower,
                            upper_bound=upper,
                            unit="s",
                            started_at=tray.entered_at,
                            tray_seq=tray.seq,
                        )
                    )

        if "infeed_present" in rising:
            state.pending.append(_Tray(state.next_tray_seq, record.timestamp))
            state.next_tray_seq += 1

        for tray in state.pending:
            elapsed = (record.timestamp - tray.entered_at).total_seconds()
            if elapsed > upper:
                observations.append(
                    self._build_observation(
                        record=record,
                        check_name="transfer_time",
                        fields=["infeed_present", "outfeed_present"],
                        description=f"트레이 {tray.seq}: {elapsed:g}초 동안 출구 미도착",
                        criterion=f"이송시간 > {upper:g}초이고 대응 출구 없음",
                        observed_value=elapsed,
                        upper_bound=upper,
                        unit="s",
                        started_at=tray.entered_at,
                        tray_seq=tray.seq,
                    )
                )

        # 출구 무이벤트를 검사
        if state.pending:
            # 출구에 도착하지 않은 가장 오래된 트레이의 진입 시각과
            # 마지막 출구 감지 시각 중 늦은 쪽부터 출구 이벤트가 없는 시간을 계산한다.
            started_at = state.pending[0].entered_at
            last_outfeed = (
                record.timestamp
                if "outfeed_present" in rising
                else state.last_rising.get("outfeed_present")
            )
            if last_outfeed is not None:
                started_at = max(started_at, last_outfeed)
            elapsed = (record.timestamp - started_at).total_seconds()
            if elapsed > upper:
                observations.append(
                    self._build_observation(
                        record=record,
                        check_name="outfeed_missing",
                        fields=["infeed_present", "outfeed_present"],
                        description=f"아직 출구에 도착하지 않은 트레이가 있지만 출구 상승 엣지 없이 {elapsed:g}초",
                        criterion=f"운전 중 아직 출구에 도착하지 않은 트레이가 있고 출구 이벤트 없음 > {upper:g}초",
                        observed_value=elapsed,
                        upper_bound=upper,
                        unit="s",
                        started_at=started_at,
                        tray_seq=state.pending[0].seq,
                    )
                )
        return observations

    @staticmethod
    def _build_observation(
        *,
        record: TelemetryRecord,
        check_name: CheckName,
        fields: list[str],
        description: str,
        criterion: str,
        observed_value: float | bool | None = None,
        lower_bound: float | None = None,
        upper_bound: float | None = None,
        unit: str | None = None,
        started_at: datetime | None = None,
        tray_seq: int | None = None,
    ) -> AnomalyObservation:
        """공통 메타데이터와 원래 센서값을 붙여 이상 관측을 생성한다.

        모든 인자를 이름으로 받아 각 탐지 함수에서 값의 의미를 바로 읽을 수 있게 한다.
        """
        return AnomalyObservation(
            process_id=record.process_id,
            asset_id=record.asset_id,
            record_id=record.record_id,
            detected_at=record.timestamp,
            check_name=check_name,
            fields=fields,
            description=description,
            criterion=criterion,
            observed_value=observed_value,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            unit=unit,
            started_at=started_at,
            tray_seq=tray_seq,
            evidence=[
                SensorEvidence(
                    field=name,
                    value=getattr(record, name),
                    unit=unit if check_name == "numeric_range" else None,
                    threshold=criterion,
                    observed=description,
                )
                for name in fields
            ],
        )
