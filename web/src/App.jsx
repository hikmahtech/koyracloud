import { Routes, Route, Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getMe, logout } from "./api";
import { Logo } from "./components/Chrome.jsx";
import Landing from "./pages/Landing.jsx";
import AppsList from "./pages/AppsList.jsx";
import NewApp from "./pages/NewApp.jsx";
import AppDetail from "./pages/AppDetail.jsx";
import Team from "./pages/Team.jsx";

function AppShell({ me, children }) {
  const nav = useNavigate();
  return (
    <div className="grid-bg min-h-screen">
      <header className="border-b border-[var(--color-line)] bg-[rgba(10,11,13,0.7)] backdrop-blur sticky top-0 z-30">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <Link to="/" className="text-[var(--color-fg)] no-underline"><Logo /></Link>
          <div className="flex items-center gap-6 text-sm">
            <Link to="/docs" className="text-[var(--color-muted)] hover:text-[var(--color-fg)] no-underline">Docs</Link>
            {me.is_admin && (
              <Link to="/team" className="text-[var(--color-muted)] hover:text-[var(--color-fg)] no-underline">Team</Link>
            )}
            <Link to="/apps/new" className="btn btn-primary">New App</Link>
            <div className="flex items-center gap-2 mono text-xs text-[var(--color-muted)]">
              <span className="dot" style={{ background: "var(--color-acid)" }} />@{me.login}
            </div>
            <button onClick={async () => { await logout(); nav(0); }}
                    className="text-[var(--color-muted)] hover:text-[var(--color-fg)] bg-transparent border-0 cursor-pointer text-sm">
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="max-w-6xl mx-auto px-6 py-10">{children}</main>
    </div>
  );
}

export default function Dashboard() {
  const { data: me, isLoading, isError } = useQuery({ queryKey: ["me"], queryFn: getMe });

  if (isLoading)
    return <div className="grid-bg min-h-screen flex items-center justify-center mono text-[var(--color-muted)]">loading…</div>;
  if (isError || !me) return <Landing />;

  return (
    <AppShell me={me}>
      <Routes>
        <Route path="/" element={<AppsList />} />
        <Route path="/apps/new" element={<NewApp />} />
        <Route path="/apps/:id" element={<AppDetail />} />
        <Route path="/team" element={<Team />} />
      </Routes>
    </AppShell>
  );
}
