## Why We Built an Open-Source Vercel Alternative (and Why You Might Use It)

Vercel is genuinely good at what it does. The experience of pushing code to GitHub and having it live in seconds, with automatic HTTPS and a shareable URL, changed how web developers think about deployment. No wrestling with servers, no infrastructure expertise required. For small projects and teams, it's hard to beat.

But if you've deployed enough projects there, you've probably hit the ceiling: costs scale unpredictably with bandwidth and function invocations, your app lives in their infrastructure, you're locked into their ecosystem, and the pricing page becomes less friendly as your traffic grows. For teams running their own hardware—whether that's a homelab, a small data center, or cloud instances you already own—the abstraction stops being worth the rent.

koyracloud exists for that gap. It's an open-source, self-hosted Platform-as-a-Service built on Docker Swarm. It borrows the things Vercel does well—push-to-deploy, automatic HTTPS, rollback, live deploy logs—and runs it all on your own infrastructure. You lose the global edge network and autoscaling, but you keep your data, your costs, and your code.

## What You Keep from Vercel

**Push-to-deploy:** Connect a GitHub repo with a simple `.paas/app.yaml` manifest or a Dockerfile. Push a commit or merge a PR, and koyracloud builds a container, pushes it to an internal registry, and deploys a Swarm service. Logs stream live; you see what's happening.

**Custom domains with automatic HTTPS:** Add two CNAMEs at your registrar—we handle the rest via Cloudflare for SaaS. The certificate mints, renews, and rotates automatically. Platform subdomains get Traefik + Let's Encrypt out of the box. No manual cert management.

**Environment variables and secrets:** Build-time framework envs (like `NEXT_PUBLIC_*` for React, `VITE_*` for Vue) are passed as build args so your client bundles get the right values baked in. Runtime secrets are injected only at runtime, encrypted at rest with Fernet, never touching image layers. One source of truth, no environment drift.

**Rollback:** Full deploy history with one-click rollback. Got a bug in production? Roll back to the last known-good version in seconds.

**Background jobs, cron, and a message bus:** Worker processes and scheduled tasks from the same repo. A per-app Redis bus ships with every deployment for inter-service communication.

## What You Don't Get

Be honest about the trade-offs. koyracloud is deliberately not a managed platform at scale.

**No global CDN or edge network.** Vercel runs your code at edge nodes worldwide, so your API is low-latency everywhere. With koyracloud, you're running on the hardware you own. If that's a single data center or a homelab, latency is what it is. If you need truly global distribution, this isn't the answer.

**No preview environments per PR.** Vercel spins up a preview URL for every pull request. koyracloud deploys from the repo you point it at; if you want preview deploys, you'll manage those separately (a different branch, a separate service, etc.).

**No autoscaling.** Vercel scales your functions invisibly. koyracloud runs a fixed number of replicas per service. You set replica count, you monitor load, you scale manually or with external tools.

**No marketplace of functions or managed services.** With Vercel, you can reach for Postgres, Redis, analytics—all hosted. With koyracloud, you bring your own infrastructure or host services yourself on the same cluster.

The honest pitch: if you're a solo developer or a small team with internal tools, client projects, or side projects running on hardware you control, koyracloud fits naturally. If you're a scaling SaaS where Vercel's optics and global reach matter, you're probably not the target.

## The Migration Path

Moving a Next.js app off Vercel is simpler than it looks. The team maintains `docs/MIGRATING-FROM-VERCEL.md`—a field-tested playbook that covers:

- Writing a Dockerfile or using a generated buildpack image (Python 3.12 + Node 22 out of the box)
- Migrating environment and secrets to koyracloud's model
- Handling custom domains (the apex-domain problem and real solutions)
- Preserving email service integrations

Most apps move in an afternoon. The hardest part is usually the first time; the second time is routine.

## For the Right Situation

koyracloud isn't selling you a story about how it's better than Vercel—it's not. It's better for a different situation: you own the infrastructure, you want the developer experience without the lock-in, and you're willing to own the operations (monitoring, backups, updates). No surprise bills, no bandwidth overage, no vendor surprise.

If that sounds like your setup, take a look at the GitHub repo or the migration guide. The project is actively maintained, and the community is small and pragmatic about what this thing actually is.
