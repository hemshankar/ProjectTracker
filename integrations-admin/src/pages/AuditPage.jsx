import AuditLog from "../components/AuditLog";
import { Empty, ErrorBox, Loading } from "../components/States";
import { useAudit } from "../hooks/useAudit";

export default function AuditPage({ api }) {
  const { status, data, error, reload } = useAudit(api);
  if (status === "loading") return <Loading />;
  if (status === "error") return <ErrorBox error={error} onRetry={reload} />;
  if (!data.length) return <Empty>No audit entries yet.</Empty>;
  return <><button onClick={reload}>Refresh</button><AuditLog entries={data} /></>;
}
