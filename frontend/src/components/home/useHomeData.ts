import { useCallback, useEffect, useRef, useState } from "react";

export type Slice<T> = {
  data: T | null;
  error: string;
  loading: boolean;
  reload: () => void;
};

function isUnauthorized(error: unknown) {
  return (
    !!error &&
    typeof error === "object" &&
    "status" in error &&
    error.status === 401
  );
}

/**
 * 한 가지 데이터를 주기적으로 불러온다. 박스마다 따로 쓰므로 한 곳이 실패해도
 * 나머지는 영향을 받지 않고, 실패하면 직전 데이터를 유지한 채 오류만 알린다.
 */
export default function useSlice<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  enabled: boolean,
  onSessionExpired: () => void,
): Slice<T> {
  const [state, setState] = useState<{
    data: T | null;
    error: string;
    loading: boolean;
  }>({ data: null, error: "", loading: enabled });
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  const expiredRef = useRef(onSessionExpired);
  fetcherRef.current = fetcher;
  expiredRef.current = onSessionExpired;

  useEffect(() => {
    if (!enabled) {
      setState({ data: null, error: "", loading: false });
      return;
    }
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      try {
        const data = await fetcherRef.current();
        if (active) setState({ data, error: "", loading: false });
      } catch (failure) {
        if (!active) return;
        if (isUnauthorized(failure)) expiredRef.current();
        setState((previous) => ({
          data: previous.data,
          error:
            failure instanceof Error ? failure.message : "불러오지 못했습니다.",
          loading: false,
        }));
      }
      if (active) timer = setTimeout(poll, intervalMs);
    }
    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [enabled, intervalMs, tick]);

  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { ...state, reload };
}
