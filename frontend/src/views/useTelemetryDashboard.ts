import { useEffect, useRef, useState } from "react";
import { getLatestTelemetry, watchTelemetry } from "../api/client";
import { applySnapshot, emptyChartModel } from "./telemetryCharts";

export default function useTelemetryDashboard(
  interval: number,
  onSessionExpired: () => void,
) {
  const model = useRef(emptyChartModel());
  const error = useRef<string | null>(null);
  const [view, setView] = useState(() => ({
    model: model.current,
    error: error.current,
    now: Date.now(),
  }));

  useEffect(() => {
    let active = true;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let delay = 1000;
    const controller = new AbortController();
    const publish = () => {
      if (active)
        setView({
          model: model.current,
          error: error.current,
          now: Date.now(),
        });
    };
    const accept = (
      snapshot: Awaited<ReturnType<typeof getLatestTelemetry>>,
    ) => {
      if (!active || controller.signal.aborted) return;
      const previous = model.current.snapshot;
      model.current = applySnapshot(model.current, snapshot, Date.now());
      const recovered = error.current !== null;
      error.current = null;
      if (
        !previous ||
        recovered ||
        previous.epoch !== snapshot.epoch ||
        previous.run_id !== snapshot.run_id
      )
        publish();
    };
    async function connect() {
      try {
        // Bootstrap sequentially so an older REST response cannot overwrite SSE.
        accept(await getLatestTelemetry(controller.signal));
        await watchTelemetry(controller.signal, (snapshot) => {
          delay = 1000;
          accept(snapshot);
        });
      } catch (failure) {
        if (!active || controller.signal.aborted) return;
        const status =
          failure && typeof failure === "object" && "status" in failure
            ? failure.status
            : null;
        if (status === 401 || status === 403) {
          error.current = "로그인 세션이 만료됐습니다.";
          publish();
          onSessionExpired();
          return;
        }
        error.current = "센서 조회 연결을 다시 시도하고 있습니다.";
        publish();
      }
      if (active) {
        retry = setTimeout(connect, delay);
        delay = Math.min(delay * 2, 30_000);
      }
    }
    void connect();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(retry);
    };
  }, [onSessionExpired]);

  useEffect(() => {
    const timer = setInterval(
      () =>
        setView({
          model: model.current,
          error: error.current,
          now: Date.now(),
        }),
      interval,
    );
    return () => clearInterval(timer);
  }, [interval]);
  return view;
}
