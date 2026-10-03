import { useState } from "react";
import ConfirmDialog from "./ConfirmDialog";

const BACKENDS = ["composio", "nango", "native"];

// Changing the backend needs an explicit confirm that states how many connections it drops.
export default function ProviderEditor({ provider, onSave, onClose }) {
  const [backend, setBackend] = useState(provider.backend);
  const [slug, setSlug] = useState(provider.backendSlug);
  const [pending, setPending] = useState(null); // {connectionsAffected}
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function save(confirm) {
    setBusy(true);
    setError("");
    try {
      await onSave(provider.toolType, { backend, backendSlug: slug, confirm });
      onClose();
    } catch (e) {
      if (e.status === 409 && e.detail) setPending(e.detail);
      else setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (pending) {
    return (
      <ConfirmDialog title="Switch backend?" confirmLabel={`Disconnect ${pending.connectionsAffected} and switch`}
        busy={busy} onConfirm={() => save(true)} onCancel={() => { setPending(null); }}>
        <p>Changing <b>{provider.displayName}</b> from <b>{provider.backend}</b> to <b>{backend}</b> will disconnect{" "}
          <b>{pending.connectionsAffected}</b> existing connection(s). Tokens cannot move between backends; each user must reconnect.</p>
      </ConfirmDialog>
    );
  }
  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label={`Edit ${provider.displayName}`}>
      <div className="dialog">
        <h3>Edit {provider.displayName}</h3>
        <label>Backend
          <select value={backend} onChange={(e) => setBackend(e.target.value)}>
            {BACKENDS.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
        </label>
        <label>Backend slug
          <input value={slug} onChange={(e) => setSlug(e.target.value)} />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <div className="row end">
          <button onClick={onClose} disabled={busy}>Cancel</button>
          <button className="primary" onClick={() => save(false)} disabled={busy}>Save</button>
        </div>
      </div>
    </div>
  );
}
