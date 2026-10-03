export default function ConfirmDialog({ title, children, confirmLabel = "Confirm", onConfirm, onCancel, busy }) {
  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label={title}>
      <div className="dialog">
        <h3>{title}</h3>
        <div>{children}</div>
        <div className="row end">
          <button onClick={onCancel} disabled={busy}>Cancel</button>
          <button className="danger" onClick={onConfirm} disabled={busy}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}
