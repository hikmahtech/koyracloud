<div align="center">

# koyracloud

**Your own Vercel — self-hosted on your Docker Swarm.**

Connect a git repo with a small manifest and koyracloud builds and runs it behind
HTTPS, with persistent storage, injected secrets, live deploy logs, custom domains
and rollback. No per-app Dockerfile, runner, or container registry — just a manifest.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-c8f04e.svg)](LICENSE)
![Status](https://img.shields.io/badge/status-alpha-blue.svg)
![Python](https://img.shields.io/badge/python-3.12-3776ab.svg)
![React](https://img.shields.io/badge/react-19-61dafb.svg)

</div>

---

## What it is

koyracloud turns a Docker Swarm into a single-operator Platform-as-a-Service. It's
the "connect a repo → it deploys" experience of Render/Vercel, scoped to **trusted
code and internal apps** — your homelab, your clients' apps, your side projects.

Every app runs from **one shared runtime image** (`python:3.12` + `node:22` + `git`).
Your code, virtualenv and build caches live on a volume; the control plane clones,
builds once in a one-off container, migrates, runs and routes the app.

## The manifest

Describe build & run in a `.paas/app.yaml` committed to your repo:

```yaml
name: my-app
runtime: python+node          # python | node | python+node
subdomain: my-app.apps.example.com
port: 8000
build:
  - pip install -r requirements.txt
  - bash -c "cd web && npm ci && npm run build"
predeploy:
  - alembic upgrade head       # runs every deploy, before start
start: uvicorn app.main:app --host 0.0.0.0 --port 8000
persist: [data]                # survives redeploys
healthcheck: /health
secrets: [SECRET_KEY]          # values set in the UI, injected at deploy
```

Full reference: the **Docs** in-app (`/docs`) or [`examples/`](examples/).

## How it works

```
repo (.paas/app.yaml)
   │  control plane clones → volume @ commit
   ▼
one-off build container   (pip / npm / vite, cached by dependency hash)
   ▼
docker stack deploy  →  service (Traefik labels, secrets, persist dirs)
   ▼
entrypoint: sync · skip build · predeploy (migrate) · exec start
   ▼
https://<host>   ·   per-host TLS minted on first request
```

The control plane is a FastAPI + React app that runs as one Swarm service on a
manager node, renders a Docker stack from your manifest, and drives the cluster
through the mounted docker socket. Builds run in a disposable container so the
served app never races its own healthcheck.

## Features

- **Bring a repo, not a Dockerfile** — one runtime image, dependency-hash caching.
- **Auto-TLS subdomains** + **custom domains** (attach in a click; Traefik handles certs).
- **Secrets encrypted at rest** (Fernet), injected at deploy.
- **Live build/deploy logs** (SSE), deploy history, one-click rollback.
- **Persistent storage** via manifest `persist:` dirs.
- **GitHub OAuth** behind a login allowlist — single-operator by design.

## Self-hosting

You need a Docker Swarm with Traefik (HTTPS entrypoint + ACME resolver) and a
shared volume path across nodes. Then:

1. Build the runtime image (`runtime-image/`).
2. Configure + deploy the control plane — see **[`deploy/README.md`](deploy/README.md)**.

## Local development

```bash
# control plane (SQLite, OAuth bypassed)
cd control-plane
KOYRA_DEV_LOGIN=you \
KOYRA_SECRET_KEY="$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')" \
  uv run uvicorn koyracloud.main:app --reload

# UI (proxies /api to :8000)
cd web && npm install && npm run dev
```

## Tests

```bash
cd runtime-image  && uv run --with pytest --with pyyaml pytest      # entrypoint
cd control-plane  && uv run --with-editable . --with pytest pytest  # control plane
```

## Project layout

```
runtime-image/   the shared buildpack: Dockerfile + entrypoint.py + tests
control-plane/   FastAPI + SQLAlchemy control plane (apps, deploys, domains, secrets, OAuth)
web/             React + Vite + Tailwind + TanStack Query (landing, docs, dashboard)
deploy/          swarm stack + deploy script + runbook
examples/        sample .paas/app.yaml manifests
```

## Non-goals

Multi-tenant isolation/sandboxing of untrusted code, autoscaling, preview-per-PR
environments, managed databases, billing. It's a single-operator, trusted-code,
internal-apps platform — kept small on purpose.

## Contributing

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) and
[SECURITY.md](SECURITY.md). All tests must pass.

## License

koyracloud is licensed under the **GNU AGPL-3.0** (see [LICENSE](LICENSE)). You may
self-host and modify it freely; if you run a modified version as a network service,
you must offer your source under the same terms.

**Commercial licensing.** The AGPL's network-copyleft is not suitable for every
business. A commercial license (no copyleft obligations) is available from the
copyright holder — see [LICENSING.md](LICENSING.md).

© Hikmah Technologies / Arshad Ansari.
