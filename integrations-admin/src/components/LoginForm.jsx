import { useState } from "react";

export default function LoginForm({ onLogin }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try { await onLogin(password); } catch (err) { setError(err.message); setPassword(""); } finally { setBusy(false); }
  }

  return (
    <form className="card login" onSubmit={submit}>
      <span className="brand-mark" aria-hidden="true">
        <svg width="20" height="20" viewBox="0 0 16 16" fill="none"><path d="M3 8h10M8 3v10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
      </span>
      <h1>Connections Gateway</h1>
      <p className="muted">Sign in to the admin console.</p>
      <label>Admin password
        <input type="password" autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus />
      </label>
      {error && <p className="error" role="alert">{error}</p>}
      <button type="submit" disabled={busy || !password}>Sign in</button>
    </form>
  );
}
