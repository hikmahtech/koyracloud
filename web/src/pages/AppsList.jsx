import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listApps, getAppsStatus } from "../api";

const STATUS = {
  live: ["var(--color-acid)", "live"],
  failed: ["var(--color-danger)", "failed"],
  building: ["#febc2e", "building"],
  deploying: ["#febc2e", "deploying"],
  pending: ["#8a909c", "pending"],
  rolled_back: ["#b69cff", "rolled back"],
};

export function StatusBadge({ status }) {
  const [color, label] = STATUS[status] || ["#5a6070", status || "never deployed"];
  return (
    <span className="inline-flex items-center gap-2 mono text-xs text-[var(--color-muted)]">
      <span className="dot" style={{ background: color, boxShadow: `0 0 8px ${color}66` }} />
      {label}
    </span>
  );
}

export function RunningDot({ st }) {
  if (!st || !st.exists)
    return <span className="mono text-xs text-[var(--color-muted)]">offline</span>;
  const healthy = st.running >= st.desired && st.desired > 0;
  const c = healthy ? "var(--color-acid)" : st.running > 0 ? "#febc2e" : "var(--color-danger)";
  return (
    <span className="inline-flex items-center gap-2 mono text-xs text-[var(--color-muted)]" title="live replicas">
      <span className="dot" style={{ background: c, boxShadow: `0 0 8px ${c}66` }} />
      {st.running}/{st.desired}
    </span>
  );
}

export default function AppsList() {
  const { data: apps = [], isLoading } = useQuery({ queryKey: ["apps"], queryFn: listApps });
  const { data: status = {} } = useQuery({
    queryKey: ["apps-status"], queryFn: getAppsStatus, refetchInterval: 30000,
  });

  if (isLoading) return <p className="mono text-[var(--color-muted)]">loading apps…</p>;

  return (
    <div>
      <div className="flex items-end justify-between mb-7">
        <div>
          <div className="eyebrow">Dashboard</div>
          <h1 className="font-display text-3xl mt-2">Apps</h1>
        </div>
        <Link to="/apps/new" className="btn btn-ghost">+ New App</Link>
      </div>

      {apps.length === 0 ? (
        <div className="card p-16 text-center">
          <p className="text-[var(--color-muted)] mb-5">No apps yet. Connect a repo with a <span className="mono text-acid">.paas/app.yaml</span>.</p>
          <Link to="/apps/new" className="btn btn-primary">Connect your first repo →</Link>
        </div>
      ) : (
        <div className="grid gap-3">
          {apps.map((app) => (
            <Link key={app.id} to={`/apps/${app.id}`}
                  className="card p-5 flex items-center justify-between hover:border-[#3a4150] transition no-underline text-[var(--color-fg)]">
              <div className="min-w-0">
                <div className="font-display text-lg">{app.name}</div>
                {app.primary_host ? (
                  <div className="mono text-xs text-[var(--color-muted)] mt-1 truncate">{app.primary_host}</div>
                ) : (
                  <div className="mono text-xs text-[var(--color-muted)] mt-1 truncate">{app.repo_url}</div>
                )}
              </div>
              <div className="flex items-center gap-5 shrink-0">
                <span className="mono text-xs text-[var(--color-muted)] hidden sm:inline">{app.branch}</span>
                <RunningDot st={status[String(app.id)]} />
                <StatusBadge status={app.latest_status} />
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
