import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getApp, listDeploys, triggerDeploy, rollback, updateApp, deleteApp,
  getEnv, putEnv, listSecretKeys, putSecret, deleteSecret,
  listDomains, addDomain, setPrimaryDomain, deleteDomain, verifyDomain, getConfig,
  getStatus, getRuntimeLogs, getUptime, getAnalytics, setAnalytics,
  getNotify, setNotify,
  getBackground, getWorkerLogs, getCronRuns, getCronRunLog, runCronNow,
} from "../api";
import { StatusBadge } from "./AppsList";

const TABS = ["deploys", "background", "analytics", "logs", "domains", "env", "secrets", "settings"];

export default function AppDetail() {
  const { id } = useParams();
  const qc = useQueryClient();
  const [tab, setTab] = useState("deploys");
  const [liveId, setLiveId] = useState(null);

  const { data: app } = useQuery({ queryKey: ["app", id], queryFn: () => getApp(id) });
  const { data: status } = useQuery({
    queryKey: ["status", id], queryFn: () => getStatus(id), refetchInterval: 30000,
  });
  const { data: uptime } = useQuery({
    queryKey: ["uptime", id], queryFn: () => getUptime(id), refetchInterval: 60000,
  });
  const { data: deploys = [] } = useQuery({
    queryKey: ["deploys", id], queryFn: () => listDeploys(id),
    refetchInterval: liveId ? 2000 : false,
  });

  const deployMut = useMutation({
    mutationFn: () => triggerDeploy(id),
    onSuccess: (d) => { setLiveId(d.id); qc.invalidateQueries({ queryKey: ["deploys", id] }); },
  });
  const rollbackMut = useMutation({
    mutationFn: (deployId) => rollback(id, deployId),
    onSuccess: (d) => { setLiveId(d.id); qc.invalidateQueries({ queryKey: ["deploys", id] }); },
  });

  if (!app) return <p className="mono text-[var(--color-muted)]">loading…</p>;
  const url = app.primary_host ? `https://${app.primary_host}` : null;

  return (
    <div>
      <Link to="/" className="mono text-xs text-[var(--color-muted)] hover:text-[var(--color-fg)] no-underline">← apps</Link>

      <div className="flex items-start justify-between flex-wrap gap-4 mt-4 mb-7">
        <div>
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="font-display text-3xl">{app.name}</h1>
            <StatusBadge status={app.latest_status} />
            <RuntimePill status={status} />
            <UptimePill uptime={uptime} />
          </div>
          <div className="flex items-center gap-4 mt-2 text-sm">
            {url && (
              <a href={url} target="_blank" rel="noreferrer"
                 className="mono text-acid hover:underline no-underline">{app.primary_host} ↗</a>
            )}
            <span className="mono text-xs text-[var(--color-muted)]">{app.branch}</span>
          </div>
        </div>
        <button onClick={() => deployMut.mutate()} disabled={deployMut.isPending} className="btn btn-primary">
          {deployMut.isPending ? "Triggering…" : "Deploy"}
        </button>
      </div>

      {liveId && <LiveLogs deployId={liveId} onDone={() => {
        qc.invalidateQueries({ queryKey: ["app", id] });
        qc.invalidateQueries({ queryKey: ["deploys", id] });
      }} />}

      <div className="flex gap-1 border-b border-[var(--color-line)] mb-6">
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)}
                  className={`px-4 py-2.5 text-sm capitalize linkbtn -mb-px border-b-2 ${
                    tab === t ? "border-[var(--color-acid)] text-[var(--color-fg)]" : "border-transparent text-[var(--color-muted)] hover:text-[var(--color-fg)]"
                  }`}>{t}</button>
        ))}
      </div>

      {tab === "deploys" && <DeployHistory deploys={deploys} onRollback={(d) => rollbackMut.mutate(d)} />}
      {tab === "background" && <BackgroundTab id={id} />}
      {tab === "analytics" && <AnalyticsTab id={id} />}
      {tab === "logs" && <RuntimeLogs id={id} />}
      {tab === "domains" && <DomainsTab id={id} />}
      {tab === "env" && <EnvEditor id={id} />}
      {tab === "secrets" && <SecretsEditor id={id} />}
      {tab === "settings" && <SettingsTab id={id} app={app} />}
    </div>
  );
}

function RuntimePill({ status }) {
  if (!status) return null;
  if (!status.exists)
    return <span className="mono text-xs text-[var(--color-muted)]">· not deployed</span>;
  const healthy = status.running >= status.desired && status.desired > 0;
  const c = healthy ? "var(--color-acid)" : status.running > 0 ? "#febc2e" : "var(--color-danger)";
  return (
    <span className="inline-flex items-center gap-2 mono text-xs text-[var(--color-muted)]"
          title={status.tasks?.[0]?.state || ""}>
      <span className="dot" style={{ background: c, boxShadow: `0 0 8px ${c}66` }} />
      {status.running}/{status.desired} running
    </span>
  );
}

function UptimePill({ uptime }) {
  if (!uptime || uptime.up === null) return null;
  const c = uptime.up ? "var(--color-acid)" : "var(--color-danger)";
  const pct = uptime.uptime_24h != null ? ` · ${uptime.uptime_24h}% 24h` : "";
  return (
    <span className="inline-flex items-center gap-2 mono text-xs text-[var(--color-muted)]"
          title={uptime.since ? `since ${uptime.since}` : ""}>
      <span className="dot" style={{ background: c, boxShadow: `0 0 8px ${c}66` }} />
      {uptime.up ? "up" : "down"}{pct}
    </span>
  );
}

function AnalyticsTab({ id }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["analytics", id], queryFn: () => getAnalytics(id, 7) });
  const toggle = useMutation({
    mutationFn: (enabled) => setAnalytics(id, enabled),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["analytics", id] }),
  });
  if (!data) return <p className="mono text-[var(--color-muted)]">loading…</p>;
  const max = Math.max(1, ...data.series.map((d) => d.views));
  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex gap-4">
        <Stat label="Pageviews · 7d" value={data.views} />
        <Stat label="Unique visitors · 7d" value={data.visitors} />
      </div>

      {/* tiny bar series */}
      <div className="card p-5">
        <div className="eyebrow mb-4">Views per day</div>
        <div className="flex items-end gap-1.5 h-28">
          {data.series.map((d) => (
            <div key={d.date} className="flex-1 flex flex-col items-center gap-1" title={`${d.date}: ${d.views}`}>
              <div className="w-full rounded-t" style={{
                height: `${Math.max(2, (d.views / max) * 100)}%`,
                background: d.views ? "var(--color-acid)" : "var(--color-line)",
              }} />
              <span className="mono text-[9px] text-[var(--color-muted)]">{d.date.slice(5)}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="grid sm:grid-cols-2 gap-4">
        <TopList title="Top pages" rows={data.top_paths} keyName="path" />
        <TopList title="Top referrers" rows={data.top_referrers} keyName="source" />
      </div>

      <div className="card p-5 space-y-3">
        <div className="flex items-center justify-between">
          <div className="text-sm font-medium">Tracking</div>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={data.enabled} className="accent-[var(--color-acid)]"
                   onChange={(e) => toggle.mutate(e.target.checked)} />
            <span className="text-[var(--color-muted)]">{data.enabled ? "enabled" : "disabled"}</span>
          </label>
        </div>
        <p className="text-xs text-[var(--color-muted)]">
          Cookieless, first-party analytics. <b className="text-[var(--color-fg)]">Static sites</b> get
          the beacon auto-injected. <b className="text-[var(--color-fg)]">Dynamic apps</b>: paste this once:
        </p>
        <div className="mono text-xs bg-[var(--color-ink)] border border-[var(--color-line)] rounded px-3 py-2 break-all">
          {data.snippet}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="card p-5 flex-1">
      <div className="font-display text-4xl">{value}</div>
      <div className="eyebrow mt-1">{label}</div>
    </div>
  );
}

function TopList({ title, rows, keyName }) {
  return (
    <div className="card p-5">
      <div className="eyebrow mb-3">{title}</div>
      {rows.length === 0 && <div className="mono text-xs text-[var(--color-muted)]">no data yet</div>}
      <ul className="space-y-1.5">
        {rows.map((r) => (
          <li key={r[keyName]} className="flex justify-between text-sm">
            <span className="mono text-[var(--color-fg)] truncate mr-3">{r[keyName]}</span>
            <span className="mono text-[var(--color-muted)]">{r.views}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function RuntimeLogs({ id }) {
  const { data, isFetching, dataUpdatedAt, refetch } = useQuery({
    queryKey: ["runtime-logs", id],
    queryFn: () => getRuntimeLogs(id, 400),
    refetchInterval: 5 * 60 * 1000,   // auto-refresh every 5 minutes
  });
  const box = useRef(null);
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [data]);
  const updated = dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString() : "—";
  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-2.5 border-b border-[var(--color-line)] flex items-center justify-between">
        <span className="mono text-xs text-[var(--color-muted)]">
          runtime logs · auto-refresh 5m · updated {updated}
        </span>
        <button onClick={() => refetch()} disabled={isFetching}
                className="mono text-xs text-acid hover:underline linkbtn disabled:opacity-50">
          {isFetching ? "refreshing…" : "refresh"}
        </button>
      </div>
      <pre ref={box} className="mono text-[12px] leading-relaxed p-4 h-[28rem] overflow-auto codeblock m-0">
        {data?.logs || "loading…"}
      </pre>
    </div>
  );
}

function LiveLogs({ deployId, onDone }) {
  const [lines, setLines] = useState([]);
  const [done, setDone] = useState(null);
  const box = useRef(null);
  useEffect(() => {
    setLines([]); setDone(null);
    const es = new EventSource(`/api/deploys/${deployId}/logs`);
    es.onmessage = (e) => setLines((ls) => [...ls, e.data]);
    es.addEventListener("done", (e) => { setDone(e.data); es.close(); onDone?.(); });
    es.onerror = () => es.close();
    return () => es.close();
  }, [deployId]);
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [lines]);
  return (
    <div className="card overflow-hidden mb-7">
      <div className="px-4 py-2.5 border-b border-[var(--color-line)] flex items-center justify-between">
        <span className="mono text-xs text-[var(--color-muted)]">deploy #{deployId} · times UTC</span>
        {done && <StatusBadge status={done} />}
      </div>
      <pre ref={box} className="mono text-[12px] leading-relaxed p-4 h-64 overflow-auto codeblock m-0">
        {lines.join("\n") || "waiting for logs…"}
      </pre>
    </div>
  );
}

function DeployHistory({ deploys, onRollback }) {
  if (deploys.length === 0) return <p className="mono text-sm text-[var(--color-muted)]">No deploys yet — hit Deploy.</p>;
  return (
    <div className="card overflow-hidden">
      <table className="w-full text-sm">
        <thead><tr className="text-left mono text-xs text-[var(--color-muted)]">
          <th className="px-4 py-3">#</th><th>Status</th><th>When</th><th>Took</th><th>Ref</th><th>Commit</th><th></th>
        </tr></thead>
        <tbody>
          {deploys.map((d) => (
            <tr key={d.id} className="border-t border-[var(--color-line)]">
              <td className="px-4 py-3 mono">{d.id}</td>
              <td><StatusBadge status={d.status} /></td>
              <td className="mono text-xs text-[var(--color-muted)] whitespace-nowrap" title={fmtTime(d.created_at)}>
                {d.created_at ? fmtAgo(d.created_at) : "—"}
              </td>
              <td className="mono text-xs text-[var(--color-muted)] whitespace-nowrap">{fmtDuration(d.created_at, d.finished_at)}</td>
              <td className="mono text-xs text-[var(--color-muted)]">{d.ref?.slice(0, 12)}</td>
              <td className="mono text-xs text-[var(--color-muted)]">{d.commit?.slice(0, 12) || "—"}</td>
              <td className="text-right pr-4">
                {d.commit && (
                  <button onClick={() => onRollback(d.id)} className="text-acid hover:underline text-xs linkbtn">
                    redeploy this commit
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function fmtTime(iso) { try { return new Date(iso).toLocaleString(); } catch { return iso; } }
// Elapsed time between two ISO timestamps, e.g. "1m 12s". "—" if not finished yet.
function fmtDuration(startIso, endIso) {
  if (!startIso || !endIso) return "—";
  const s = Math.round((new Date(endIso) - new Date(startIso)) / 1000);
  if (s < 0) return "—";
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}
function fmtAgo(iso) {
  const s = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function RunBadge({ status }) {
  const map = {
    success: ["ok", "var(--color-acid)"],
    failed: ["failed", "var(--color-danger)"],
    running: ["running", "#febc2e"],
  };
  const [label, color] = map[status] || [status, "var(--color-muted)"];
  return <span className="mono text-[10px] rounded px-1.5 py-0.5 border" style={{ color, borderColor: color }}>{label}</span>;
}

function BackgroundTab({ id }) {
  const { data, isLoading } = useQuery({
    queryKey: ["background", id], queryFn: () => getBackground(id), refetchInterval: 15000,
  });
  if (isLoading || !data) return <p className="mono text-[var(--color-muted)]">loading…</p>;
  const { redis, workers, cron } = data;
  const empty = !redis.enabled && workers.length === 0 && cron.length === 0;
  return (
    <div className="max-w-3xl space-y-7">
      {empty && (
        <p className="text-sm text-[var(--color-muted)]">
          No background services yet. Declare <span className="mono text-[var(--color-fg)]">workers</span>,{" "}
          <span className="mono text-[var(--color-fg)]">cron</span> or <span className="mono text-[var(--color-fg)]">redis</span>{" "}
          in <span className="mono">.paas/app.yaml</span> and redeploy.
        </p>
      )}

      <section className="space-y-3">
        <div className="eyebrow">Workers</div>
        {workers.length === 0
          ? <p className="mono text-xs text-[var(--color-muted)]">No workers.</p>
          : <div className="card divide-y divide-[var(--color-line)]">
              {workers.map((w) => <WorkerRow key={w.name} id={id} w={w} />)}
            </div>}
      </section>

      <section className="space-y-3">
        <div className="eyebrow">Cron jobs <span className="text-[var(--color-muted)] normal-case">· UTC</span></div>
        {cron.length === 0
          ? <p className="mono text-xs text-[var(--color-muted)]">No cron jobs.</p>
          : <div className="space-y-2">{cron.map((c) => <CronRow key={c.id} id={id} job={c} />)}</div>}
      </section>

      <section className="space-y-3">
        <div className="eyebrow">Redis</div>
        <div className="card p-5 space-y-2">
          {redis.enabled ? (
            <>
              <div className="flex items-center gap-2 text-sm">
                <span className="dot" style={{ background: "var(--color-acid)", boxShadow: "0 0 8px var(--color-acid)66" }} />
                <span className="text-[var(--color-fg)]">Provisioned</span>
                <span className="mono text-xs text-[var(--color-muted)]">· REDIS_URL injected</span>
              </div>
              <p className="text-xs text-[var(--color-muted)]">
                Shared instance, isolated by ACL. Namespace every key and pub/sub channel as{" "}
                <span className="mono text-acid">{redis.prefix}:</span> — other names are rejected.
              </p>
            </>
          ) : (
            <p className="text-xs text-[var(--color-muted)]">
              Not enabled. Set <span className="mono text-[var(--color-fg)]">redis: true</span> in the manifest
              to get a scoped Redis + <span className="mono">REDIS_URL</span>.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}

function WorkerRow({ id, w }) {
  const [open, setOpen] = useState(false);
  const healthy = w.running >= w.desired && w.desired > 0;
  const c = healthy ? "var(--color-acid)" : w.running > 0 ? "#febc2e" : "var(--color-danger)";
  return (
    <div className="px-4 py-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="dot" style={{ background: c, boxShadow: `0 0 8px ${c}66` }} />
          <span className="mono text-sm">{w.name}</span>
          <span className="mono text-xs text-[var(--color-muted)]">{w.running}/{w.desired} running</span>
        </div>
        <button onClick={() => setOpen(!open)} className="text-xs text-acid hover:underline linkbtn">
          {open ? "hide logs" : "logs"}
        </button>
      </div>
      {open && <WorkerLogs id={id} worker={w.name} />}
    </div>
  );
}

function WorkerLogs({ id, worker }) {
  const { data } = useQuery({
    queryKey: ["worker-logs", id, worker], queryFn: () => getWorkerLogs(id, worker, 300),
    refetchInterval: 60000,
  });
  const box = useRef(null);
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [data]);
  return (
    <pre ref={box} className="mono text-[11px] leading-relaxed p-3 h-56 overflow-auto codeblock bg-[var(--color-ink)] border border-[var(--color-line)] rounded m-0 mt-3">
      {data?.logs || "loading…"}
    </pre>
  );
}

function CronRow({ id, job }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const run = useMutation({
    mutationFn: () => runCronNow(id, job.id),
    onSuccess: () => {
      setOpen(true);
      qc.invalidateQueries({ queryKey: ["cron-runs", id, job.id] });
      qc.invalidateQueries({ queryKey: ["background", id] });
    },
  });
  return (
    <div className="card px-4 py-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 min-w-0">
          <span className="mono text-sm">{job.name}</span>
          <span className="mono text-xs text-acid">{job.schedule}</span>
          {job.last_status && <RunBadge status={job.last_status} />}
          {job.last_run_at && <span className="mono text-[11px] text-[var(--color-muted)]" title={job.last_run_at}>{fmtAgo(job.last_run_at)}</span>}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <button onClick={() => run.mutate()} disabled={run.isPending} className="text-xs text-acid hover:underline linkbtn">
            {run.isPending ? "running…" : "run now"}
          </button>
          <button onClick={() => setOpen(!open)} className="text-xs text-[var(--color-muted)] hover:text-[var(--color-fg)] linkbtn">
            {open ? "hide" : "runs"}
          </button>
        </div>
      </div>
      <div className="mono text-[11px] text-[var(--color-muted)] mt-1.5 truncate">$ {job.command}</div>
      {open && <CronRuns id={id} jobId={job.id} />}
    </div>
  );
}

function CronRuns({ id, jobId }) {
  const { data: runs = [] } = useQuery({
    queryKey: ["cron-runs", id, jobId], queryFn: () => getCronRuns(id, jobId, 20),
    refetchInterval: 5000,
  });
  const [openRun, setOpenRun] = useState(null);
  if (runs.length === 0) return <p className="mono text-[11px] text-[var(--color-muted)] mt-3">No runs yet.</p>;
  return (
    <div className="mt-3 space-y-1">
      {runs.map((r) => (
        <div key={r.id}>
          <button onClick={() => setOpenRun(openRun === r.id ? null : r.id)}
                  className="w-full flex items-center justify-between text-left linkbtn px-0 py-1">
            <span className="flex items-center gap-2">
              <RunBadge status={r.status} />
              <span className="mono text-[11px] text-[var(--color-muted)]">{fmtTime(r.started_at)}</span>
              {r.exit_code != null && <span className="mono text-[11px] text-[var(--color-muted)]">exit {r.exit_code}</span>}
            </span>
            <span className="text-[11px] text-acid">{openRun === r.id ? "hide log" : "log"}</span>
          </button>
          {openRun === r.id && <CronRunLog id={id} jobId={jobId} runId={r.id} />}
        </div>
      ))}
    </div>
  );
}

function CronRunLog({ id, jobId, runId }) {
  const { data } = useQuery({
    queryKey: ["cron-run-log", id, jobId, runId], queryFn: () => getCronRunLog(id, jobId, runId),
  });
  return (
    <pre className="mono text-[11px] leading-relaxed p-3 max-h-72 overflow-auto codeblock bg-[var(--color-ink)] border border-[var(--color-line)] rounded m-0 mb-2">
      {data?.log || "loading…"}
    </pre>
  );
}

function DomainsTab({ id }) {
  const qc = useQueryClient();
  const { data: domains = [] } = useQuery({ queryKey: ["domains", id], queryFn: () => listDomains(id) });
  const { data: config } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const ip = config?.public_ip || "your server's IP";
  const [host, setHost] = useState("");
  const inval = () => qc.invalidateQueries({ queryKey: ["domains", id] });
  const invalApp = () => qc.invalidateQueries({ queryKey: ["app", id] });
  const addMut = useMutation({ mutationFn: () => addDomain(id, host), onSuccess: () => { setHost(""); inval(); invalApp(); } });
  const primMut = useMutation({ mutationFn: (did) => setPrimaryDomain(id, did), onSuccess: () => { inval(); invalApp(); } });
  const delMut = useMutation({ mutationFn: (did) => deleteDomain(id, did), onSuccess: () => { inval(); invalApp(); } });
  const verMut = useMutation({ mutationFn: (did) => verifyDomain(id, did), onSuccess: () => inval() });

  return (
    <div className="max-w-2xl space-y-5">
      <p className="text-sm text-[var(--color-muted)]">
        Add any domain you own. If a custom domain has CNAME records below, add them at your
        registrar and the edge mints &amp; auto-renews TLS for you. Otherwise point an A record
        at <span className="mono text-acid">{ip}</span> and Traefik mints TLS on first request.
        <b className="text-[var(--color-fg)]"> Redeploy</b> to apply changes.
      </p>
      <div className="card divide-y divide-[var(--color-line)]">
        {domains.map((d) => (
          <div key={d.id} className="px-4 py-3 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3 min-w-0">
                <DnsDot ok={d.dns_ok} />
                <a href={`https://${d.host}`} target="_blank" rel="noreferrer" className="mono text-sm no-underline text-[var(--color-fg)] hover:text-acid truncate">{d.host}</a>
                {d.is_primary && <span className="mono text-[10px] text-acid border border-[var(--color-line)] rounded px-1.5 py-0.5">PRIMARY</span>}
                {d.records?.length > 0 && <CertBadge verified={d.verified} />}
              </div>
              <div className="flex items-center gap-3 shrink-0">
                {!d.is_primary && <button onClick={() => primMut.mutate(d.id)} className="text-xs text-[var(--color-muted)] hover:text-[var(--color-fg)] linkbtn">set primary</button>}
                <button onClick={() => delMut.mutate(d.id)} className="text-xs text-[var(--color-danger)] hover:underline linkbtn">remove</button>
              </div>
            </div>
            {d.records?.length > 0 && (
              <div className="space-y-2 pl-5">
                <div className="flex items-center justify-between">
                  <p className="text-xs text-[var(--color-muted)]">Add these CNAME records at your registrar:</p>
                  <button onClick={() => verMut.mutate(d.id)} disabled={verMut.isPending} className="text-xs text-acid hover:underline linkbtn">
                    {verMut.isPending ? "checking…" : "verify"}
                  </button>
                </div>
                {d.records.map((r, i) => <DnsRecordRow key={i} record={r} />)}
              </div>
            )}
          </div>
        ))}
        {domains.length === 0 && <div className="px-4 py-3 mono text-sm text-[var(--color-muted)]">No domains.</div>}
      </div>
      <form onSubmit={(e) => { e.preventDefault(); addMut.mutate(); }} className="flex gap-2">
        <input value={host} onChange={(e) => setHost(e.target.value)} placeholder="app.example.com" className="input mono" />
        <button disabled={!host || addMut.isPending} className="btn btn-primary shrink-0">Add</button>
      </form>
      {addMut.isError && <p className="text-[var(--color-danger)] text-sm">{addMut.error?.response?.data?.detail || "Failed"}</p>}
    </div>
  );
}

function CertBadge({ verified }) {
  const [label, color] = verified ? ["ACTIVE", "var(--color-acid)"] : ["PENDING", "#d9a441"];
  return (
    <span className="mono text-[10px] rounded px-1.5 py-0.5 border"
      style={{ color, borderColor: color }} title="Edge TLS certificate status">{label}</span>
  );
}

function DnsRecordRow({ record }) {
  return (
    <div className="border border-[var(--color-line)] rounded px-3 py-2 text-xs space-y-1">
      <div className="mono text-[var(--color-muted)]">{record.type}</div>
      <CopyRow label="name" value={record.name} />
      <CopyRow label="value" value={record.value} />
    </div>
  );
}

function CopyRow({ label, value }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard?.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };
  return (
    <div className="flex items-center gap-2">
      <span className="text-[var(--color-muted)] w-12 shrink-0">{label}</span>
      <code className="mono text-[var(--color-fg)] truncate flex-1">{value}</code>
      <button onClick={copy} className="text-[10px] text-acid hover:underline linkbtn shrink-0">{copied ? "copied" : "copy"}</button>
    </div>
  );
}

function DnsDot({ ok }) {
  const [c, title] = ok === true ? ["var(--color-acid)", "DNS points here"]
    : ok === false ? ["var(--color-danger)", "DNS not pointing here yet"]
    : ["#5a6070", "DNS status unknown"];
  return <span className="dot shrink-0" title={title} style={{ background: c, boxShadow: `0 0 8px ${c}66` }} />;
}

function EnvEditor({ id }) {
  const qc = useQueryClient();
  const { data: vars = [] } = useQuery({ queryKey: ["env", id], queryFn: () => getEnv(id) });
  const [rows, setRows] = useState(null);
  const list = rows ?? vars;
  const mut = useMutation({
    mutationFn: () => putEnv(id, list.filter((r) => r.key)),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["env", id] }); setRows(null); },
  });
  const upd = (i, k, v) => setRows(list.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  return (
    <div className="max-w-2xl space-y-3">
      <p className="text-sm text-[var(--color-muted)]">Non-secret environment variables. Redeploy to apply.</p>
      {list.map((r, i) => (
        <div key={i} className="flex gap-2">
          <input className="input mono" value={r.key} placeholder="KEY" onChange={(e) => upd(i, "key", e.target.value)} />
          <input className="input mono" value={r.value} placeholder="value" onChange={(e) => upd(i, "value", e.target.value)} />
        </div>
      ))}
      <div className="flex gap-3 items-center">
        <button onClick={() => setRows([...list, { key: "", value: "" }])} className="text-acid text-sm linkbtn">+ add variable</button>
        <button onClick={() => mut.mutate()} className="btn btn-primary text-sm">{mut.isPending ? "Saving…" : "Save env"}</button>
      </div>
    </div>
  );
}

function SecretsEditor({ id }) {
  const qc = useQueryClient();
  const { data: keys = [] } = useQuery({ queryKey: ["secrets", id], queryFn: () => listSecretKeys(id) });
  const [k, setK] = useState(""); const [v, setV] = useState("");
  const addMut = useMutation({ mutationFn: () => putSecret(id, k, v), onSuccess: () => { qc.invalidateQueries({ queryKey: ["secrets", id] }); setK(""); setV(""); } });
  const delMut = useMutation({ mutationFn: (key) => deleteSecret(id, key), onSuccess: () => qc.invalidateQueries({ queryKey: ["secrets", id] }) });
  return (
    <div className="max-w-2xl space-y-4">
      <p className="text-sm text-[var(--color-muted)]">Encrypted at rest, injected as env at deploy. Values are never shown again.</p>
      <div className="card divide-y divide-[var(--color-line)]">
        {keys.map((key) => (
          <div key={key} className="flex items-center justify-between px-4 py-3">
            <span className="mono text-sm">{key}</span>
            <button onClick={() => delMut.mutate(key)} className="text-xs text-[var(--color-danger)] hover:underline linkbtn">delete</button>
          </div>
        ))}
        {keys.length === 0 && <div className="px-4 py-3 mono text-sm text-[var(--color-muted)]">No secrets.</div>}
      </div>
      <form onSubmit={(e) => { e.preventDefault(); addMut.mutate(); }} className="flex gap-2">
        <input className="input mono" value={k} placeholder="SECRET_KEY" onChange={(e) => setK(e.target.value)} />
        <input className="input mono" type="password" value={v} placeholder="value" onChange={(e) => setV(e.target.value)} />
        <button disabled={!k || !v} className="btn btn-primary shrink-0">Set</button>
      </form>
    </div>
  );
}

function NotifyCard({ id }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["notify", id], queryFn: () => getNotify(id) });
  const [email, setEmail] = useState(null);
  const val = email ?? data?.notify_email ?? "";
  const save = useMutation({
    mutationFn: () => setNotify(id, val),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["notify", id] }); setEmail(null); },
  });
  return (
    <div className="card p-6 space-y-3">
      <div className="text-sm font-medium">Email alerts</div>
      <p className="text-xs text-[var(--color-muted)]">
        Get emailed on deploy success/failure and down/recovered.
        {data && !data.email_configured && (
          <span className="text-[#febc2e]"> Sending isn't configured on this instance yet (no Resend key).</span>
        )}
      </p>
      <div className="flex gap-2">
        <input className="input mono" type="email" placeholder="you@example.com" value={val}
               onChange={(e) => setEmail(e.target.value)} />
        <button onClick={() => save.mutate()} className="btn btn-primary text-sm shrink-0">
          {save.isPending ? "Saving…" : "Save"}
        </button>
      </div>
      {data?.owner_login && <p className="mono text-[11px] text-[var(--color-muted)]">owner: @{data.owner_login}</p>}
    </div>
  );
}

function SettingsTab({ id, app }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [branch, setBranch] = useState(app.branch);
  const [auto, setAuto] = useState(app.auto_deploy);
  const [pinned, setPinned] = useState(app.pinned);
  const save = useMutation({ mutationFn: () => updateApp(id, { branch, auto_deploy: auto, pinned }), onSuccess: () => qc.invalidateQueries({ queryKey: ["app", id] }) });
  const del = useMutation({ mutationFn: () => deleteApp(id), onSuccess: () => { qc.invalidateQueries({ queryKey: ["apps"] }); nav("/"); } });
  return (
    <div className="max-w-2xl space-y-6">
      <div className="card p-6 space-y-4">
        <div>
          <div className="text-sm font-medium mb-1.5">Repository</div>
          <div className="mono text-xs text-[var(--color-muted)]">{app.repo_url}</div>
        </div>
        <label className="block">
          <div className="text-sm font-medium mb-1.5">Branch</div>
          <input className="input mono" value={branch} onChange={(e) => setBranch(e.target.value)} />
        </label>
        <label className="flex items-center gap-2.5 text-sm cursor-pointer select-none">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} className="accent-[var(--color-acid)]" />
          <span className="text-[var(--color-muted)]">Auto-deploy on push / CI</span>
        </label>
        {auto && !app.webhook_seen_at && (
          <p className="text-xs -mt-1" style={{ color: "#febc2e" }}>
            ⚠ No GitHub webhook has ever reached this instance for this repo, so
            auto-deploy won’t fire. Set it up in <b>Push-to-deploy</b> below.
          </p>
        )}
        <label className="flex items-center gap-2.5 text-sm cursor-pointer select-none">
          <input type="checkbox" checked={pinned} onChange={(e) => setPinned(e.target.checked)} className="accent-[var(--color-acid)]" />
          <span className="text-[var(--color-muted)]">
            Pin to node{" "}
            {pinned && (app.pinned_node
              ? <span className="mono text-[var(--color-fg)]">({app.pinned_node})</span>
              : <span className="text-[var(--color-muted)]">(set on next deploy)</span>)}
          </span>
        </label>
        <p className="text-xs text-[var(--color-muted)] -mt-1">
          For stateful apps: keeps every container on the one node it runs on, so
          node-local data isn’t orphaned by a reschedule.
        </p>
        <button onClick={() => save.mutate()} className="btn btn-primary text-sm">{save.isPending ? "Saving…" : "Save"}</button>
      </div>

      <div className="card p-6 space-y-2">
        <div className="text-sm font-medium">Push-to-deploy</div>
        {app.webhook_seen_at ? (
          <p className="mono text-xs" style={{ color: "var(--color-acid)" }}>
            ✓ webhook connected · last event {new Date(app.webhook_seen_at).toLocaleString()}
          </p>
        ) : (
          <p className="mono text-xs" style={{ color: "#febc2e" }}>
            ⚠ no webhook received yet — GitHub pings this URL the moment you save
            the webhook, so this turns green within seconds of adding it.
          </p>
        )}
        <p className="text-xs text-[var(--color-muted)]">
          With auto-deploy on, point a GitHub webhook at the URL below (content-type
          <span className="mono"> application/json</span>, secret = <span className="mono">KOYRA_WEBHOOK_SECRET</span>),
          then pick which event it sends for <span className="mono">{app.branch}</span>:
        </p>
        <ul className="text-xs text-[var(--color-muted)] list-disc pl-5 space-y-0.5">
          <li><span className="mono text-[var(--color-fg)]">push</span> — deploy on every push (repos without CI).</li>
          <li><span className="mono text-[var(--color-fg)]">workflow_run</span> — deploy only after a GitHub Actions run completes successfully (repos with CI).</li>
        </ul>
        <div className="mono text-xs bg-[var(--color-ink)] border border-[var(--color-line)] rounded px-3 py-2 break-all">
          {window.location.origin}/api/webhooks/github
        </div>
      </div>

      <div className="card p-6 space-y-1.5">
        <div className="text-sm font-medium">How it builds</div>
        <p className="text-xs text-[var(--color-muted)]">
          Each deploy builds a container image from your repo (its own
          <span className="mono"> Dockerfile</span>, or one koyracloud generates from
          <span className="mono"> .paas/app.yaml</span>), pushes it to the internal registry, and runs it
          on the swarm. Watch the <b className="text-[var(--color-fg)]">Deploys</b> tab for live build → push → deploy logs.
        </p>
      </div>

      <NotifyCard id={id} />

      <div className="card p-6 border-[rgba(255,107,107,0.3)]">
        <div className="text-sm font-medium mb-1">Danger zone</div>
        <p className="text-xs text-[var(--color-muted)] mb-4">Deletes the app, its env/secrets/domains and tears down the swarm stack.</p>
        <button onClick={() => { if (confirm(`Delete ${app.name}? This cannot be undone.`)) del.mutate(); }} className="btn btn-danger text-sm">
          {del.isPending ? "Deleting…" : "Delete app"}
        </button>
      </div>
    </div>
  );
}
