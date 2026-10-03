import { useMemo } from "react";
import { providersApi } from "../api/providers";
import { useResource } from "./useResource";

export function useProviders(api) {
  const svc = useMemo(() => providersApi(api), [api]);
  const res = useResource(svc.list);
  return { ...res, update: async (t, patch) => { const r = await svc.update(t, patch); await res.reload(); return r; }, svc };
}
