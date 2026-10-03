import { useCallback, useEffect, useState } from "react";

// loading | error | ready — every page renders all three (plus empty) explicitly.
export function useResource(load) {
  const [state, setState] = useState({ status: "loading", data: null, error: null });
  const reload = useCallback(async () => {
    try {
      setState((s) => ({ ...s, status: s.data ? "ready" : "loading" }));
      setState({ status: "ready", data: await load(), error: null });
    } catch (e) {
      setState({ status: "error", data: null, error: e });
    }
  }, [load]);
  useEffect(() => { reload(); }, [reload]);
  return { ...state, reload };
}
