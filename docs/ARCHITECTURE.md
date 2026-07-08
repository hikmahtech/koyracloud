# Architecture & design decisions

This document explains how koyracloud deploys an app and *why* it's built the way it
is. It complements the [README](../README.md) (what it is) and
[`deploy/README.md`](../deploy/README.md) (how to run it).

## Components

| Component | What it is |
|-----------|------------|
| **Control plane** | A FastAPI + React app running as a single Swarm service on a manager node. Owns the database (apps, deploys, domains, env, secrets), drives the cluster via the mounted docker socket, serves the dashboard + API, and runs background loops: the uptime monitor and the **cron scheduler** (launches due jobs as Swarm run-to-completion jobs). Also exposes Prometheus `/metrics` (see [`MONITORING.md`](MONITORING.md)). |
| **Internal registry** | A `registry:2` Swarm service koyracloud owns. Per-app images are pushed here and pulled by Swarm on whichever node runs the app. |
| **Shared Redis** | A `redis:7` Swarm service koyracloud owns — the bus for apps with `redis: true` (and their workers/cron). Each app gets an ACL user scoped to its own `<app>:*` keys/channels; reached as `koyracloud_redis:6379`. AOF on an NFS-driver volume. |
| **Base buildpack image** | `python:3.12 + node:22 + git` (`runtime-image/`). Used as the `FROM` for *generated* app images and to serve static sites. Apps that ship their own `Dockerfile` don't use it. |
| **Traefik** | The HTTPS edge. The control plane renders per-app router labels; Traefik routes by `Host(...)`. |
| **cloudflared tunnel** | Brings custom-domain traffic from the Cloudflare edge to Traefik (for the Cloudflare-for-SaaS flow). |
| **NFS** | Shared storage for persisted app data, the registry's image store, and Redis's AOF. **Never** for application code. |

## The deploy pipeline

```
1. clone        repo @ commit → LOCAL build dir (KOYRA_BUILD_DIR, off NFS)
2. manifest     read .paas/app.yaml (or synthesize one for a static repo)
3. dockerfile   use the repo's own Dockerfile, or generate one from the manifest
4. build        docker build  → koyra-app-<name>:<commit>-<argshash>  (app env as build args)
                (SKIPPED when this exact image — same <commit> AND same build-args —
                 was already built+pushed, tracked in the `built_images` table; the
                 redeploy then just re-deploys the existing image)
5. push         docker push   → <registry>/koyra-app-<name>:<commit>-<argshash> and :latest
6. deploy       docker stack deploy → Swarm service from the registry image
7. run          Swarm pulls + runs the app on any node; clean up the local build dir
```

Each step streams to the deploy log (SSE) so you watch it live in the dashboard.

The docker build context is the repo root by default, or a subdirectory when the
manifest sets `root:` (monorepo apps — e.g. a Next site under `marketing/site/`
of a larger repo). The context is resolved through symlinks and asserted to stay
inside the clone, so a crafted manifest can't point the build at the host
filesystem. See `docs/MIGRATING-FROM-VERCEL.md` for the app-author playbook.

Only step 4 (the `docker build`) runs on the control-plane node's Docker; everything
the app actually *does* is a Swarm service (step 6/7) scheduled on **any** node — apps
are never pinned to the control plane. Re-rendering routing (e.g. attaching a domain)
is the common redeploy that hits the build-skip, so it costs nothing but a Swarm
service update.

**The image tag includes a hash of the build-args, not just the commit.** Build-time
vars (`NEXT_PUBLIC_*`/`VITE_*`) are inlined into the image at `docker build`, so the
build inputs are `commit + build-args`. Tagging by commit alone meant changing such a
var and redeploying *silently reused the stale image* — the new value never shipped
without an unrelated new commit to bust the cache. Folding the build-args into the tag
(`:<commit>-<argshash>`) makes that change a new image identity, so it rebuilds; an
unchanged redeploy still maps to the same tag and skips. Each built tag is recorded in
the `built_images` table, and the build is skipped only when that exact row exists.

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
a `registry:2` service and tags images `<registry>/koyra-app-<name>:<commit>-<argshash>`.

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

This is still the default for every app. The one opt-in exception — apps with
*node-local* state that NFS can't cover — is below.

## Decision: opt-in per-app node pinning

The default above (nothing pinned) breaks for an app whose state lives on the *node's
local disk* rather than an NFS-driver `persist:` volume — a Swarm reschedule to another
node would orphan that data. Pinning is the opt-in escape hatch: an `AppPin` row (own
table, `app_pins`) whose mere presence means "pinned," with a `node` column holding the
recorded hostname — empty until learned.

On a pinned deploy, `deployer._run_deploy` resolves the node before rendering the stack:
if it's already recorded, use it; otherwise read where the app currently runs via
`docker service ps` (a redeploy of an existing app), or deploy free once and read back
where Swarm landed it (a brand-new app), then record it in `AppPin.node` so every deploy
after carries the constraint. `stack_render.render_stack`'s `pin_node` param turns a
resolved node into `deploy.placement.constraints: [node.hostname == <node>]` on **both**
the web service and its workers, since they share the app's persist volumes and must
co-locate. A per-app pin takes precedence over the operator-wide `KOYRA_APP_NODE` env var.

Toggled via `PATCH /api/apps/{id}` (`pinned: bool`; `AppOut.pinned` / `pinned_node`
mirror it back) from the dashboard's Settings tab. Turning it on only takes effect on the
**next** deploy — it doesn't move or restart whatever's already running.

**Caveat, not a bug:** the pin binds to a node *hostname*. Rename or replace that node and
a pinned app's constraint can no longer be satisfied — it sits `Pending` until you unpin
(or repin to the new hostname). That's the intended fail-safe for node-local data;
silently rescheduling it elsewhere would be the actual bug.

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

**Apex domains are the exception.** A zone apex can't be a CNAME, and Cloudflare for SaaS
won't activate a custom hostname served via apex `A`-records-to-anycast (HTTP 409, "DNS
target needs to point to the SaaS zone"). So `www` uses the SaaS path above, and the apex
is handled per registrar — registrar forwarding, a Route 53 `ALIAS`→CloudFront redirect,
Cloudflare apex CNAME-flattening (when the domain's DNS is on Cloudflare), or the
self-hosted `deploy/apex-redirect-stack.yml` (a Caddy redirector reached over a WAN2
port-forward — the one inbound path that *can* solve Let's Encrypt HTTP-01, which the
tunnel can't). `docs/MIGRATING-FROM-VERCEL.md` §6 covers all four with trade-offs.

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
