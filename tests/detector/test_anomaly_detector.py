"""수치 경계와 광전 이벤트의 시간·FIFO 동작을 검증한다."""

from datetime import datetime, timedelta, timezone

import pytest

from weeing_weeing.contracts import SCHEMA_VERSION, TelemetryRecord
from weeing_weeing.detector.anomaly_detector import AnomalyDetector
from weeing_weeing.detector.detection_models import (
    DEFAULT_NUMERIC_RANGES,
    DetectionContext,
    NumericRange,
)

T0 = datetime(2026, 10, 5, tzinfo=timezone.utc)
RUN = DetectionContext(run_cmd=True)


def record(second, *, infeed=False, outfeed=False, asset="motor-1", **values):
    """기본 센서값은 모두 정상 중앙값이며, 개별 테스트에서 필요한 값만 바꾼다."""
    data = {
        name: (normal.lower + normal.upper) / 2
        for name, normal in DEFAULT_NUMERIC_RANGES.items()
    }
    data.update(values)
    return TelemetryRecord(
        record_id=f"{asset}-{second}",
        timestamp=T0 + timedelta(seconds=second),
        process_id="process-1",
        asset_id=asset,
        schema_version=SCHEMA_VERSION,
        infeed_present=infeed,
        outfeed_present=outfeed,
        **data,
    )


def started_detector(**options):
    detector = AnomalyDetector(numeric_ranges={}, **options)
    detector.evaluate(record(0), RUN)
    return detector


def test_simultaneous_numeric_anomalies_and_evidence():
    detector = AnomalyDetector()
    results = detector.evaluate(record(0, rpm=990, dc_bus_voltage_v=27))
    assert [item.fields for item in results] == [["rpm"], ["dc_bus_voltage_v"]]
    assert results[0].observed_value == 990
    assert results[0].evidence[0].value == 990
    assert all(item.record_id == "motor-1-0" for item in results)


@pytest.mark.parametrize("name", DEFAULT_NUMERIC_RANGES)
def test_numeric_normal_boundaries_are_inclusive(name):
    detector = AnomalyDetector()
    normal = DEFAULT_NUMERIC_RANGES[name]
    assert detector.evaluate(record(0, **{name: normal.lower})) == []
    assert detector.evaluate(record(1, **{name: normal.upper})) == []


def test_missing_and_nonfinite_values_are_not_zero_or_anomalies():
    detector = AnomalyDetector()
    assert (
        detector.evaluate(
            record(
                0, dc_input_current_a=None, motor_housing_temp_c=None, rpm=float("nan")
            )
        )
        == []
    )
    assert detector.evaluate(record(1, rpm=float("inf"))) == []


def test_occupancy_uses_elapsed_seconds_and_both_sensors():
    detector = AnomalyDetector(numeric_ranges={})
    for tick in range(7):
        assert detector.evaluate(record(tick / 2, infeed=True, outfeed=True)) == []
    results = detector.evaluate(record(3.5, infeed=True, outfeed=True))
    assert {item.check_name for item in results} == {
        "infeed_occupancy",
        "outfeed_occupancy",
    }
    assert all(item.observed_value == 3.5 for item in results)
    assert detector.evaluate(record(4)) == []
    assert detector.evaluate(record(4.5, infeed=True)) == []


def test_initial_true_is_only_an_occupancy_baseline():
    detector = AnomalyDetector(numeric_ranges={})
    for second in range(21):
        results = detector.evaluate(record(second, infeed=second == 0), RUN)
        assert not any(item.check_name == "transfer_time" for item in results)


@pytest.mark.parametrize("elapsed", [14, 15, 16])
def test_transfer_boundaries_and_multiple_fifo_trays(elapsed):
    detector = started_detector()
    results = []
    # 5초 간격 세 트레이와 입구·출구 동시 상승을 포함한다.
    for second in range(1, elapsed + 12):
        results.extend(
            detector.evaluate(
                record(
                    second,
                    infeed=second in {1, 6, 11, elapsed + 1},
                    outfeed=second in {elapsed + 1, elapsed + 6, elapsed + 11},
                ),
                RUN,
            )
        )
    assert not any(
        item.check_name in {"transfer_time", "signal_pattern", "outfeed_missing"}
        for item in results
    )


def test_fast_transfer_has_fifo_sequence():
    detector = started_detector()
    results = []
    for second in range(1, 15):
        results.extend(
            detector.evaluate(
                record(second, infeed=second == 1, outfeed=second == 14), RUN
            )
        )
    transfers = [item for item in results if item.check_name == "transfer_time"]
    assert len(transfers) == 1
    assert transfers[0].observed_value == 13
    assert transfers[0].tray_seq == 1


def test_late_exits_preserve_fifo_and_simultaneous_new_infeed():
    detector = started_detector()
    for second in range(1, 18):
        results = detector.evaluate(record(second, infeed=second in {1, 6}), RUN)
        assert not any(item.check_name == "transfer_time" for item in results)
    results = detector.evaluate(record(18), RUN)
    assert {item.check_name for item in results} >= {"transfer_time", "outfeed_missing"}
    assert all(
        item.tray_seq == 1 for item in results if item.check_name == "transfer_time"
    )

    # A는 t19에 지연 도착하며, 같은 시각의 신규 진입 C도 큐에 등록되어야 한다.
    results = detector.evaluate(record(19, infeed=True, outfeed=True), RUN)
    transfers = [item for item in results if item.check_name == "transfer_time"]
    assert [(item.tray_seq, item.observed_value) for item in transfers] == [(1, 18)]

    # 추가 호출 없이 B와 C의 출구가 각각 FIFO 순번 2, 3과 대응하는지 확인한다.
    exits = []
    for second in range(20, 33):
        results = detector.evaluate(record(second, outfeed=second in {24, 32}), RUN)
        if second in {24, 32}:
            exits.extend(item for item in results if item.check_name == "transfer_time")
        assert not any(item.check_name == "signal_pattern" for item in results)
    assert [(item.tray_seq, item.observed_value) for item in exits] == [
        (2, 18),
        (3, 13),
    ]
    assert exits[0].started_at == T0 + timedelta(seconds=6)
    assert exits[1].started_at == T0 + timedelta(seconds=19)

    # 모든 트레이가 빠진 뒤에는 기존 트레이의 시간 초과를 다시 보고하지 않는다.
    for second in range(33, 40):
        results = detector.evaluate(record(second), RUN)
        assert not any(
            item.check_name in {"transfer_time", "outfeed_missing"} for item in results
        )


def test_unmatched_exit_reports_pattern_without_assigning_error_code():
    detector = started_detector()
    results = detector.evaluate(record(1, outfeed=True), RUN)
    assert [item.check_name for item in results] == ["signal_pattern"]
    assert len(results[0].evidence) == 2
    assert "code" not in results[0].model_dump()


def test_interval_checks_completed_and_missing_next_edges():
    detector = AnomalyDetector(numeric_ranges={})
    detector.evaluate(record(0), RUN)
    for second in range(1, 4):
        results = detector.evaluate(record(second, infeed=second in {1, 3}), RUN)
    assert any(
        item.check_name == "infeed_interval" and item.observed_value == 2
        for item in results
    )
    for second in range(4, 11):
        results = detector.evaluate(record(second), RUN)
    assert any(
        item.check_name == "infeed_interval" and item.observed_value == 7
        for item in results
    )


@pytest.mark.parametrize("run_cmd", [False, None])
def test_nonrunning_context_skips_interval_check(run_cmd):
    detector = AnomalyDetector(numeric_ranges={})
    context = DetectionContext(run_cmd=run_cmd)
    for second in range(15):
        assert detector.evaluate(record(second, infeed=second == 1), context) == []


def test_running_context_always_checks_missing_next_infeed():
    detector = AnomalyDetector(numeric_ranges={})
    detector.evaluate(record(0), RUN)
    for second in range(1, 7):
        results = detector.evaluate(record(second, infeed=second == 1), RUN)
        assert not any(item.check_name == "infeed_interval" for item in results)
    results = detector.evaluate(record(7), RUN)
    assert any(
        item.check_name == "infeed_interval" and item.observed_value == 6
        for item in results
    )


@pytest.mark.parametrize("interval", [4.5, 5.0, 5.5])
def test_existing_infeed_tolerance_remains_normal(interval):
    detector = AnomalyDetector(numeric_ranges={})
    detector.evaluate(record(0), RUN)
    for tick in range(1, int((1 + interval) * 2) + 1):
        second = tick / 2
        results = detector.evaluate(
            record(second, infeed=second in {1, 1 + interval}), RUN
        )
        assert not any(item.check_name == "infeed_interval" for item in results)


def test_interval_restarts_after_run_command_is_stopped():
    detector = AnomalyDetector(numeric_ranges={})
    detector.evaluate(record(0), RUN)
    detector.evaluate(record(1, infeed=True), RUN)
    for second in range(2, 10):
        detector.evaluate(record(second), DetectionContext(run_cmd=False))
    assert detector.evaluate(record(10, infeed=True), RUN) == []
    for second in range(11, 16):
        results = detector.evaluate(record(second, infeed=second == 15), RUN)
        assert not any(item.check_name == "infeed_interval" for item in results)


def test_sample_gap_restarts_occupancy_measurement():
    detector = started_detector()
    for second in range(1, 6):
        results = detector.evaluate(record(second, infeed=True), RUN)
    occupied = next(item for item in results if item.check_name == "infeed_occupancy")
    assert occupied.observed_value == 4
    # 표본 공백을 넘어선 연속 점유는 추정하지 않고 현재 시각부터 다시 관측한다.
    for second in range(10, 14):
        results = detector.evaluate(record(second, infeed=True), RUN)
        assert not any(item.check_name == "infeed_occupancy" for item in results)
    results = detector.evaluate(record(14, infeed=True), RUN)
    occupied = next(item for item in results if item.check_name == "infeed_occupancy")
    assert occupied.started_at == T0 + timedelta(seconds=10)
    assert occupied.observed_value == 4


def test_continuous_run_preserves_occupancy_interval_and_fifo_timers():
    detector = started_detector()
    for second in range(1, 19):
        results = detector.evaluate(
            record(second, infeed=True), DetectionContext(run_cmd=True)
        )
    # 장기 점유 중에도 입구 진입 시각과 FIFO를 유지해 동시 이상을 계속 전달한다.
    expected = {
        "infeed_occupancy",
        "infeed_interval",
        "transfer_time",
        "outfeed_missing",
    }
    assert {item.check_name for item in results} == expected
    assert all(item.started_at == T0 + timedelta(seconds=1) for item in results)
    assert all(item.observed_value == 17 for item in results)


def test_outfeed_missing_without_readiness_context():
    detector = started_detector()
    context = DetectionContext(run_cmd=True)
    # 입구 t1부터 정확히 16초까지는 정상 경계이고, 17초가 지나면 미검출이다.
    for second in range(1, 18):
        results = detector.evaluate(record(second, infeed=second == 1), context)
        assert not any(item.check_name == "outfeed_missing" for item in results)
    results = detector.evaluate(record(18), context)
    missing = next(item for item in results if item.check_name == "outfeed_missing")
    assert missing.started_at == T0 + timedelta(seconds=1)
    assert missing.observed_value == 17
    assert missing.tray_seq == 1


def test_outfeed_missing_timer_restarts_at_last_exit():
    detector = started_detector()
    context = DetectionContext(run_cmd=True)
    # 첫 트레이는 t16에 출구 도착, 두 번째는 아직 출구에 도착하지 않아 마지막 출구부터 계산한다.
    for second in range(1, 33):
        results = detector.evaluate(
            record(second, infeed=second in {1, 6}, outfeed=second == 16), context
        )
        assert not any(item.check_name == "outfeed_missing" for item in results)
    results = detector.evaluate(record(33), context)
    missing = next(item for item in results if item.check_name == "outfeed_missing")
    assert missing.started_at == T0 + timedelta(seconds=16)
    assert missing.observed_value == 17
    assert missing.tray_seq == 2


def test_duplicate_and_reverse_time():
    detector = AnomalyDetector(numeric_ranges={})
    row = record(1, infeed=True)
    assert detector.evaluate(row) == []
    assert detector.evaluate(row) == []
    with pytest.raises(ValueError, match="timestamp"):
        detector.evaluate(record(0))
    assert detector.evaluate(record(2, infeed=True)) == []


def test_assets_do_not_share_occupancy_state():
    detector = AnomalyDetector(numeric_ranges={})
    for second in range(5):
        results = detector.evaluate(record(second, infeed=True))
        assert detector.evaluate(record(second, asset="motor-2")) == []
    assert any(item.check_name == "infeed_occupancy" for item in results)


def test_configuration_validation():
    with pytest.raises(ValueError):
        AnomalyDetector(transfer_range_s=(16, 14))
    with pytest.raises(ValueError):
        AnomalyDetector(numeric_ranges={"record_id": NumericRange(0, 1, "-")})
    with pytest.raises(ValueError):
        NumericRange(float("nan"), 1, "-")


def test_unmatched_exit_keeps_tracking_and_registers_simultaneous_infeed():
    detector = started_detector()
    # 빈 큐의 출구 신호는 이상이지만, 같은 행의 입구 트레이는 등록해야 한다.
    results = detector.evaluate(record(1, infeed=True, outfeed=True), RUN)
    assert any(item.check_name == "signal_pattern" for item in results)
    exits = []
    for second in range(2, 25):
        results = detector.evaluate(
            record(second, infeed=second == 6, outfeed=second in {19, 24}), RUN
        )
        assert not any(item.check_name == "signal_pattern" for item in results)
        if second in {19, 24}:
            exits.extend(item for item in results if item.check_name == "transfer_time")
    assert [(item.tray_seq, item.observed_value) for item in exits] == [
        (1, 18),
        (2, 18),
    ]


def test_stuck_infeed_reports_anomalies_without_inventing_trays_or_stopping_fifo():
    detector = started_detector()
    held = []
    exits = []
    for second in range(1, 35):
        results = detector.evaluate(
            record(
                second, infeed=second <= 8 or second == 21, outfeed=second in {19, 34}
            ),
            RUN,
        )
        if second == 8:
            held = results
        if second in {19, 34}:
            exits.extend(item for item in results if item.check_name == "transfer_time")
        assert not any(item.check_name == "signal_pattern" for item in results)
    assert {item.check_name for item in held} >= {"infeed_occupancy", "infeed_interval"}
    assert [(item.tray_seq, item.observed_value) for item in exits] == [
        (1, 18),
        (2, 13),
    ]


def test_new_edges_are_tracked_automatically_after_sample_gap():
    detector = started_detector()
    detector.evaluate(record(1, infeed=True), RUN)
    # 기존 데이터 공백 초기화 정책은 유지하고, 다음 유효 엣지부터 자동 추적한다.
    detector.evaluate(record(10), RUN)
    exits = []
    for second in range(11, 25):
        results = detector.evaluate(
            record(second, infeed=second == 11, outfeed=second == 24), RUN
        )
        if second == 24:
            exits = [item for item in results if item.check_name == "transfer_time"]
    assert len(exits) == 1
    assert exits[0].started_at == T0 + timedelta(seconds=11)
    assert exits[0].observed_value == 13
