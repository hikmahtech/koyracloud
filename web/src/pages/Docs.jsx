import { PublicNav, Footer } from "../components/Chrome.jsx";

function Code({ children, label }) {
  return (
    <div className="card overflow-hidden my-4">
      {label && (
        <div className="px-4 py-2 border-b border-[var(--color-line)] mono text-xs text-[var(--color-muted)]">
          {label}
        </div>
      )}
      <pre className="mono text-[12.5px] leading-relaxed p-4 overflow-auto text-[#cdd3dd] m-0">{children}</pre>
    </div>
  );
}

const NAV = [
  ["quickstart", "Quickstart"],
  ["manifest", "The manifest"],
  ["fields", "Manifest fields"],
  ["runtime", "Runtimes & build"],
  ["domains", "Custom domains"],
  ["secrets", "Secrets & env"],
  ["persistence", "Persistence"],
  ["architecture", "How it works"],
];

function Field({ name, req, children }) {
  return (
    <tr className="border-t border-[var(--color-line)] align-top">
      <td className="py-2.5 pr-4 mono text-acid whitespace-nowrap">{name}</td>
      <td className="py-2.5 pr-4 mono text-xs text-[var(--color-muted)]">{req ? "required" : "optional"}</td>
      <td className="py-2.5 text-sm text-[var(--color-fg)]">{children}</td>
    </tr>
  );
}

export default function Docs() {
  return (
    <div className="grid-bg min-h-screen">
      <PublicNav />
      <div className="max-w-6xl mx-auto px-6 py-12 grid lg:grid-cols-[200px_1fr] gap-12">
        {/* sidebar */}
        <aside className="hidden lg:block">
          <div className="sticky top-24">
            <div className="eyebrow mb-4">Documentation</div>
            <nav className="flex flex-col gap-1.5 text-sm">
              {NAV.map(([id, label]) => (
                <a key={id} href={`#${id}`}
                   className="text-[var(--color-muted)] hover:text-[var(--color-fg)] no-underline py-1">
                  {label}
                </a>
              ))}
            </nav>
          </div>
        </aside>

        <article className="max-w-3xl prose-koyra">
          <div className="eyebrow">Get started</div>
          <h1 className="font-display text-4xl mt-3 mb-2">Deploy a repo</h1>
          <p className="text-[var(--color-muted)]">
            koyracloud runs your app from a single shared runtime image. You describe how
            to build and start it in a <span className="mono text-acid">.paas/app.yaml</span> manifest;
            the control plane clones, builds, migrates, runs and routes it.
          </p>

          <Section id="quickstart" title="Quickstart">
            <ol className="list-decimal ml-5 space-y-2 text-[var(--color-fg)]">
              <li>Add <span className="mono text-acid">.paas/app.yaml</span> to your repo (see below) and push.</li>
              <li>Sign in, click <b>New App</b>, paste the repo URL and branch.</li>
              <li>Open <b>Secrets</b> and set anything your app needs (e.g. <span className="mono">SECRET_KEY</span>).</li>
              <li>Hit <b>Deploy</b> and watch the live log. Your app comes up at
                <span className="mono text-acid"> &lt;name&gt;.apps.koyracloud.com</span>.</li>
            </ol>
          </Section>

          <Section id="manifest" title="The manifest">
            <p className="text-[var(--color-muted)]">A complete example for a FastAPI + Vite app:</p>
            <Code label=".paas/app.yaml">{`name: lens-inventory
runtime: python+node
subdomain: lens.apps.koyracloud.com   # default host (optional)
port: 8000
build:
  - pip install -r requirements.txt
  - bash -c "cd web && npm ci && npm run build"
predeploy:
  - alembic upgrade head
start: uvicorn app.main:app --host 0.0.0.0 --port 8000
persist:
  - data
healthcheck: /health
env:
  CORS_ORIGINS: https://lens.apps.koyracloud.com
secrets:
  - SECRET_KEY`}</Code>
          </Section>

          <Section id="fields" title="Manifest fields">
            <div className="card overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <tbody>
                  <Field name="name" req>Stack + service identity. Alphanumeric, <span className="mono">-</span>, <span className="mono">_</span>.</Field>
                  <Field name="runtime" req><span className="mono">python</span>, <span className="mono">node</span>, or <span className="mono">python+node</span>.</Field>
                  <Field name="start" req>The command that starts your server (becomes PID 1). Must bind <span className="mono">0.0.0.0</span> on <span className="mono">port</span>.</Field>
                  <Field name="port" req>Container port Traefik routes to.</Field>
                  <Field name="build">Commands run once when dependencies change (hashed over <span className="mono">requirements.txt</span> + <span className="mono">package-lock.json</span>).</Field>
                  <Field name="predeploy">Commands run on every deploy before start — e.g. migrations. Must be idempotent.</Field>
                  <Field name="subdomain">Default host. Falls back to <span className="mono">&lt;name&gt;.apps.koyracloud.com</span>. Manage more in the Domains tab.</Field>
                  <Field name="persist">Directories that survive redeploys (gitignored, on the volume).</Field>
                  <Field name="healthcheck">HTTP path probed for liveness, e.g. <span className="mono">/health</span>.</Field>
                  <Field name="env">Non-secret environment defaults baked into the deploy.</Field>
                  <Field name="secrets">Names of secrets to inject at deploy. Set their values in the UI — never commit them.</Field>
                </tbody>
              </table>
            </div>
          </Section>

          <Section id="runtime" title="Runtimes & build">
            <p className="text-[var(--color-muted)]">
              Every app runs the same image: <span className="mono">python:3.12</span> + <span className="mono">node:22</span> + <span className="mono">git</span>.
              On start, the entrypoint syncs your repo to the volume, and if the dependency hash
              changed it runs your <span className="mono">build</span> steps, caching the venv,
              <span className="mono"> node_modules</span> and built assets. Unchanged restarts skip
              the build entirely, so reschedules are fast and offline-safe.
            </p>
            <p className="text-[var(--color-muted)] mt-3">
              Single-container model: serve your built frontend from your backend (e.g. FastAPI
              <span className="mono"> StaticFiles</span>) so API and SPA share one origin and port.
            </p>
          </Section>

          <Section id="domains" title="Custom domains">
            <p className="text-[var(--color-muted)]">
              Every app gets <span className="mono text-acid">&lt;name&gt;.apps.koyracloud.com</span> automatically.
              To attach your own domain, open the app's <b>Domains</b> tab and add it, then point DNS at the homelab:
            </p>
            <Code label="DNS (your registrar)">{`Type   Host        Value
A      yourdomain  <your server's public IP>`}</Code>
            <p className="text-[var(--color-muted)]">
              Traefik mints a Let's Encrypt certificate on the first request — no extra config.
              The Domains tab shows whether DNS already points here. Set any domain as <b>primary</b>;
              all attached domains route to the same app.
            </p>
          </Section>

          <Section id="secrets" title="Secrets & env">
            <p className="text-[var(--color-muted)]">
              List secret <i>names</i> in the manifest; set their <i>values</i> in the app's
              <b> Secrets</b> tab. They're encrypted at rest (Fernet) and injected as environment
              variables at deploy time. Non-sensitive config goes in <span className="mono">env:</span>.
            </p>
          </Section>

          <Section id="persistence" title="Persistence">
            <p className="text-[var(--color-muted)]">
              Directories under <span className="mono">persist:</span> live on the NFS-backed volume and
              survive redeploys and reschedules. A SQLite database at <span className="mono">./data/app.db</span>,
              for example, persists across deploys when <span className="mono">data</span> is listed.
            </p>
          </Section>

          <Section id="architecture" title="How it works">
            <Code>{`repo (.paas/app.yaml)
   │  control plane clones → NFS volume @ commit
   ▼
one-off build container  (pip / npm / vite, cached by dep-hash)
   ▼
docker stack deploy  →  service (Traefik labels, secrets, persist)
   ▼
entrypoint: sync · skip build · predeploy (migrate) · exec start
   ▼
https://<host>  ·  per-host TLS minted on first request`}</Code>
            <p className="text-[var(--color-muted)]">
              The control plane is a single service on the swarm manager that renders a Docker
              stack from your manifest and drives the cluster. Builds run in a one-off container so
              the served app never races its own healthcheck.
            </p>
          </Section>

          <div className="mt-12 card p-6 flex items-center justify-between flex-wrap gap-4">
            <span className="text-[var(--color-muted)]">Ready?</span>
            <a href="/api/auth/login" className="btn btn-primary">Sign in & deploy →</a>
          </div>
        </article>
      </div>
      <Footer />
    </div>
  );
}

function Section({ id, title, children }) {
  return (
    <section id={id} className="mt-12 scroll-mt-24">
      <h2 className="font-display text-2xl mb-3">{title}</h2>
      {children}
    </section>
  );
}
