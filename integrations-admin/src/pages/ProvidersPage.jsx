import { useState } from "react";
import ProviderEditor from "../components/ProviderEditor";
import ProvidersTable from "../components/ProvidersTable";
import { Empty, ErrorBox, Loading } from "../components/States";
import { useProviders } from "../hooks/useProviders";

export default function ProvidersPage({ api }) {
  const { status, data, error, reload, update, svc } = useProviders(api);
  const [editing, setEditing] = useState(null);
  const [toggleError, setToggleError] = useState("");

  async function toggle(p, enabled) {
    setToggleError("");
    try { await update(p.toolType, { enabled }); } catch (e) { setToggleError(e.message); }
  }

  if (status === "loading") return <Loading />;
  if (status === "error") return <ErrorBox error={error} onRetry={reload} />;
  if (!data.length) return <Empty>No providers registered.</Empty>;
  return (
    <>
      {toggleError && <p className="error" role="alert">{toggleError}</p>}
      <ProvidersTable providers={data} svc={svc} onEdit={setEditing} onToggle={toggle} />
      {editing && <ProviderEditor provider={editing} onSave={update} onClose={() => setEditing(null)} />}
    </>
  );
}
