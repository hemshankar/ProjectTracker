import { useState } from "react";

export default function TestPanel({ provider, svc }) {
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  async function run(fn) {
    setBusy(true);
    try { setResult(await fn()); } catch (e) { setResult({ ok: false, error: e.message }); } finally { setBusy(false); }
  }
  const connect = () => run(async () => {
    const { url } = await svc.testConnect(provider.toolType);
    window.open(url, "_blank", "noopener");
    return { ok: true, note: "Connect link opened in a new tab. Authorize, then run the test action." };
  });

  return (
    <div className="test">
      <button disabled={busy} onClick={connect}>Test connect</button>
      <button disabled={busy} onClick={() => run(() => svc.testAction(provider.toolType))}>Test action</button>
      {result && (
        <span className={result.ok ? "ok" : "bad"} role="status">
          {result.ok ? "OK" : "Failed"}
          {result.latencyMs !== undefined && ` · ${result.latencyMs} ms`}
          {result.action && ` · ${result.action}`}
          {result.error && ` · ${result.error}`}
          {result.note && ` · ${result.note}`}
        </span>
      )}
    </div>
  );
}
