import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createApp } from "../api";

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

  return (
    <div className="max-w-xl">
      <Link to="/" className="mono text-xs text-[var(--color-muted)] hover:text-[var(--color-fg)] no-underline">← apps</Link>
      <div className="eyebrow mt-4">New app</div>
      <h1 className="font-display text-3xl mt-2 mb-1">Connect a repository</h1>
      <p className="text-sm text-[var(--color-muted)] mb-7">
        The repo must contain a <span className="mono text-acid">.paas/app.yaml</span> manifest.
        It gets <span className="mono">&lt;name&gt;.apps.example.com</span> by default.
      </p>

      <form onSubmit={(e) => { e.preventDefault(); mut.mutate(); }} className="card p-6 space-y-5">
        <Field label="Name" hint="lowercase, used for the subdomain & stack">
          <input required value={form.name} onChange={set("name")} placeholder="lens-inventory" className="input mono" />
        </Field>
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
