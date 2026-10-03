import BackendBadge from "./BackendBadge";
import TestPanel from "./TestPanel";

const CRED_LABEL = { set: "set", missing: "missing", "n/a": "n/a" };

export default function ProvidersTable({ providers, svc, onEdit, onToggle }) {
  return (
    <div className="table-wrap"><table>
      <thead>
        <tr><th>Provider</th><th>Backend</th><th>Slug</th><th>Auth</th><th>Credentials</th><th>Connections</th><th>Enabled</th><th></th><th>Test</th></tr>
      </thead>
      <tbody>
        {providers.map((p) => (
          <tr key={p.toolType}>
            <td><b>{p.displayName}</b><div className="muted">{p.toolType}</div></td>
            <td><BackendBadge backend={p.backend} />{!p.backendAvailable && <div className="warn">backend not installed</div>}</td>
            <td>{p.backendSlug}</td>
            <td>{p.authMode}</td>
            <td><span className={`pill pill-${p.credentialStatus}`}>{CRED_LABEL[p.credentialStatus] || p.credentialStatus}</span></td>
            <td>{p.connectionCount}</td>
            <td>
              <label className="switch">
                <input type="checkbox" checked={p.enabled} onChange={(e) => onToggle(p, e.target.checked)}
                  aria-label={`${p.displayName} enabled`} />
              </label>
            </td>
            <td><button onClick={() => onEdit(p)}>Edit</button></td>
            <td><TestPanel provider={p} svc={svc} /></td>
          </tr>
        ))}
      </tbody>
    </table></div>
  );
}
