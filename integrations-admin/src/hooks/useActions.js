import { useMemo } from "react";
import { actionsApi } from "../api/actions";
import { useResource } from "./useResource";

export function useActions(api) {
  const svc = useMemo(() => actionsApi(api), [api]);
  const res = useResource(svc.list);
  return { ...res, save: async (action, patch) => { await svc.update(action, patch); await res.reload(); } };
}
