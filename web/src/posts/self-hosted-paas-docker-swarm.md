Most teams eventually reach a point where managing containers by hand stops working. You're pushing images to a registry, writing bash scripts to pull and restart them, maintaining TLS certificates, managing environment variables in a dozen places, and spending Friday afternoons debugging why a service won't start. At some point you think: someone must have solved this already. They have — and you probably know the answer: Kubernetes. But before you go down that road, there's a quieter option that doesn't require a PhD in YAML.

A self-hosted PaaS on Docker Swarm handles the plumbing you're probably reimplementing manually: the build-push-deploy loop, HTTPS for every app, secrets management, persistent storage, logs, and rollbacks. You trade the ability to hand-tune every knob for something that just works, and you keep it running on hardware you already have.

## What is a self-hosted PaaS, really?

A Platform-as-a-Service abstracts away the container choreography. Instead of thinking about services and networks and load balancers, you think about apps. Push code, declare a few requirements (what runtime, what port, which directories persist), and it goes live.

Traditional PaaS platforms — Heroku, Railway, Fly — handle this for you in the cloud. You pay them per dyno or per GB-second, they own the infrastructure, and you deploy via `git push`. The tradeoff is cost and lock-in. You're running on their servers, with their quotas, and their pricing model.

A self-hosted PaaS inverts that: you own the cluster (maybe a couple of servers in your homelab, or your client's rack), and you run the platform software yourself. The economics shift. If you're already paying for the bare metal, the PaaS layer — the orchestration, the build pipeline, the HTTPS — is mostly software.

## Why Docker Swarm, not Kubernetes?

Kubernetes is powerful. It's also 800 pages of concepts before you deploy your first pod. You need a cluster administrator, persistent-volume claims, ingress resources with three layers of indirection, and enough YAML to make a grown engineer cry. For most internal apps and smaller operations, it's overkill.

Docker Swarm is boring. A cluster is just nodes and services. You describe what you want to run, Swarm schedules it, and it stays running. The mental model fits in a brain. You can understand the whole thing in a day. For a small team running a handful of apps, that simplicity is the feature.

Swarm also runs on commodity hardware — no special networking overlays, no 10GB of RAM just for the control plane. A three-node cluster (one manager, two workers) with standard Docker is genuinely cheap to operate.

The tradeoff is scale and sophistication. Kubernetes can orchestrate thousands of nodes and handles things Swarm doesn't think about: rolling updates with canary deployments, complex networking policies, sophisticated scheduling constraints. If you're Netflix or Stripe, you need it. If you're a bootstrapped team or running internal tools, Swarm is plenty, and you'll spend your time shipping features instead of fighting the platform.

## What you get over hand-rolling it

The gap between "I have Docker Swarm" and "I have a working deployment platform" is wider than you'd think. The things you're building yourself:

**The build pipeline.** Pulling code, running a build step, tagging an image, pushing it to a registry. Caching layers. Handling build failures gracefully. That's a service and a half right there.

**The deploy loop.** New image in the registry — now update the service to use it, watch the rollout, handle failures. Rollback if something breaks. Keep logs of what deployed when.

**HTTPS and DNS.** Every modern app needs TLS. That means provisioning certificates, renewing them before they expire, wiring up DNS, and changing the hostname every time you redeploy. Let's Encrypt automation helps, but you still need the plumbing.

**Secrets.** Environment variables with API keys and passwords shouldn't live in code or docker-compose files. You need a place to store them encrypted and a way to inject them safely at runtime.

**Persistence.** Some directories in your app — a database, uploaded files, logs — need to survive a redeploy or a node failure. That means NFS mounts, backups, and keeping them separate from the container lifecycle.

**Live logs and history.** You deploy something, it fails, and you want to know why. Live build logs. Deploy history. The ability to roll back to the last known-good version in one click.

You can cobble this together with scripts and Traefik and a lot of patience. But the effort adds up, and the bugs are subtle. A small platform handles all of it in one place.

## What koyracloud does

koyracloud is a self-hosted PaaS designed for Docker Swarm. You connect a GitHub repo with a small manifest (`.paas/app.yaml`), declare your runtime (Python, Node, static, or a custom Dockerfile), and configure a subdomain and a port. Push code, and it builds the image on local disk (layer-cached), pushes it to an internal registry, and deploys a Swarm service behind HTTPS.

Persistence is NFS. Secrets are encrypted at rest and injected at runtime. HTTPS is automatic for platform subdomains (Traefik + Let's Encrypt) or Cloudflare-backed for custom domains. You get live logs during builds and deploys, deploy history, and one-click rollback.

Beyond simple web apps, it also handles background workers (always-on processes) and cron jobs (scheduled, run-to-completion tasks) from the same repository and image. Per-app Redis buses for inter-process communication. GitHub-based deployments — push-to-deploy on `git push` or gated behind a successful CI workflow.

Single operator by design. No multi-tenant sandboxing. No autoscaling (you manage cluster capacity yourself). No preview environments per PR. No managed databases. It's honest about what it is: a thin, practical layer between you and your cluster for trusted code and internal apps.

## Who it's for and who it's not

If you're running five to fifty applications, maintaining a homelab or a couple of servers, and want them deployed and scaled without hand-rolling orchestration, this fits. If you're building customer-facing SaaS with untrusted code, you need proper sandboxing. If you're scaling to hundreds of microservices, Kubernetes or a managed PaaS makes sense. If you don't have a cluster and don't want to manage one, just use Heroku or Railway.

The honest pitch: you already have the hardware, you already understand Docker, you probably already have Swarm or are ready to learn it. This takes the friction out of the next piece: getting your code from GitHub to production without reinventing the wheel.

The code is open at [github.com/hikmahtech/koyracloud](https://github.com/hikmahtech/koyracloud), and the [docs](/docs) walk through Docker Swarm setup if you're building from scratch.