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
  ["static", "Static sites"],
  ["domains", "Custom domains"],
  ["analytics", "Analytics & uptime"],
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
            koyracloud builds your app into a container image, pushes it to a built-in
            registry, and runs it on the swarm. You describe how to build and start it in a
            <span className="mono text-acid"> .paas/app.yaml</span> manifest — or bring your own
            <span className="mono"> Dockerfile</span>.
          </p>

          <Section id="quickstart" title="Quickstart">
            <ol className="list-decimal ml-5 space-y-2 text-[var(--color-fg)]">
              <li>Add <span className="mono text-acid">.paas/app.yaml</span> to your repo (see below) and push.</li>
              <li>Sign in, click <b>New App</b>, paste the repo URL and branch.</li>
              <li>Open <b>Secrets</b> and set anything your app needs (e.g. <span className="mono">SECRET_KEY</span>).</li>
              <li>Hit <b>Deploy</b> and watch the live log. Your app comes up at
                <span className="mono text-acid"> &lt;name&gt;.apps.example.com</span>.</li>
            </ol>
          </Section>

          <Section id="manifest" title="The manifest">
            <p className="text-[var(--color-muted)]">A complete example for a FastAPI + Vite app:</p>
            <Code label=".paas/app.yaml">{`name: lens-inventory
runtime: python+node
subdomain: lens.apps.example.com   # default host (optional)
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
  CORS_ORIGINS: https://lens.apps.example.com
secrets:
  - SECRET_KEY`}</Code>
          </Section>

          <Section id="fields" title="Manifest fields">
            <div className="card overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <tbody>
                  <Field name="name" req>Stack + service identity. Alphanumeric, <span className="mono">-</span>, <span className="mono">_</span>.</Field>
                  <Field name="runtime" req><span className="mono">python</span>, <span className="mono">node</span>, <span className="mono">python+node</span>, <span className="mono">static</span>, or <span className="mono">dockerfile</span>.</Field>
                  <Field name="dockerfile">Path to your repo's own Dockerfile (or set <span className="mono">runtime: dockerfile</span> for <span className="mono">./Dockerfile</span>). koyracloud builds it as-is; <span className="mono">build</span>/<span className="mono">start</span> are ignored.</Field>
                  <Field name="start">The command that starts your server (becomes the container command). Must bind <span className="mono">0.0.0.0</span> on <span className="mono">port</span>. Not needed for <span className="mono">static</span> / <span className="mono">dockerfile</span>.</Field>
                  <Field name="static_dir">For <span className="mono">runtime: static</span>: directory to serve. Auto-detected (<span className="mono">dist/build/public/out/_site</span> or repo root) if omitted.</Field>
                  <Field name="port" req>Container port Traefik routes to.</Field>
                  <Field name="build">Image build steps (become <span className="mono">RUN</span> layers). Cached by Docker's layer cache; unchanged deps aren't reinstalled.</Field>
                  <Field name="predeploy">Commands run on every start before the app — e.g. migrations. Must be idempotent.</Field>
                  <Field name="subdomain">Default host. Falls back to <span className="mono">&lt;name&gt;-&lt;token&gt;.apps.example.com</span> (a random token keeps names from colliding). Manage more in the Domains tab.</Field>
                  <Field name="persist">Directories that survive redeploys (NFS-backed volumes, mounted into the container).</Field>
                  <Field name="healthcheck">HTTP path probed for liveness, e.g. <span className="mono">/health</span>.</Field>
                  <Field name="env">Non-secret environment defaults baked into the deploy.</Field>
                  <Field name="secrets">Names of secrets to inject at deploy. Set their values in the UI — never commit them.</Field>
                </tbody>
              </table>
            </div>
          </Section>

          <Section id="runtime" title="Runtimes & build">
            <p className="text-[var(--color-muted)]">
              Each deploy builds a per-app image — from a <span className="mono">Dockerfile</span> koyracloud
              generates (base <span className="mono">python:3.12</span> + <span className="mono">node:22</span>, your
              <span className="mono"> build</span> steps as layers) or your repo's own. It's built on local
              disk (off NFS, layer-cached), pushed to the internal registry, and the container runs from
              the image — so the app reads no code over NFS and can run on any node.
            </p>
            <p className="text-[var(--color-muted)] mt-3">
              Build-time env (<span className="mono">NEXT_PUBLIC_*</span>, <span className="mono">VITE_*</span>) is
              passed as build args, so client bundles bake the right values. Secrets are injected at run time
              only. Single-container model: serve your built frontend from your backend (e.g. FastAPI
              <span className="mono"> StaticFiles</span>) so API and SPA share one origin and port.
            </p>
          </Section>

          <Section id="dockerfile" title="Bring your own Dockerfile">
            <p className="text-[var(--color-muted)]">
              Already containerized? Set <span className="mono">runtime: dockerfile</span> and koyracloud builds
              your image as-is and runs it as a managed service — you still get domains, env/secrets, logs and rollback.
            </p>
            <Code label=".paas/app.yaml">{`name: my-app
runtime: dockerfile        # or: dockerfile: docker/Dockerfile
port: 8000
healthcheck: /health
secrets:
  - DATABASE_URL`}</Code>
          </Section>

          <Section id="deploy" title="Push-to-deploy">
            <p className="text-[var(--color-muted)]">
              Turn on <b>Auto-deploy</b> in the app's Settings and add a GitHub webhook to your repo
              (the Settings tab shows the URL + secret). Choose the event it sends:
              <span className="mono"> push</span> deploys on every push; <span className="mono">workflow_run</span>
              deploys only after a GitHub Actions run finishes successfully — so repos with CI deploy after it passes.
            </p>
          </Section>

          <Section id="static" title="Static sites (Netlify-style)">
            <p className="text-[var(--color-muted)]">
              For frontend-only / static sites, koyracloud serves the files itself —
              no server command needed. Use <span className="mono">runtime: static</span>:
            </p>
            <Code label=".paas/app.yaml">{`name: my-site
runtime: static
# optional: build a frontend first, then serve the output
build:
  - bash -c "npm ci && npm run build"
static_dir: dist        # auto-detected if omitted`}</Code>
            <p className="text-[var(--color-muted)]">
              <b className="text-[var(--color-fg)]">Zero-config:</b> if a repo has
              <span className="mono"> index.html</span> (at the root or in
              <span className="mono"> dist/build/public/out/_site</span>) and <i>no</i>
              manifest at all, koyracloud auto-detects it as a static site and serves
              it — just connect the repo and deploy. SPA client-side routes fall back to
              <span className="mono"> index.html</span>, and the analytics beacon is
              injected automatically.
            </p>
          </Section>

          <Section id="domains" title="Custom domains">
            <p className="text-[var(--color-muted)]">
              Every app gets <span className="mono text-acid">&lt;name&gt;.apps.example.com</span> automatically.
              To attach your own domain, open the app's <b>Domains</b> tab and add it. If Cloudflare for SaaS
              is configured, koyracloud registers it as a custom hostname and shows the two CNAME records to
              add at <i>your</i> registrar — the Cloudflare edge then mints and auto-renews TLS (Vercel-style,
              no nameserver move):
            </p>
            <Code label="DNS (your registrar)">{`Type   Host                    Value
CNAME  yourdomain              origin.<your-saas-zone>
CNAME  _acme-challenge.yourdomain   <shown in the Domains tab>`}</Code>
            <p className="text-[var(--color-muted)]">
              The Domains tab shows each domain's cert status (Pending → Active). Set any domain as
              <b> primary</b>; all attached domains route to the same app. (Without Cloudflare for SaaS,
              point an A record at the host and Traefik mints a Let's Encrypt cert instead.)
            </p>
          </Section>

          <Section id="secrets" title="Secrets & env">
            <p className="text-[var(--color-muted)]">
              List secret <i>names</i> in the manifest; set their <i>values</i> in the app's
              <b> Secrets</b> tab. They're encrypted at rest (Fernet) and injected as environment
              variables at deploy time. Non-sensitive config goes in <span className="mono">env:</span>.
            </p>
          </Section>

          <Section id="analytics" title="Analytics & uptime">
            <p className="text-[var(--color-muted)]">
              Every app gets built-in, cookieless <b className="text-[var(--color-fg)]">analytics</b>
              (pageviews, unique visitors, top pages/referrers) and an
              <b className="text-[var(--color-fg)]"> uptime monitor</b> (koyracloud probes your
              app and tracks up/down + 24h %). Both are on the app's tabs and header.
            </p>
            <p className="text-[var(--color-muted)] mt-3">
              Static sites get the analytics beacon injected automatically. For dynamic
              apps, paste the one-line snippet from the <b>Analytics</b> tab. Analytics is
              opt-out per app. Set an email in <b>Settings → Email alerts</b> to be notified
              on deploy success/failure and down/recovered (when the instance has email configured).
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
