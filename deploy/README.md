# Deploying the koyracloud control plane

The control plane is a single Swarm service pinned to a manager node. It serves
the API + UI and drives the swarm via the mounted docker socket. All
instance-specific values live in `deploy/koyracloud.env` (gitignored).

## Prerequisites

### 1. A Docker Swarm with Traefik
You need a swarm with Traefik as the edge: an external overlay network (default
`traefik_public`), an HTTPS entrypoint (`websecure`), and an ACME cert resolver
(`letsencrypt`) using the HTTP-01 challenge. Apps and the control plane attach to
that network and declare routers via deploy labels.

### 2. DNS
Point your control-plane host and a wildcard for app subdomains at your edge's
public IP:

| Type | Host         | Value                  |
|------|--------------|------------------------|
| A    | `koyracloud` | `<your server's IP>`   |
| A    | `*.apps`     | `<your server's IP>`   |

Traefik mints a per-host Let's Encrypt cert on first request.

### 3. Config
```bash
cp deploy/koyracloud.env.example deploy/koyracloud.env
$EDITOR deploy/koyracloud.env   # host, apps domain, public IP, allowlist, node…
```

### 4. The base buildpack image + the internal registry
Each deploy builds a **per-app image** and pushes it to an **internal registry**
that ships in the stack (a `registry:2` service). Apps are pulled from there and
run on any node — nothing is pinned.

- The base buildpack image (`python:3.12 + node:22 + git`) is the `FROM` for
  *generated* app images and serves static sites. Build + make it pullable by the
  nodes (push to a registry, or load on each node):
  ```bash
  docker build -f runtime-image/Dockerfile -t koyracloud-runtime:latest runtime-image/
  ```
  Apps that ship their own `Dockerfile` don't use it.
- Leave `KOYRA_APP_NODE` empty and `KOYRA_RESOLVE_IMAGE_NEVER=0` so apps schedule
  anywhere and pull from the registry. `KOYRA_REGISTRY` defaults to
  `127.0.0.1:5000` (the registry on the ingress mesh); `KOYRA_BUILD_DIR` is a
  **local** path (not NFS) where the control plane clones + builds.
- Set `KOYRA_NFS_SERVER` to your NFS server IP so the registry's image store and
  app `persist:` dirs use Docker NFS-driver volumes (mounted per-node, no pinning).
  Create the registry's storage dir on the export once: `<nfs>/koyracloud/registry`.
  Leave it empty for single-node / local (plain bind mounts).
- The shared **Redis** service (the bus for app `redis: true`, workers and cron)
  also stores its AOF on an NFS-driver volume — create `<nfs>/koyracloud/redis`
  on the export once too.

### 5. Secrets (Docker secrets, created once)
```bash
python3 -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())' \
  | tr -d '\n' | docker --context <ctx> secret create koyra_secret_key -
openssl rand -hex 32 | tr -d '\n' | docker --context <ctx> secret create koyra_session_secret -
printf '%s' '<github oauth client secret>' | docker --context <ctx> secret create koyra_github_client_secret -
printf '%s' '<github pat for cloning>'     | docker --context <ctx> secret create koyra_github_pat -
# Cloudflare for SaaS API token (Zone:SSL and Certificates:Edit + Zone:DNS:Read,
# scoped to your SaaS zone). Registers user custom domains as custom hostnames.
printf '%s' '<cloudflare for saas api token>' | docker --context <ctx> secret create koyra_cloudflare_api_token -
# Shared Redis admin password (the `default`/admin user). The control plane uses
# it to manage per-app ACL users. A blank secret disables the Redis bus — apps
# with `redis: true` then fail their deploy. Use a URL-safe value (no spaces).
openssl rand -hex 24 | tr -d '\n' | docker --context <ctx> secret create koyra_redis_admin_password -
```
> Secrets are immutable. To rotate: detach, `secret rm`, recreate, redeploy.
> Never rotate `koyra_secret_key` (the Fernet master key) without re-encrypting
> stored app secrets.
> Every secret is declared `external: true`, so it must exist before deploy. For
> optional features you aren't using (Cloudflare for SaaS, Resend), create an
> empty secret: `printf '' | docker --context <ctx> secret create koyra_cloudflare_api_token -`
> — the control plane treats a blank token as "feature off".

### 6. GitHub OAuth App
Register an OAuth App with callback `https://<your host>/api/auth/callback`; put
the Client ID in `koyracloud.env` and the Client Secret in the Docker secret above.

### 7. Custom domains via Cloudflare for SaaS (optional)
koyracloud serves users' *own* domains (DNS left at their registrar) by
registering them as Cloudflare for SaaS **custom hostnames**: the Cloudflare edge
mints + renews the TLS cert and routes to a fallback origin, so a user adds only
CNAMEs and never moves nameservers. Adding a domain in the UI calls the Cloudflare
API automatically and shows the records to add; `verify` polls the live cert
status. Leave `KOYRA_CLOUDFLARE_ZONE_ID` blank to keep the feature off — custom
domains then fall back to plain A-records → Traefik (section 2).

One-time, on the Cloudflare zone you'll register custom hostnames under (the
**SaaS zone**, e.g. `koyracloud.com`):

1. **SSL/TLS → Custom Hostnames → Enable Cloudflare for SaaS** (first 100 free).
2. **Turn on DCV Delegation** — gives a stable `<host>.<id>.dcv.cloudflare.com`
   target so users add the cert record once and never touch it again on renewal.
3. **Fallback Origin:** create a **proxied** DNS record (e.g. `origin.<zone>`)
   that reaches your edge — on the homelab it's a proxied CNAME into the
   Cloudflare Tunnel — then set it as the zone's *Fallback Origin*. Put the same
   hostname in `KOYRA_CLOUDFLARE_SAAS_ORIGIN`.
4. **Tunnel ingress (tunnel deployments only):** the tunnel must route *unknown*
   Host headers to Traefik, or custom hostnames 404 inside the tunnel. End the
   tunnel ingress with a catch-all → `https://traefik_traefik:443` (No TLS
   Verify). See the homelab `cloudflared` role README for the exact config.
5. Set `KOYRA_CLOUDFLARE_ZONE_ID` (zone → Overview) and create the
   `koyra_cloudflare_api_token` secret (section 5).

Each user then adds two CNAMEs at their registrar (both shown in the UI):

| Type  | Host                    | Value                                                 |
|-------|-------------------------|-------------------------------------------------------|
| CNAME | `<sub>`                 | your fallback origin (`KOYRA_CLOUDFLARE_SAAS_ORIGIN`) |
| CNAME | `_acme-challenge.<sub>` | `<full-host>.<dcv-id>.dcv.cloudflare.com`             |

The cert is validated over **DNS** through the `_acme-challenge` DCV-delegation
CNAME (Cloudflare controls that record and issues + auto-renews the cert) — *not*
over HTTP. HTTP-01 can't work behind a tunnel whose catch-all routes the
`/.well-known/acme-challenge/` path to the app (which 404s it), so koyracloud
registers custom hostnames with `ssl.method: txt`. Traefik does **not** mint a
Let's Encrypt cert for these hosts — Cloudflare terminates their TLS at the edge
and the app's SaaS-host router carries no cert resolver.

> Cert propagation lags the hostname going "Active" by a few minutes — a
> transient TLS `handshake failure` right after adding a domain is just the edge
> cert catching up; don't change anything.

## Deploy
```bash
DOCKER_CONTEXT=<your swarm context> ./deploy/deploy.sh
```
Builds the image, loads it onto the manager, and deploys/force-rolls the stack.

## Verify
```bash
curl -s https://<your host>/api/health        # {"status":"ok"}
docker --context <ctx> service logs -f koyracloud_control-plane
```
