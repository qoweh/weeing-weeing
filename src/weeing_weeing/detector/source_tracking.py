"""개별 트레이 이벤트와 확인된 재공 스냅샷을 사용하는 선택적 시뮬레이터 추적."""

from collections import deque

from weeing_weeing.contracts import Severity


def evaluate_source_tracking(record, context, state, put, completed_transfer):
    source = context["source_tracking"]
    fields = ("infeed_present", "outfeed_present")
    emit = put
    buffered = []

    def put(*args, **kwargs):
        buffered.append((args, kwargs))

    def invalid(reason):
        state.tracking = False
        state.source_sequence = None
        state.source_previous_at = None
        state.clear_transfer_history()
        # A bad checkpoint invalidates this frame's transfer assessments too.
        buffered.clear()
        emit("D04", Severity.WARNING, reason=reason)

    if not source["origin_verified_empty"] or not source["events_complete"]:
        invalid("원천 재공 추적 초기화 또는 이벤트 완전성 미확인")
        return
    checkpoint = [
        (item["item_id"], item["entered_at"], item["simulation_seconds"])
        for item in source["pending"]
    ]
    if state.source_epoch != source["source_id"] or state.source_sequence is None:
        # 직접 확인한 원천 재공만 복원한다. 과거 이송 통계나 사건 회복은 추정하지 않는다.
        state.source_epoch = source["source_id"]
        state.source_sequence = source["sequence"]
        state.source_pending = deque(checkpoint)
        state.clear_transfer_history()
        state.last_in = source["last_infeed_at"]
        state.last_out = source["last_outfeed_at"]
        state.source_last_in_seconds = source["last_infeed_simulation_seconds"]
        state.source_last_out_seconds = source["last_outfeed_simulation_seconds"]
        state.tracking = True
        state.expired = False
        state.intervals.clear()
        state.normal_intervals = 0
    else:
        if (
            state.source_previous_seconds is not None
            and source["simulation_seconds"] < state.source_previous_seconds
        ):
            invalid("시뮬레이션 시계 역행")
            return
        expected = state.source_sequence + 1
        for event in source["events"]:
            if event["sequence"] != expected:
                invalid("원천 이벤트 순번 불연속")
                return
            expected += 1
            at = event["at"]
            clock = event["simulation_seconds"]
            if (
                state.source_previous_seconds is not None
                and clock < state.source_previous_seconds
            ):
                invalid("이전 표본보다 오래된 시뮬레이션 이벤트")
                return
            if state.source_previous_at is not None and at < state.source_previous_at:
                invalid("이전 표본보다 오래된 원천 이벤트")
                return
            if event["kind"] == "infeed":
                if any(
                    item_id == event["item_id"]
                    for item_id, _, _ in state.source_pending
                ):
                    invalid("중복 트레이 입구 이벤트")
                    return
                if state.last_in is not None:
                    interval = clock - state.source_last_in_seconds
                    bad = not 4 <= interval <= 6
                    state.intervals.append(bad)
                    state.normal_intervals = 0 if bad else state.normal_intervals + 1
                    if bad:
                        put(
                            "P05",
                            Severity.ERROR
                            if len(state.intervals) == 5 and sum(state.intervals) >= 3
                            else Severity.WARNING,
                            fields[:1],
                            criterion="원천 투입 4~6초, 최근 5간격 중 3회 이탈 Error",
                            observed=f"간격 {interval:g}초",
                            started_at=state.last_in,
                        )
                    elif state.normal_intervals >= 5:
                        put("P05", Severity.NORMAL)
                state.last_in = at
                state.source_last_in_seconds = clock
                state.source_pending.append((event["item_id"], at, clock))
            else:
                state.last_out = at
                state.source_last_out_seconds = clock
                if (
                    not state.source_pending
                    or state.source_pending[0][0] != event["item_id"]
                ):
                    invalid("대응 입구 또는 FIFO 순서가 다른 출구 이벤트")
                    return
                _, entered, entered_clock = state.source_pending.popleft()
                if state.expired:
                    invalid("만료 트레이의 늦은 출구: 원천 재동기화 필요")
                    return
                completed_transfer(
                    record.model_copy(update={"timestamp": at}),
                    {**context, "source_event_simulation_seconds": clock},
                    state,
                    put,
                    clock - entered_clock,
                    entered,
                )
        if (
            expected - 1 != source["sequence"]
            or list(state.source_pending) != checkpoint
            or state.last_in != source["last_infeed_at"]
            or state.last_out != source["last_outfeed_at"]
            or state.source_last_in_seconds != source["last_infeed_simulation_seconds"]
            or state.source_last_out_seconds
            != source["last_outfeed_simulation_seconds"]
        ):
            invalid("원천 이벤트와 재공 스냅샷 불일치")
            return
        state.source_sequence = source["sequence"]
    state.source_previous_at = record.timestamp
    state.source_previous_seconds = source["simulation_seconds"]
    put("D04", Severity.NORMAL, reason="원천 트레이 이벤트·재공 스냅샷 일치")
    if state.last_in and context.get("continuous_infeed") is True:
        elapsed = source["simulation_seconds"] - state.source_last_in_seconds
        if elapsed > 6:
            put(
                "P05",
                Severity.ERROR if elapsed > 10 else Severity.WARNING,
                fields[:1],
                criterion="원천 미투입 >6초 Warning, >10초 Error",
                observed=f"미투입 {elapsed:g}초",
                started_at=state.last_in,
            )
    if state.source_pending:
        entered = state.source_pending[0][1]
        entered_clock = state.source_pending[0][2]
        elapsed = source["simulation_seconds"] - entered_clock
        if elapsed > 16:
            state.expired = True
            put(
                "P01",
                Severity.ERROR,
                fields,
                criterion="출구 미도착 >16초",
                observed=f"{elapsed:g}초",
                started_at=entered,
            )
        origin = max(entered, state.last_out) if state.last_out else entered
        out_clock = state.source_last_out_seconds
        no_out = source["simulation_seconds"] - max(
            entered_clock, out_clock if out_clock is not None else entered_clock
        )
        if no_out > 16 and context.get("downstream_ready") is True:
            put(
                "P06",
                Severity.ERROR,
                fields,
                criterion="재공·RUN·수신 가능·출구 없음 >16초",
                observed=f"출구 없음 {no_out:g}초",
                started_at=origin,
            )
    elif context.get("inspection_confirmed") is True:
        put("P01", Severity.NORMAL)
        put("P06", Severity.NORMAL)
    for args, kwargs in buffered:
        emit(*args, **kwargs)
