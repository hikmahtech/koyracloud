# Permissions the control plane needs

koyracloud is built for a **single, trusted operator** (see the
[non-goals](../README.md#non-goals) and [`SECURITY.md`](../SECURITY.md)), not
for locking a hostile tenant out of the host. This doc exists so
security-conscious self-hosters know exactly what they're granting, and can
make an informed call about where to run it — not so they can strip access
down to something the control plane doesn't need and won't work with.

## Docker socket — root-equivalent, no way around it

The control plane mounts `/var/run/docker.sock` read-write
(`deploy/koyracloud-stack.yml`) and shells out to the `docker` CLI
(`koyracloud/docker_ctl.py`) to:

- `docker build` / `tag` / `push` — build a per-app image from a cloned repo
  and push it to the internal registry.
- `docker stack deploy` / `stack rm` — deploy, update, and tear down every
  app's Swarm stack, including labels, networks, and secrets.
- `docker service logs` / `ps` / `ls` / `inspect` — read runtime status and
  logs for any service on the swarm, not just koyracloud's own.
- `docker service create --mode replicated-job` / `service rm` — launch cron
  jobs as one-off Swarm jobs and reap them when done.

There is no scoped-down mode. A process with the Docker socket can create a
privileged container, bind-mount the host root, and read/write anything on
that node — this is Docker's model, not something koyracloud adds on top.
**Access to the socket is equivalent to root on every node in the swarm.**

What actually gates this in practice:

- The control-plane service is `placement: constraints: node.role == manager`
  (see `koyracloud-stack.yml`) — it never runs on a worker.
- The socket is reachable only from inside that one container; nothing about
  koyracloud exposes it over the network.
- The only thing standing between "anyone on the internet" and "docker socket"
  is the GitHub OAuth allowlist (`KOYRA_ALLOWED_LOGINS`) — see below. Treat
  that list with the same care as root's `authorized_keys`.

If you want an actually isolated blast radius, run the control plane on its
own dedicated manager (or a single-node swarm) that hosts nothing else
sensitive — don't rely on filesystem or network controls to contain it.

## The internal Docker registry

The `registry` service (`registry:2`) is published on the swarm's ingress
mesh so every node can pull from it at `127.0.0.1:5000` — an
[insecure-by-default](https://docs.docker.com/registry/insecure/) registry
with no auth in front of it. It is reachable only from nodes on the swarm's
data plane, not from the public internet, but it is **not authenticated** —
anything that can reach port 5000 on any swarm node can pull (and, with
`REGISTRY_STORAGE_DELETE_ENABLED=true`, delete) images. Don't publish 5000 on
a public interface or bridge it onto a network that isn't swarm-internal.

## Filesystem / NFS

The control plane needs read-write access to:

- `${KOYRA_NFS_BASE}/cp` → mounted at `/data` — the SQLite DB, uploaded
  secrets (encrypted), and backups.
- `${KOYRA_NFS_BASE}` (the whole tree) → mounted at the same path — app
  `persist:` volumes and the registry/redis NFS-driver volumes live under
  here; the control plane and the app containers need to see the same paths.
- `${KOYRA_BUILD_DIR}` (default `/tmp/koyra-build`, **local disk, not NFS** —
  see `deploy/README.md` §4) — where repos are cloned and images are built.
  NFS's small-file I/O makes `npm ci` / `pip install` slow enough to matter,
  and can starve the control plane's own DB if the NFS link is saturated.

If `KOYRA_NFS_SERVER` is set, the registry and Redis volumes are Docker
NFS-driver volumes (`driver_opts: type: nfs`) so a reschedule to a different
node doesn't lose data. Docker mounts these itself; the export just needs
`<nfs>/koyracloud/registry` and `<nfs>/koyracloud/redis` created once, host
permissions permitting the export's squash settings (see the `nocopy`
comment in `koyracloud-stack.yml` for the root-squash caveat with Redis).

## GitHub — two separate credentials, different scopes

**1. OAuth App (login only).** `koyracloud/auth.py` requests exactly the
`read:user` scope — enough to read the authenticated user's `login` and check
it against `KOYRA_ALLOWED_LOGINS`. It never reads or touches repos with this
token; the OAuth token isn't even persisted past the login exchange. The
Client Secret is a Docker secret (`koyra_github_client_secret`).

**2. Personal Access Token (repo cloning).** `GITHUB_PAT` /
`koyra_github_pat` is used **only** by `deployer.git_clone` to authenticate
`git clone` / `fetch` / `pull` over HTTPS (passed as an `Authorization`
header via `git -c http.extraHeader`, never embedded in the URL or written to
argv/logs — see `deployer._auth_args`). It needs read access to whatever
repos you'll deploy from:

- Classic PAT: `repo` scope for private repos, or no scope at all (leave it
  set to a token with `public_repo` only, or use no PAT and a `https://`
  clone URL) if every app you deploy is public.
- Fine-grained PAT: `Contents: Read-only`, scoped to the specific
  repositories you intend to deploy.

The PAT is never used to call the GitHub API — only to authenticate git
transport. It doesn't need `workflow`, `admin:*`, or write scopes of any
kind.

**3. Webhook secret (push-to-deploy).** `KOYRA_WEBHOOK_SECRET` is a shared
HMAC secret you set on the GitHub webhook, not an OAuth scope — it verifies
`X-Hub-Signature-256` on incoming push events. No GitHub permissions are
requested for this at all.

## Cloudflare for SaaS (optional — custom domains)

Inert unless both `KOYRA_CLOUDFLARE_ZONE_ID` and the
`koyra_cloudflare_api_token` secret are set. When active,
`koyracloud/cloudflare.py` only calls the zone's `custom_hostnames`
endpoints (create/list/get/delete). The token needs, scoped to **your SaaS
zone only** (not "All zones"):

- `Zone → SSL and Certificates → Edit`
- `Zone → DNS → Read`

No `Zone → DNS → Edit`, no account-level permissions, no access to any other
zone.

## Redis admin password (optional — shared Redis bus)

`koyra_redis_admin_password` authenticates as the Redis `default` user. The
control plane uses it only to provision/revoke a scoped ACL user per app that
opts into `redis: true` — apps themselves never see the admin password, only
their own ACL user's credentials via the injected `REDIS_URL`. Leaving the
secret blank disables the feature entirely (deploys requesting `redis: true`
fail loudly instead of silently working with shared creds).

## Resend API key (optional — email alerts)

`RESEND_API_KEY` / `koyra_resend_api_key` is used only to send transactional
alert emails (deploy failures, uptime alerts). A [Resend](https://resend.com)
API key scoped to **Sending access only** is sufficient — koyracloud never
reads inboxes, domains, or account settings via this key.

## Summary

| Credential | Where | Minimum scope | Used for |
|---|---|---|---|
| Docker socket | host mount | n/a (inherently root-equivalent) | build/push/deploy/manage everything on the swarm |
| GitHub OAuth Client Secret | `koyra_github_client_secret` | `read:user` (requested in code, not configurable) | identify the logging-in user against the allowlist |
| GitHub PAT | `koyra_github_pat` | `repo` (private) / none (public-only) | `git clone`/`fetch`/`pull` over HTTPS |
| Webhook secret | `koyra_webhook_secret` | n/a (shared HMAC secret) | verify push-to-deploy webhook signatures |
| Cloudflare API token | `koyra_cloudflare_api_token` | `Zone:SSL and Certificates:Edit` + `Zone:DNS:Read`, scoped to one zone | custom-hostname registration for user domains |
| Redis admin password | `koyra_redis_admin_password` | n/a (shared secret) | provision per-app Redis ACL users |
| Resend API key | `koyra_resend_api_key` | Sending access only | transactional alert emails |
| NFS export | `KOYRA_NFS_BASE` | read-write | DB, backups, app persist volumes, registry/redis storage |

Everything above except the Docker socket is optional or narrowly scoped by
design — the socket is the one access grant you can't shrink, only isolate
by running the control plane on a manager node that hosts nothing else you
care about.
