import { useState } from "react";

function CredentialRow({ cred, onSave, onClear }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try { await onSave(cred.name, value); setValue(""); } catch (err) { setError(err.message); } finally { setBusy(false); }
  }

  return (
    <form className="card" onSubmit={save}>
      <div className="row">
        <b>{cred.label}</b>
        <span className={`pill pill-${cred.status}`}>{cred.status === "set" ? `set (${cred.source})` : "not set"}</span>
      </div>
      <div className="row">
        {/* Write-only: the value is never shown, only replaced. */}
        <input type="password" autoComplete="off" placeholder={cred.status === "set" ? "Enter a new value to rotate" : "Enter value"}
          value={value} onChange={(e) => setValue(e.target.value)} aria-label={cred.label} />
        <button type="submit" disabled={busy || !value}>{cred.status === "set" ? "Rotate" : "Save"}</button>
        {cred.source === "db" && <button type="button" disabled={busy} onClick={() => onClear(cred.name)}>Clear</button>}
      </div>
      {error && <p className="error" role="alert">{error}</p>}
    </form>
  );
}

export default function CredentialsPanel({ credentials, onSave, onClear }) {
  return <div>{credentials.map((c) => <CredentialRow key={c.name} cred={c} onSave={onSave} onClear={onClear} />)}</div>;
}
