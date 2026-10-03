import { useState } from "react";
import { ErrorBox } from "./States";

export default function ActionRow({ action: a, onSave }) {
  const [open, setOpen] = useState(false);
  const [attempts, setAttempts] = useState(a.maxAttempts);
  const [delay, setDelay] = useState(a.baseDelayMs);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  const save = async () => {
    setBusy(true); setError(null); setSaved(false);
    try {
      const patch = { baseDelayMs: Number(delay) };
      if (a.retriesEditable) patch.maxAttempts = Number(attempts);
      await onSave(a.action, patch);
      setSaved(true);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <>
      <tr>
        <td><button className="link" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? "▾" : "▸"} {a.action}</button></td>
        <td>{a.mutating ? "Write" : "Read"}</td>
        <td>{a.retriesEditable ? a.maxAttempts : "none (writes never retry)"}</td>
      </tr>
      {open && (
        <tr><td colSpan={3}>
          <p>{a.description}</p>
          <details><summary>Input schema</summary><pre>{JSON.stringify(a.inputSchema, null, 2)}</pre></details>
          <div className="row">
            <label>Max attempts{" "}
              <input type="number" min={1} max={10} value={attempts} disabled={!a.retriesEditable}
                onChange={(e) => setAttempts(e.target.value)} />
            </label>
            <label>Base delay (ms){" "}
              <input type="number" min={0} max={10000} value={delay} onChange={(e) => setDelay(e.target.value)} />
            </label>
            <button className="primary" onClick={save} disabled={busy}>Save</button>
            {saved && <span className="muted">Saved</span>}
          </div>
          <p className="muted">Retries apply to reads on 429/5xx with exponential backoff. Writes are sent once.</p>
          {error && <ErrorBox error={error} />}
        </td></tr>
      )}
    </>
  );
}
