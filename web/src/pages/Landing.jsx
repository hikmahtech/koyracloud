import { Link } from "react-router-dom";
import { PublicNav, Footer } from "../components/Chrome.jsx";

const MANIFEST = `name: lens-inventory
runtime: python+node
subdomain: lens.apps.example.com
port: 8000
build:
  - pip install -r requirements.txt
  - bash -c "cd web && npm ci && npm run build"
predeploy:
  - alembic upgrade head
start: uvicorn app.main:app --host 0.0.0.0 --port 8000
persist: [data]
healthcheck: /health
secrets: [SECRET_KEY]`;

const STEPS = [
  { n: "01", t: "Commit a manifest", d: "Drop a .paas/app.yaml in your repo — build, start, port, persistent dirs, secrets." },
  { n: "02", t: "Connect the repo", d: "Point koyracloud at it. One shared runtime image builds every app on the volume — no per-app Dockerfile." },
  { n: "03", t: "It deploys", d: "Clone → build → migrate → run, behind Traefik with an auto-TLS subdomain. Logs, history, rollback included." },
];

const FEATURES = [
  ["Bring a repo, not a Dockerfile", "One python+node+git runtime image runs everything. Dependencies are hashed and cached on the volume — restarts are instant and offline-safe."],
  ["Auto-TLS on every subdomain", "Apps land on a unique <name>-<token>.apps.example.com with TLS handled for you. Attach your own domains in a click."],
  ["Secrets, encrypted at rest", "Fernet-encrypted in the control plane, injected at deploy. Never in your repo, never in the image."],
  ["Live logs, history, rollback", "Stream the build and deploy as it happens. Every deploy is recorded; roll back to any commit."],
  ["Persistent storage", "Declare persist dirs in the manifest; they survive redeploys on NFS-backed volumes."],
  ["Single-operator, by design", "GitHub OAuth behind an allowlist. Your homelab, your apps, your rules — no multi-tenant ceremony."],
];

export default function Landing() {
  return (
    <div className="grid-bg min-h-screen">
      <PublicNav />

      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="glow absolute inset-x-0 top-0 h-[420px] pointer-events-none" />
        <div className="max-w-6xl mx-auto px-6 pt-20 pb-16 grid lg:grid-cols-[1.05fr_1fr] gap-12 items-center">
          <div>
            <div className="eyebrow rise" style={{ animationDelay: "0ms" }}>Self-hosted PaaS · for your swarm</div>
            <h1 className="rise mt-5 text-5xl sm:text-6xl leading-[0.98] font-semibold"
                style={{ animationDelay: "60ms" }}>
              Your own Vercel,<br />running on <span className="text-acid">your</span> metal.
            </h1>
            <p className="rise mt-6 text-lg text-[var(--color-muted)] max-w-xl" style={{ animationDelay: "140ms" }}>
              Connect a git repo, get a running app behind HTTPS — with builds, persistent
              storage, injected secrets, live logs and rollback. No per-app Dockerfile,
              runner, or registry. Just a manifest.
            </p>
            <div className="rise mt-8 flex flex-wrap gap-3" style={{ animationDelay: "220ms" }}>
              <a href="/api/auth/login" className="btn btn-primary">Sign in with GitHub →</a>
              <Link to="/docs" className="btn btn-ghost">Read the docs</Link>
            </div>
          </div>

          {/* Manifest card */}
          <div className="rise" style={{ animationDelay: "300ms" }}>
            <div className="card overflow-hidden shadow-2xl">
              <div className="flex items-center gap-2 px-4 py-3 border-b border-[var(--color-line)]">
                <span className="dot" style={{ background: "#ff5f57" }} />
                <span className="dot" style={{ background: "#febc2e" }} />
                <span className="dot" style={{ background: "var(--color-acid)" }} />
                <span className="ml-2 mono text-xs text-[var(--color-muted)]">.paas/app.yaml</span>
              </div>
              <pre className="mono text-[12.5px] leading-relaxed p-5 overflow-auto text-[#cdd3dd] m-0">{MANIFEST}</pre>
            </div>
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="max-w-6xl mx-auto px-6 py-16">
        <div className="eyebrow">How it works</div>
        <div className="mt-8 grid md:grid-cols-3 gap-5">
          {STEPS.map((s) => (
            <div key={s.n} className="card p-6">
              <div className="mono text-acid text-sm">{s.n}</div>
              <div className="font-display text-xl mt-3">{s.t}</div>
              <p className="text-[var(--color-muted)] text-sm mt-2 leading-relaxed">{s.d}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section className="max-w-6xl mx-auto px-6 py-8">
        <div className="eyebrow">What you get</div>
        <div className="mt-8 grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {FEATURES.map(([t, d]) => (
            <div key={t} className="card p-6 hover:border-[#3a4150] transition">
              <div className="font-display text-lg leading-snug">{t}</div>
              <p className="text-[var(--color-muted)] text-sm mt-2 leading-relaxed">{d}</p>
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="max-w-6xl mx-auto px-6 py-20">
        <div className="card p-10 text-center relative overflow-hidden">
          <div className="glow absolute inset-x-0 top-0 h-40 pointer-events-none" />
          <h2 className="font-display text-3xl sm:text-4xl">Ship your next repo in minutes.</h2>
          <p className="text-[var(--color-muted)] mt-3">Add a manifest, connect the repo, watch it go live.</p>
          <div className="mt-7 flex justify-center gap-3">
            <a href="/api/auth/login" className="btn btn-primary">Get started</a>
            <Link to="/docs" className="btn btn-ghost">Manifest reference</Link>
          </div>
        </div>
      </section>

      <Footer />
    </div>
  );
}
