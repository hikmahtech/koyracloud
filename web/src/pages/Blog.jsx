import { PublicNav, Footer } from "../components/Chrome.jsx";

const POSTS = [
  {
    date: "2026-06-10",
    tag: "Launch",
    title: "Introducing koyracloud",
    body: [
      "koyracloud turns a homelab Docker Swarm into a self-hosted PaaS. Connect a git repo with a .paas/app.yaml manifest — or your own Dockerfile — and it builds a container image, runs it behind HTTPS, and routes it for you.",
      "It's built for a single trusted operator: GitHub OAuth behind an allowlist, secrets encrypted at rest, and a built-in registry every node pulls app images from. The first app onboarded was a FastAPI + React inventory system — connected, built and live on its own subdomain in minutes.",
    ],
  },
  {
    date: "2026-06-10",
    tag: "Engineering",
    title: "Why we build apps into images, off NFS",
    body: [
      "An earlier design kept each app's code, node_modules and venv on a shared NFS volume, and a one-off container built dependencies there before the long-running service served the code from NFS. It worked — until it didn't: NFS is miserable at the many-small-files workload of a node_modules tree, builds crawled, and the I/O contention starved the control plane's own database enough to fail its healthcheck mid-deploy.",
      "Now each deploy builds a per-app container image on local disk (off NFS), pushes it to a built-in registry, and runs the container from the image. Docker's layer cache replaces the hand-rolled dependency hashing, NFS is touched only for persisted data, and because any node can pull the image, apps run and reschedule anywhere. It removed more code than it added.",
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
