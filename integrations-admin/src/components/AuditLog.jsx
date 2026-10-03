const when = (ms) => new Date(ms).toLocaleString();

function detail(e) {
  const x = e.extra || {};
  if ("from" in x) return `${x.from} → ${x.to}${x.connectionsAffected ? ` (${x.connectionsAffected} connections dropped)` : ""}`;
  if (x.label !== undefined) return `label: ${x.label || "(none)"}`;
  return e.outcome && e.outcome !== "ok" ? e.outcome : "";
}

export default function AuditLog({ entries }) {
  return (
    <table>
      <thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Target</th><th>Detail</th></tr></thead>
      <tbody>
        {entries.map((e, i) => (
          <tr key={i}><td>{when(e.at)}</td><td>{e.actor}</td><td>{e.action}</td><td>{e.target}</td><td>{detail(e)}</td></tr>
        ))}
      </tbody>
    </table>
  );
}
