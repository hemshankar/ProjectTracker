import { useMemo } from "react";
import { credentialsApi } from "../api/credentials";
import { useResource } from "./useResource";

export function useCredentials(api) {
  const svc = useMemo(() => credentialsApi(api), [api]);
  const res = useResource(svc.list);
  return {
    ...res,
    save: async (name, value) => { await svc.set(name, value); await res.reload(); },
    clear: async (name) => { await svc.clear(name); await res.reload(); },
  };
}
