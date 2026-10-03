import { useMemo } from "react";
import { auditApi } from "../api/audit";
import { useResource } from "./useResource";

export function useAudit(api) {
  const svc = useMemo(() => auditApi(api), [api]);
  return useResource(svc.list);
}
