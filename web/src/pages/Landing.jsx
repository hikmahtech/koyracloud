import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PublicNav, Footer } from "../components/Chrome.jsx";
import { joinWaitlist } from "../api.js";

const REPO_URL = "https://github.com/hikmahtech/koyracloud";

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
  { n: "01", t: "Commit a manifest", d: "Drop a .paas/app.yaml in your repo — build, start, port, persistent dirs, secrets. Or point at your own Dockerfile." },
  { n: "02", t: "Connect the repo", d: "Point koyracloud at it. Each deploy builds a per-app container image — from your manifest's steps or your Dockerfile — and pushes it to a built-in registry." },
  { n: "03", t: "It deploys", d: "Swarm pulls the image and runs it on any node, behind Traefik with an auto-TLS subdomain. Live logs, history and rollback included." },
];

const FEATURES = [
  ["Bring a repo — or your own Dockerfile", "A manifest builds a per-app image (python+node base, or your Dockerfile), layer-cached and pushed to a built-in registry — so any node can pull and run it."],
  ["Auto-TLS on every subdomain", "Apps land on a unique <name>-<token>.apps.example.com with TLS handled for you. Attach your own domains in a click."],
  ["Secrets, encrypted at rest", "Fernet-encrypted in the control plane, injected at deploy. Never in your repo, never in the image."],
  ["Live logs, history, rollback", "Stream the build and deploy as it happens. Every deploy is recorded; roll back to any commit."],
  ["Persistent storage", "Declare persist dirs in the manifest; they survive redeploys on NFS-backed volumes."],
  ["Workers, cron & Redis", "Add background workers and scheduled jobs from the same repo, and a scoped Redis bus to pass events between them — all in the manifest."],
  ["Single-operator, by design", "GitHub OAuth behind an allowlist. Your homelab, your apps, your rules — no multi-tenant ceremony."],
];

const CLIENTS = [
  { name: "ansaar.in", url: "https://ansaar.in", desc: "Islamic reference platform" },
  { name: "domainposture.com", url: "https://domainposture.com", desc: "Domain security posture" },
  { name: "quantamentary.com", url: "https://quantamentary.com", desc: "Quantamental investing" },
  { name: "manasrealty.com", url: "https://manasrealty.com", desc: "Real estate" },
  { name: "vcsolutions.co.in", url: "https://vcsolutions.co.in", desc: "VC solutions" },
];

function WaitlistSection() {
  const [email, setEmail] = useState("");
  const [siteCount, setSiteCount] = useState("");
  const [state, setState] = useState("idle"); // idle | submitting | done | error

  async function submit(e) {
    e.preventDefault();
    if (!email || !siteCount) return;
    setState("submitting");
    try {
      await joinWaitlist(email, siteCount);
      setState("done");
    } catch {
      setState("error");
    }
  }

  return (
    <section id="waitlist" className="max-w-6xl mx-auto px-6 py-16 scroll-mt-24">
      <div className="card p-10 relative overflow-hidden">
        <div className="glow absolute inset-x-0 top-0 h-40 pointer-events-none" />
        <div className="eyebrow">Managed koyracloud · coming soon</div>
        <h2 className="font-display text-3xl sm:text-4xl mt-4">
          Don't want to run the swarm? <span className="text-acid">We'll host it.</span>
        </h2>
        <p className="text-[var(--color-muted)] mt-3 max-w-xl">
          A fully-managed koyracloud — we run the infrastructure, you deploy unlimited
          sites from git. We're lining up the first users. Want in?
        </p>

        {state === "done" ? (
          <p className="mt-7 text-acid font-medium">You're on the list — we'll be in touch. 🎉</p>
        ) : (
          <form onSubmit={submit} className="mt-7 flex flex-wrap gap-3 items-center max-w-xl">
            <input
              type="email" required value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@agency.com"
              className="input flex-1 min-w-[220px]"
            />
            <select required value={siteCount} onChange={(e) => setSiteCount(e.target.value)}
                    className="input">
              <option value="" disabled>How many sites?</option>
              <option value="1-2">1–2 sites</option>
              <option value="3-9">3–9 sites</option>
              <option value="10+">10+ sites</option>
            </select>
            <button disabled={!email || !siteCount || state === "submitting"}
                    className="btn btn-primary shrink-0">
              {state === "submitting" ? "Joining…" : "Join the waitlist"}
            </button>
            {state === "error" && (
              <p className="w-full text-sm" style={{ color: "#ff5f57" }}>
                Something went wrong — try again.
              </p>
            )}
          </form>
        )}
      </div>
    </section>
  );
}

export default function Landing() {
  // Deep-link target: a shared koyracloud.com/#waitlist should land on the
  // signup form. The SPA renders after parse, so the browser's native anchor
  // jump misses — scroll it in once the section is mounted.
  useEffect(() => {
    if (window.location.hash !== "#waitlist") return;
    requestAnimationFrame(() =>
      document.getElementById("waitlist")?.scrollIntoView({ behavior: "smooth" }));
  }, []);

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
              Connect a git repo, get a running app behind HTTPS — with per-app image
              builds, persistent storage, injected secrets, live logs and rollback.
              Bring a small manifest, or your own Dockerfile.
            </p>
            <div className="rise mt-8 flex flex-wrap gap-3" style={{ animationDelay: "220ms" }}>
              <a href="/api/auth/login" className="btn btn-primary">Sign in with GitHub →</a>
              <Link to="/docs" className="btn btn-ghost">Read the docs</Link>
              <a href={REPO_URL} target="_blank" rel="noreferrer" className="btn btn-ghost">Self-host it ↗</a>
            </div>
            <p className="rise mt-3 text-sm text-[var(--color-muted)]" style={{ animationDelay: "260ms" }}>
              Open source — <a href={REPO_URL} target="_blank" rel="noreferrer"
                className="text-acid no-underline hover:underline">github.com/hikmahtech/koyracloud</a>.
              Run it on your own Docker Swarm.
            </p>
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

      {/* Our Clients */}
      <section className="max-w-6xl mx-auto px-6 py-16">
        <div className="eyebrow text-center">Our clients</div>
        <p className="mt-3 text-center text-sm text-[var(--color-muted)]">
          Production apps running on koyracloud — built by{" "}
          <a href="https://hikmahtechnologies.com" target="_blank" rel="noreferrer"
             className="text-acid no-underline hover:underline">Hikmah Technologies</a>.
        </p>
        <div className="mt-8 flex flex-wrap justify-center gap-4">
          {CLIENTS.map((c) => (
            <a key={c.name} href={c.url} target="_blank" rel="noreferrer noopener"
               className="card px-6 py-4 no-underline hover:border-[#3a4150] transition text-center min-w-[160px]">
              <div className="font-display text-sm font-medium text-[var(--color-fg)]">{c.name}</div>
              <div className="text-xs text-[var(--color-muted)] mt-1">{c.desc}</div>
            </a>
          ))}
        </div>
      </section>

      {/* Managed waitlist */}
      <WaitlistSection />

      {/* CTA */}
      <section className="max-w-6xl mx-auto px-6 py-20">
        <div className="card p-10 text-center relative overflow-hidden">
          <div className="glow absolute inset-x-0 top-0 h-40 pointer-events-none" />
          <h2 className="font-display text-3xl sm:text-4xl">Ship your next repo in minutes.</h2>
          <p className="text-[var(--color-muted)] mt-3">
            Add a manifest, connect the repo, watch it go live — or run the whole thing on your own swarm.
          </p>
          <div className="mt-7 flex justify-center flex-wrap gap-3">
            <a href="/api/auth/login" className="btn btn-primary">Get started</a>
            <Link to="/docs" className="btn btn-ghost">Manifest reference</Link>
            <a href={REPO_URL} target="_blank" rel="noreferrer" className="btn btn-ghost">Self-host on GitHub ↗</a>
          </div>
        </div>
      </section>

      <Footer />
    </div>
  );
}
