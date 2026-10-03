import { ApiError } from "../api/client";

export function Loading() { return <p className="muted" role="status">Loading…</p>; }

export function ErrorBox({ error, onRetry }) {
  const offline = error instanceof ApiError && error.status === 0;
  return (
    <div className="error" role="alert">
      <strong>{offline ? "No gateway connection." : "Something went wrong."}</strong> {error.message}
      {onRetry && <button onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function Empty({ children }) { return <p className="empty">{children}</p>; }
