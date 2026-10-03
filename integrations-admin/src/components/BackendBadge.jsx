const LABELS = { composio: "Composio", nango: "Nango", native: "Native" };

// Unknown backends fall back to their raw name, so a new backend needs no UI change.
export default function BackendBadge({ backend }) {
  return <span className={`badge badge-${LABELS[backend] ? backend : "other"}`}>{LABELS[backend] || backend}</span>;
}
