import { PublicNav, Footer } from "../components/Chrome.jsx";

const POSTS = [
  {
    date: "2026-06-10",
    tag: "Launch",
    title: "Introducing koyracloud",
    body: [
      "koyracloud turns a homelab Docker Swarm into a self-hosted PaaS. Connect a git repo with a .paas/app.yaml manifest and it builds, runs and routes your app behind HTTPS — no per-app Dockerfile, runner, or container registry.",
      "It's built for a single trusted operator: GitHub OAuth behind an allowlist, secrets encrypted at rest, and one shared runtime image that runs everything. The first app onboarded was a FastAPI + React inventory system — connected, built and live on its own subdomain in minutes.",
    ],
  },
  {
    date: "2026-06-10",
    tag: "Engineering",
    title: "Why builds run in a one-off container",
    body: [
      "Early on, apps built their dependencies inside the served container on first start. That raced the healthcheck and, worse, concurrent restarts ran npm installs against the same shared volume and corrupted each other.",
      "The fix: the control plane runs the build once in a disposable container, then deploys the long-running service — which finds the dependency hash satisfied, skips the build, runs migrations and starts. No race, no corruption, fast restarts.",
    ],
  },
  {
    date: "2026-06-10",
    tag: "Feature",
    title: "Attach your own domains",
    body: [
      "Every app gets an automatic *.apps.example.com subdomain, but you can now attach custom domains from the app's Domains tab. Point an A record at the homelab and Traefik mints a certificate on the first request — all domains route to the same app, and you choose which one is primary.",
    ],
  },
];

export default function Blog() {
  return (
    <div className="grid-bg min-h-screen">
      <PublicNav />
      <div className="max-w-3xl mx-auto px-6 py-16">
        <div className="eyebrow">Blog & changelog</div>
        <h1 className="font-display text-4xl mt-3 mb-10">What's shipping</h1>
        <div className="space-y-5">
          {POSTS.map((p) => (
            <article key={p.title} className="card p-7">
              <div className="flex items-center gap-3 mb-3">
                <span className="mono text-xs text-acid border border-[var(--color-line)] rounded px-2 py-0.5">{p.tag}</span>
                <span className="mono text-xs text-[var(--color-muted)]">{p.date}</span>
              </div>
              <h2 className="font-display text-2xl mb-3">{p.title}</h2>
              {p.body.map((para, i) => (
                <p key={i} className="text-[var(--color-muted)] leading-relaxed mb-3">{para}</p>
              ))}
            </article>
          ))}
        </div>
      </div>
      <Footer />
    </div>
  );
}
