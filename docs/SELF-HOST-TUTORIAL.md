# Self-hosting koyracloud — full tutorial

This walks you from bare Linux machines to a running koyracloud with your first
app live behind HTTPS. It fills in the Docker Swarm, Traefik, NFS and DNS pieces
that [`deploy/README.md`](../deploy/README.md) (the concise reference) assumes you
already have.

**What you'll end up with:** a Docker Swarm running koyracloud's control plane, an
internal registry and a shared Redis, behind a Traefik HTTPS edge — and an app you
deployed from a git repo, live at `https://<name>-<token>.<your-domain>`.

**Time:** ~30–45 minutes. **You need:** one or more Linux hosts with Docker, a
domain you control, and a GitHub account.

---

## 1. The machines

koyracloud runs on a **Docker Swarm**. One node is fine to start; more nodes give
you rescheduling if one dies. On every host:

- Install Docker Engine (https://docs.docker.com/engine/install/).
- Make sure ports **80** and **443** are reachable from the internet on at least
  one node (the Traefik edge), or front it with a tunnel/proxy (see §6).

## 2. Initialize the Swarm

On the machine you want as the **manager**:

```bash
docker swarm init --advertise-addr <this-node-ip>
```

It prints a `docker swarm join ...` command — run that on any **worker** nodes you
want to add. Check the cluster from the manager:

```bash
docker node ls
```

> Single node? That's fine — the manager is also a worker. Everything below works.

## 3. Shared storage (NFS)

Persistent app data, the image registry and Redis live on storage every node can
reach. The simplest is an **NFS export**.

- **Multiple nodes:** stand up an NFS server (or use your NAS) exporting e.g.
  `/srv/koyracloud`, reachable from every node. Note its IP — it becomes
  `KOYRA_NFS_SERVER`. Create these directories on the export now:
  ```bash
  mkdir -p /srv/koyracloud/{registry,redis}
  ```
- **Single node / trying it out:** leave `KOYRA_NFS_SERVER` blank — koyracloud
  falls back to plain bind mounts under `KOYRA_NFS_BASE` (a local path).

## 4. DNS

Pick a domain for your apps, e.g. `apps.example.com` (one label deep so a single
free wildcard cert can cover it). Add two records at your DNS provider:

| Record | Name | Points at |
|--------|------|-----------|
| `A` (or wildcard) | `*.apps.example.com` | your edge node's public IP |
| `A` | `koyra.example.com` (the dashboard) | your edge node's public IP |

Every app gets `https://<name>-<token>.apps.example.com` automatically; the
dashboard/control plane lives at `koyra.example.com` (this becomes `KOYRA_HOST`).

## 5. The Traefik edge

koyracloud renders Traefik labels on each app; Traefik does the routing + TLS.
Create the shared network and deploy the example edge:

```bash
docker network create --driver overlay --attachable traefik_public

export ACME_EMAIL=you@example.com
docker stack deploy -c deploy/examples/traefik-stack.yml traefik
```

That `traefik-stack.yml` terminates TLS on a `websecure` entrypoint and mints
Let's Encrypt certs via a resolver named `letsencrypt` (the default
`KOYRA_CERT_RESOLVER`) using the HTTP-01 challenge — so it needs inbound `:80`
and `:443`. Already run Traefik? Just make sure it's on `traefik_public`, has a
`websecure` entrypoint, and a cert resolver whose name you'll put in
`KOYRA_CERT_RESOLVER`.

## 6. (Optional) Behind a tunnel / proxy

No open inbound ports? Front the edge with a Cloudflare Tunnel (or similar) and
set `KOYRA_APPS_DOMAIN_PROXIED=1` in your config — the proxy serves TLS and
Traefik skips ACME for in-zone hosts. For attaching customers' **custom domains**
(Vercel-style, edge-minted certs) see [`MIGRATING-FROM-VERCEL.md`](MIGRATING-FROM-VERCEL.md).

## 7. A GitHub OAuth app

Sign-in is GitHub OAuth behind an allowlist. Create an OAuth app at
**GitHub → Settings → Developer settings → OAuth Apps → New**:

- **Homepage URL:** `https://koyra.example.com`
- **Authorization callback URL:** `https://koyra.example.com/api/auth/callback`

Keep the **Client ID** (goes in config) and **Client Secret** (a Docker secret).

## 8. Configure + install

Clone the repo and run the guided installer against your swarm:

```bash
git clone https://github.com/hikmahtech/koyracloud.git
cd koyracloud

# Fill in your instance config (domain, NFS server, GitHub login, host):
cp deploy/koyracloud.env.example deploy/koyracloud.env
$EDITOR deploy/koyracloud.env

# Network + secrets + base image + deploy, all guided:
DOCKER_CONTEXT=<your-swarm-context> ./deploy/install.sh
```

`install.sh` creates the `traefik_public` network if missing, generates the random
Docker secrets (Fernet key, session/webhook secrets, Redis admin password),
prompts for the GitHub credentials, builds the base buildpack image, and runs the
deploy. It's idempotent — re-run it any time.

> Prefer to do it by hand, or want every secret command spelled out? Follow
> [`deploy/README.md`](../deploy/README.md) §5 instead, then run `./deploy/deploy.sh`.

`<your-swarm-context>` is a Docker context pointing at your manager (`docker context
create swarm --docker host=ssh://user@manager`), or `default` if you're on the
manager itself.

## 9. Verify

```bash
# control plane is up
curl -s https://koyra.example.com/api/health        # {"status":"ok"}

# all three services are 1/1
docker --context <your-swarm-context> service ls --filter name=koyracloud
```

Open `https://koyra.example.com`, sign in with GitHub (the account must be in
`KOYRA_ALLOWED_LOGINS`).

## 10. Deploy your first app

In the repo you want to deploy, add a `.paas/app.yaml`
([reference](https://koyra.example.com/docs) or [`examples/`](../examples/)):

```yaml
name: my-app
runtime: python+node
port: 8000
build:
  - pip install -r requirements.txt
start: uvicorn app.main:app --host 0.0.0.0 --port 8000
healthcheck: /health
```

Then in the dashboard: **New App** → paste the repo URL + branch → **Deploy**, and
watch the live build → push → run log. It comes up at
`https://my-app-<token>.apps.example.com`.

## 11. Going further

- **Push-to-deploy:** turn on Auto-deploy and add the GitHub webhook shown in the
  app's Settings tab.
- **Custom domains:** the Domains tab (with Cloudflare for SaaS configured, certs
  are minted at the edge — no nameserver move).
- **Background work:** declare `workers:`, `cron:` and `redis: true` in the manifest
  — always-on workers, scheduled jobs and a per-app Redis bus, from the same repo.
  See the **Workers, cron & Redis** section of the docs.

---

That's a full koyracloud. For *why* it's built this way (build-into-image, the
internal registry, nothing-pinned), see [`ARCHITECTURE.md`](ARCHITECTURE.md).
