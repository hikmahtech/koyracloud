import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createApp, listGithubRepos } from "../api";

export default function NewApp() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [form, setForm] = useState({ name: "", repo_url: "", branch: "main", auto_deploy: false });

  const mut = useMutation({
    mutationFn: () => createApp(form),
    onSuccess: (app) => {
      qc.invalidateQueries({ queryKey: ["apps"] });
      nav(`/apps/${app.id}`);
    },
  });

  const set = (k) => (e) =>
    setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  // Repos the koyracloud GitHub App can read for this user (Vercel-style
  // picker). `enabled` is false on installs still using a plain OAuth App.
  const { data: gh } = useQuery({ queryKey: ["github-repos"], queryFn: listGithubRepos, retry: false });
  const pickRepo = (e) => {
    const r = gh?.repos.find((x) => x.full_name === e.target.value);
    if (!r) return;
    const name = form.name || r.full_name.split("/")[1].toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
    setForm({ ...form, name, repo_url: r.url, branch: r.default_branch });
  };

  return (
    <div className="max-w-xl">
      <Link to="/" className="mono text-xs text-[var(--color-muted)] hover:text-[var(--color-fg)] no-underline">← apps</Link>
      <div className="eyebrow mt-4">New app</div>
      <h1 className="font-display text-3xl mt-2 mb-1">Connect a repository</h1>
      <p className="text-sm text-[var(--color-muted)] mb-7">
        The repo needs a <span className="mono text-acid">.paas/app.yaml</span> manifest — or
        just an <span className="mono">index.html</span> to be served as a static site.
        It gets <span className="mono">&lt;name&gt;-&lt;token&gt;.apps.example.com</span> by default.
      </p>

      <form onSubmit={(e) => { e.preventDefault(); mut.mutate(); }} className="card p-6 space-y-5">
        <Field label="Name" hint="lowercase, used for the subdomain & stack">
          <input required value={form.name} onChange={set("name")} placeholder="lens-inventory" className="input mono" />
        </Field>
        {gh?.enabled && (
          <Field label="GitHub repository" hint={gh.connected ? "read-only via the GitHub App" : ""}>
            {gh.connected ? (
              <>
                <select defaultValue="" onChange={pickRepo} className="input mono">
                  <option value="">{gh.repos.length ? "Pick a repo…" : "No repos yet — install the app below"}</option>
                  {gh.repos.map((r) => (
                    <option key={r.full_name} value={r.full_name}>{r.full_name}{r.private ? "  (private)" : ""}</option>
                  ))}
                </select>
                <a href={gh.install_url} target="_blank" rel="noreferrer"
                  className="inline-block mt-1.5 mono text-[11px] text-[var(--color-muted)] hover:text-[var(--color-fg)]">
                  Add or manage repos on GitHub ↗
                </a>
              </>
            ) : (
              <p className="text-xs text-[var(--color-muted)]">
                Sign out and back in to connect your GitHub repos, then install the app on the ones to deploy.
              </p>
            )}
          </Field>
        )}
        <Field label="Repository URL">
          <input required value={form.repo_url} onChange={set("repo_url")} placeholder="https://github.com/owner/repo" className="input mono" />
        </Field>
        <Field label="Branch">
          <input value={form.branch} onChange={set("branch")} className="input mono" />
        </Field>
        <label className="flex items-center gap-2.5 text-sm cursor-pointer select-none">
          <input type="checkbox" checked={form.auto_deploy} onChange={set("auto_deploy")} className="accent-[var(--color-acid)]" />
          <span className="text-[var(--color-muted)]">Auto-deploy on push</span>
        </label>
        {form.auto_deploy && (
          <p className="text-xs text-[var(--color-muted)] -mt-2">
            Needs a GitHub webhook on the repo — setup instructions are on the
            app’s Settings tab after create.
          </p>
        )}
        {mut.isError && (
          <p className="text-[var(--color-danger)] text-sm">{mut.error?.response?.data?.detail || "Failed to create app"}</p>
        )}
        <button disabled={mut.isPending} className="btn btn-primary w-full justify-center">
          {mut.isPending ? "Creating…" : "Create app"}
        </button>
      </form>
    </div>
  );
}

function Field({ label, hint, children }) {
  return (
    <label className="block">
      <div className="flex items-baseline justify-between mb-1.5">
        <span className="text-sm font-medium">{label}</span>
        {hint && <span className="mono text-[11px] text-[var(--color-muted)]">{hint}</span>}
      </div>
      {children}
    </label>
  );
}
