# Architecture & design decisions

This document explains how koyracloud deploys an app and *why* it's built the way it
is. It complements the [README](../README.md) (what it is) and
[`deploy/README.md`](../deploy/README.md) (how to run it).

## Components

| Component | What it is |
|-----------|------------|
| **Control plane** | A FastAPI + React app running as a single Swarm service on a manager node. Owns the database (apps, deploys, domains, env, secrets), drives the cluster via the mounted docker socket, and serves the dashboard + API. |
| **Internal registry** | A `registry:2` Swarm service koyracloud owns. Per-app images are pushed here and pulled by Swarm on whichever node runs the app. |
| **Base buildpack image** | `python:3.12 + node:22 + git` (`runtime-image/`). Used as the `FROM` for *generated* app images and to serve static sites. Apps that ship their own `Dockerfile` don't use it. |
| **Traefik** | The HTTPS edge. The control plane renders per-app router labels; Traefik routes by `Host(...)`. |
| **cloudflared tunnel** | Brings custom-domain traffic from the Cloudflare edge to Traefik (for the Cloudflare-for-SaaS flow). |
| **NFS** | Shared storage for persisted app data and the registry's image store. **Never** for application code. |

## The deploy pipeline

```
1. clone        repo @ commit → LOCAL build dir (KOYRA_BUILD_DIR, off NFS)
2. manifest     read .paas/app.yaml (or synthesize one for a static repo)
3. dockerfile   use the repo's own Dockerfile, or generate one from the manifest
4. build        docker build  → koyra-app-<name>:<commit>   (app env as build args)
5. push         docker push   → <registry>/koyra-app-<name>:<commit> and :latest
6. deploy       docker stack deploy → Swarm service from the registry image
7. run          Swarm pulls + runs the app on any node; clean up the local build dir
```

Each step streams to the deploy log (SSE) so you watch it live in the dashboard.

## Decision: build into an image, off NFS — not build-on-NFS

**Earlier design:** one shared runtime image; the app's code, `node_modules`, venv and
build caches lived on an NFS volume; a one-off container ran `npm ci` / `next build`
*on that NFS volume*, and the long-running service then served the code from NFS.

**Why it was changed:** NFS is terrible at the many-small-files workload of a JS
`node_modules` (or a Python venv). Builds crawled, and the I/O contention starved the
control plane — whose SQLite database lives on the same NFS — enough that Swarm's
health check failed and restarted it *mid-deploy*, orphaning the deploy.

**Now:** clone to **local disk**, `docker build` there (the image holds the built
app), and run the container **from the image**. Docker's layer cache replaces the old
hand-rolled dependency-hash cache. NFS is touched only for `persist:` data. This is the
standard buildpack/registry model and removed more code than it added (the
clone-on-NFS / sync-on-start / dep-hash machinery is gone).

## Decision: an internal registry, reached at `127.0.0.1:5000`

To run an app on *any* node, that node must be able to pull its image. koyracloud runs
a `registry:2` service and tags images `<registry>/koyra-app-<name>:<commit>`.

The registry is **published on the Swarm ingress mesh** (`5000:5000`), so every node
reaches it as `127.0.0.1:5000`. Docker treats `127.0.0.1` as an insecure-OK registry
**by default**, so there's no per-daemon config, no TLS, and no auth to manage — and the
registry is **never reachable from outside the swarm**.

**Why not put the registry behind Traefik / a real domain?** Two reasons: the homelab
reference setup proxies through Cloudflare, whose free tier **caps request bodies at
100 MB** — image layers routinely exceed that, so pushes would fail; and the inbound
ports are closed, so a public route wouldn't reach in anyway. The loopback-over-ingress
pattern is simpler *and* strictly internal.

> A *container's* `127.0.0.1` is its own loopback — only the host/daemon's reaches the
> registry. Test reachability with `docker run --network host`, not from inside a service.

## Decision: nothing is pinned — NFS-driver volumes

Pinning every app to one node defeats the point: lose that node, lose everything. So
neither the registry nor apps are pinned (`KOYRA_APP_NODE` empty,
`KOYRA_RESOLVE_IMAGE_NEVER=0` so apps resolve/pull from the registry).

The catch: a plain bind mount to an NFS path only works on nodes that already have the
NFS mounted there. Instead, the registry's storage and each app's `persist:` dir use a
**Docker NFS-driver volume** (`type: nfs, o: addr=<server>,nfsvers=4, device=:<path>`,
the homelab's standard pattern). Docker mounts the NFS itself on whichever node runs the
container, so:

- no node needs a pre-mounted NFS, and
- the registry/app can run **and reschedule** anywhere.

The control plane pre-creates each `persist:` directory on the NFS so the volume's
`device` path resolves. Without `KOYRA_NFS_SERVER` set (local/dev), `stack_render` falls
back to plain bind mounts.

## Decision: custom domains via Cloudflare for SaaS, validated over DNS

A user attaches their own domain; koyracloud registers it as a **Cloudflare for SaaS
custom hostname** and returns the two CNAMEs they add at their registrar: one routing
traffic to the SaaS fallback origin, one delegating ACME/DCV. The Cloudflare edge mints
and auto-renews the cert — the user never moves nameservers (Vercel-style).

**Validation must be DNS (`ssl.method: txt`, via DCV delegation), not HTTP.** The
homelab tunnel's ingress catch-alls *every* path — including
`/.well-known/acme-challenge/<token>` — to the app, so Cloudflare's HTTP-01 challenge is
proxied to the app (which 404s it) instead of being served at the edge, and the cert sits
in `pending_validation` forever. DNS validation via the `_acme-challenge` delegation CNAME
sidesteps the app entirely. (Proven the hard way: a real hostname stuck on HTTP validation
went active within ~90s once switched to `txt`.)

## Decision: default app URLs are `<name>-<token>.<apps_domain>` behind one wildcard

Every app gets a default URL the moment it's created, with no DNS work by the user. Two
choices make this free and collision-proof:

- **One label deep, so one free wildcard cert covers everything.** The host is
  `<name>-<token>.<apps_domain>` and `apps_domain` is a single label under the zone (e.g.
  `koyracloud.com`, *not* `apps.koyracloud.com`). A provider's free wildcard cert for
  `*.<apps_domain>` (e.g. Cloudflare Universal SSL) only matches one label deep, so keeping
  the host one level down means no paid certificate is needed. A single proxied wildcard DNS
  record `*.<apps_domain>` → the tunnel routes every app to Traefik, which dispatches by Host.
- **A random per-app `token`** (a short hex slug stored on the app) is appended to the name
  so two apps can never collide on a URL and the URLs aren't trivially enumerable
  (Vercel-style). It's generated once at creation and seeded as the app's primary `Domain`.

The auto-subdomain is in-zone, so it skips the Cloudflare-for-SaaS custom-hostname flow
above. Its TLS depends on how `apps_domain` is fronted: a self-host with open `80/443` lets
Traefik mint a Let's Encrypt cert (the default). When `apps_domain` sits behind a
TLS-terminating proxy over a tunnel (no inbound HTTP-01 path), set
`KOYRA_APPS_DOMAIN_PROXIED=1` so Traefik *skips* ACME for in-zone hosts — the edge already
serves the wildcard cert, and an ACME attempt would only fail and burn rate limits.

## Decision: app env + secrets reach the build, as build args

Frameworks like Next.js (`NEXT_PUBLIC_*`) and Vite (`VITE_*`) **inline env vars at build
time** into the client bundle. If those are absent during `docker build`, the bundle bakes
`undefined` and breaks in the browser even when the values are set correctly. So the
non-secret app env is passed to the build as `--build-arg`. Secrets are injected only at
**run** time (in the service environment), never baked into image history.

## Decision: push-to-deploy, optionally gated on CI

The webhook (`POST /api/webhooks/github`, HMAC-verified) maps an event to a deploy:

- **`push`** → deploy immediately (repos without gating CI).
- **`workflow_run` completed + success** → deploy *after* CI passes (repos with CI send
  this event instead). Failed/in-progress runs never deploy.

The repo's webhook is configured to send whichever event suits it; the control plane
handles both and dedups by commit SHA. Per-app `auto_deploy` gates the whole thing.

## Configuration & secrets

Everything instance-specific is environment-driven (see
[`deploy/koyracloud.env.example`](../deploy/koyracloud.env.example)); nothing is hardcoded.
Sensitive values (Fernet key, OAuth secret, GitHub PAT, Cloudflare token, webhook secret)
are read from mounted **Docker secrets** via `config._secret("NAME")` (`NAME_FILE` then
`NAME`), so they stay out of the process environment and image. App secrets are encrypted
at rest with Fernet and decrypted only to inject at run time.
