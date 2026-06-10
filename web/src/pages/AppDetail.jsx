import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getApp, listDeploys, triggerDeploy, rollback, updateApp, deleteApp,
  getEnv, putEnv, listSecretKeys, putSecret, deleteSecret,
  listDomains, addDomain, setPrimaryDomain, deleteDomain, getConfig,
  getStatus, getRuntimeLogs, getUptime, getAnalytics, setAnalytics,
} from "../api";
import { StatusBadge } from "./AppsList";

const TABS = ["deploys", "analytics", "logs", "domains", "env", "secrets", "settings"];

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
                  className={`px-4 py-2.5 text-sm capitalize bg-transparent border-0 cursor-pointer -mb-px border-b-2 ${
                    tab === t ? "border-[var(--color-acid)] text-[var(--color-fg)]" : "border-transparent text-[var(--color-muted)] hover:text-[var(--color-fg)]"
                  }`}>{t}</button>
        ))}
      </div>

      {tab === "deploys" && <DeployHistory deploys={deploys} onRollback={(d) => rollbackMut.mutate(d)} />}
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
                className="mono text-xs text-acid hover:underline bg-transparent border-0 cursor-pointer disabled:opacity-50">
          {isFetching ? "refreshing…" : "refresh"}
        </button>
      </div>
      <pre ref={box} className="mono text-[12px] leading-relaxed p-4 h-[28rem] overflow-auto text-[#cdd3dd] m-0">
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
        <span className="mono text-xs text-[var(--color-muted)]">deploy #{deployId}</span>
        {done && <StatusBadge status={done} />}
      </div>
      <pre ref={box} className="mono text-[12px] leading-relaxed p-4 h-64 overflow-auto text-[#cdd3dd] m-0">
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
          <th className="px-4 py-3">#</th><th>Status</th><th>Ref</th><th>Commit</th><th></th>
        </tr></thead>
        <tbody>
          {deploys.map((d) => (
            <tr key={d.id} className="border-t border-[var(--color-line)]">
              <td className="px-4 py-3 mono">{d.id}</td>
              <td><StatusBadge status={d.status} /></td>
              <td className="mono text-xs text-[var(--color-muted)]">{d.ref?.slice(0, 12)}</td>
              <td className="mono text-xs text-[var(--color-muted)]">{d.commit?.slice(0, 12) || "—"}</td>
              <td className="text-right pr-4">
                {d.commit && (
                  <button onClick={() => onRollback(d.id)} className="text-acid hover:underline text-xs bg-transparent border-0 cursor-pointer">
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

function DomainsTab({ id }) {
  const qc = useQueryClient();
  const { data: domains = [] } = useQuery({ queryKey: ["domains", id], queryFn: () => listDomains(id) });
  const { data: config } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const ip = config?.public_ip || "your server's IP";
  const [host, setHost] = useState("");
  const inval = () => qc.invalidateQueries({ queryKey: ["domains", id] });
  const addMut = useMutation({ mutationFn: () => addDomain(id, host), onSuccess: () => { setHost(""); inval(); qc.invalidateQueries({ queryKey: ["app", id] }); } });
  const primMut = useMutation({ mutationFn: (did) => setPrimaryDomain(id, did), onSuccess: () => { inval(); qc.invalidateQueries({ queryKey: ["app", id] }); } });
  const delMut = useMutation({ mutationFn: (did) => deleteDomain(id, did), onSuccess: () => { inval(); qc.invalidateQueries({ queryKey: ["app", id] }); } });

  return (
    <div className="max-w-2xl space-y-5">
      <p className="text-sm text-[var(--color-muted)]">
        Point an A record at <span className="mono text-acid">{ip}</span>, then add the domain here.
        Traefik mints TLS on first request. <b className="text-[var(--color-fg)]">Redeploy</b> to apply changes.
      </p>
      <div className="card divide-y divide-[var(--color-line)]">
        {domains.map((d) => (
          <div key={d.id} className="flex items-center justify-between px-4 py-3">
            <div className="flex items-center gap-3 min-w-0">
              <DnsDot ok={d.dns_ok} />
              <a href={`https://${d.host}`} target="_blank" rel="noreferrer" className="mono text-sm no-underline text-[var(--color-fg)] hover:text-acid truncate">{d.host}</a>
              {d.is_primary && <span className="mono text-[10px] text-acid border border-[var(--color-line)] rounded px-1.5 py-0.5">PRIMARY</span>}
            </div>
            <div className="flex items-center gap-3 shrink-0">
              {!d.is_primary && <button onClick={() => primMut.mutate(d.id)} className="text-xs text-[var(--color-muted)] hover:text-[var(--color-fg)] bg-transparent border-0 cursor-pointer">set primary</button>}
              <button onClick={() => delMut.mutate(d.id)} className="text-xs text-[var(--color-danger)] hover:underline bg-transparent border-0 cursor-pointer">remove</button>
            </div>
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
        <button onClick={() => setRows([...list, { key: "", value: "" }])} className="text-acid text-sm bg-transparent border-0 cursor-pointer">+ add variable</button>
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
            <button onClick={() => delMut.mutate(key)} className="text-xs text-[var(--color-danger)] hover:underline bg-transparent border-0 cursor-pointer">delete</button>
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

function SettingsTab({ id, app }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [branch, setBranch] = useState(app.branch);
  const [auto, setAuto] = useState(app.auto_deploy);
  const save = useMutation({ mutationFn: () => updateApp(id, { branch, auto_deploy: auto }), onSuccess: () => qc.invalidateQueries({ queryKey: ["app", id] }) });
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
          <span className="text-[var(--color-muted)]">Auto-deploy on push</span>
        </label>
        <button onClick={() => save.mutate()} className="btn btn-primary text-sm">{save.isPending ? "Saving…" : "Save"}</button>
      </div>

      <div className="card p-6 space-y-2">
        <div className="text-sm font-medium">Push-to-deploy</div>
        <p className="text-xs text-[var(--color-muted)]">
          With auto-deploy on, a push to <span className="mono">{app.branch}</span> redeploys this app.
          Point a GitHub webhook (or your GitHub App's webhook) at this URL, content-type
          <span className="mono"> application/json</span>, secret = your <span className="mono">KOYRA_WEBHOOK_SECRET</span>:
        </p>
        <div className="mono text-xs bg-[var(--color-ink)] border border-[var(--color-line)] rounded px-3 py-2 break-all">
          {window.location.origin}/api/webhooks/github
        </div>
      </div>

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
