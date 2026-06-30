Here's a concrete one: you've got a FastAPI backend with a React frontend, and you want it running on your homelab at a real URL with HTTPS — not on localhost, not on a paid host. This walks through deploying exactly that on koyracloud, from manifest to live app. It's the kind of full-stack app most side projects actually are.

The assumption is that you already have koyracloud running on a Docker Swarm (if not, the self-host tutorial covers the swarm, Traefik edge, NFS and DNS first). From there, deploying an app is a manifest and a button.

## The app

A typical layout: a Python API at the repo root, a React app under `web/` that builds to static files the API serves. One process, one port. The trick with a full-stack app is that the build needs *both* a Python and a Node toolchain, and koyracloud has a runtime for exactly that.

## The manifest

Commit a `.paas/app.yaml` to the repo root:

```yaml
name: inventory
runtime: python+node          # both toolchains available at build
port: 8000
build:
  - pip install -r requirements.txt
  - bash -c "cd web && npm ci && npm run build"
predeploy:
  - alembic upgrade head        # runs every start, before the app
start: uvicorn app.main:app --host 0.0.0.0 --port 8000
persist: [data]                 # survives redeploys (NFS-backed)
healthcheck: /health
secrets: [DATABASE_URL, SECRET_KEY]
```

A few things worth understanding rather than copy-pasting:

- **`runtime: python+node`** gives the build a buildpack image with both `python:3.12` and `node:22`. Your `build` steps run in there, so `pip install` and `npm ci && npm run build` both just work. The result is baked into a per-app container image.
- **`build` vs `predeploy`.** `build` runs once when the image is built. `predeploy` runs on every start, before the app comes up — the right place for database migrations, so a rollback to an older image still migrates correctly.
- **`port`** is the single port your app listens on. Traefik routes HTTPS to it. Your React build is static files FastAPI serves, so there's only one process and one port — no separate frontend service to wire up.
- **`persist: [data]`** marks directories that survive redeploys, backed by NFS. Everything else is ephemeral and rebuilt from the image, which is what you want.
- **`healthcheck: /health`** is the path Swarm polls to know the app is ready before routing traffic to it. Add a trivial `/health` route that returns 200.

## Secrets and build-time env

`secrets: [DATABASE_URL, SECRET_KEY]` declares the names; you set the *values* in the dashboard, and koyracloud injects them at **runtime** — encrypted at rest with Fernet, never baked into image layers.

There's one gotcha specific to frontends: anything inlined into the client bundle at build time (`VITE_*` for Vite, `NEXT_PUBLIC_*` for Next) has to exist when `npm run build` runs, not just at runtime. koyracloud passes your app's env vars as **build args** too, so those values are baked into the client bundle instead of coming out `undefined`. Set them as env in the dashboard and they're available at both build and run.

## Deploy

In the dashboard: **New App**, paste the repo URL, and **Deploy**. koyracloud clones the repo, builds the image on local disk, pushes it to the internal registry, and deploys a Swarm service from it. You watch the build and deploy logs stream live (SSE) the whole time. A minute or so later the app is up at `inventory-<token>.<your apps domain>` with a real Let's Encrypt certificate.

If the build fails — a missing dependency, a bad command — you see it in the log, fix the repo, and push. Which brings us to the good part.

## Push-to-deploy

Once connected, a GitHub webhook redeploys the app on every `push`. If your repo runs CI, point koyracloud at the successful `workflow_run` instead, so it deploys only after tests pass. Either way, after the first manual deploy you never touch the dashboard to ship again: `git push`, watch the logs, done. Break something? One click rolls back to the previous image — and because deploys are immutable images, the rollback is instant and exact, not a re-build-and-pray.

## Adding a worker later

Say the app grows a background job — sending emails, processing uploads. Same repo, same image, add to the manifest:

```yaml
redis: true                     # provision a scoped Redis, inject REDIS_URL
workers:
  - name: jobs
    start: python -m app.worker
cron:
  - name: nightly
    schedule: "0 2 * * *"
    command: python -m app.jobs.nightly
```

The worker is an always-on process off the same image; cron jobs run to completion on a schedule with per-run logs and a **Run now** button; and `redis: true` injects a `REDIS_URL` your web and worker share, isolated to your app's key prefix. No new repo, no new image, no separate infrastructure.

That's the whole loop: a manifest, a deploy, and a `git push` from then on. A full-stack app on your own hardware, behind HTTPS, in about the time it takes to read this.

koyracloud is open source (AGPL-3.0), built by [Hikmah Technologies](https://hikmahtechnologies.com). The manifest reference and more examples are in the [repo](https://github.com/hikmahtech/koyracloud) — stars welcome if this saved you a weekend.
