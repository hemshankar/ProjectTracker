import { useEffect, useMemo, useState } from "react";
import { createClient } from "./api/client";
import { sessionApi } from "./api/session";
import LoginForm from "./components/LoginForm";
import { ErrorBox, Loading } from "./components/States";
import ActionsPage from "./pages/ActionsPage";
import AuditPage from "./pages/AuditPage";
import CredentialsPage from "./pages/CredentialsPage";
import ProvidersPage from "./pages/ProvidersPage";

// key: [nav label, page component, page subtitle]
const PAGES = {
  providers: ["Providers", ProvidersPage, "Where each integration is routed, its credentials, and live connection health."],
  actions: ["Tools", ActionsPage, "Named actions callers can use, with retry limits."],
  credentials: ["Credentials", CredentialsPage, "Backend API keys and secrets. Write-only and encrypted at rest."],
  audit: ["Audit log", AuditPage, "Every admin change and proxied call, newest first."],
};

function Brand({ tag }) {
  return (
    <div className="brand">
      <span className="brand-mark" aria-hidden="true">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 8h10M8 3v10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
      </span>
      Connections Gateway{tag && <span className="brand-tag">Admin</span>}
    </div>
  );
}

export default function App() {
  const [auth, setAuth] = useState("checking"); // checking | out | in | offline
  const [page, setPage] = useState("providers");
  const api = useMemo(() => createClient({ onUnauthorized: () => setAuth("out") }), []);
  const session = useMemo(() => sessionApi(api), [api]);

  useEffect(() => {
    session.me().then(() => setAuth("in")).catch((e) => setAuth(e.status === 0 ? "offline" : "out"));
  }, [session]);

  if (auth === "checking") return <main className="narrow"><Loading /></main>;
  if (auth === "offline") return <main className="narrow"><ErrorBox error={new Error("The admin API is not responding.")} /></main>;
  if (auth === "out") return <main className="narrow"><LoginForm onLogin={async (pw) => { await session.login(pw); setAuth("in"); }} /></main>;

  const [title, Page, subtitle] = PAGES[page];
  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <Brand tag />
          <nav aria-label="Sections">
            {Object.entries(PAGES).map(([key, [label]]) => (
              <button key={key} className={key === page ? "active" : ""} aria-current={key === page ? "page" : undefined} onClick={() => setPage(key)}>{label}</button>
            ))}
          </nav>
          <button className="signout" onClick={async () => { await session.logout().catch(() => {}); setAuth("out"); }}>Sign out</button>
        </div>
      </header>
      <main>
        <div className="page-head"><h2>{title}</h2><p>{subtitle}</p></div>
        <Page api={api} />
      </main>
    </>
  );
}
