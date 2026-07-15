# Permissions & access

What the control plane actually touches, and the minimum grant for each — for
operators who want to scope credentials down before exposing this to the
internet. Every claim below is tied to the code path that uses it; nothing
here is aspirational. See [`SECURITY.md`](../SECURITY.md) for the threat model
this all sits inside (single-operator, trusted code) and
[`deploy/README.md`](../deploy/README.md) §5 for how each secret is created.

## 1. Docker socket — root-equivalent, no lesser scope works

`/var/run/docker.sock` is bind-mounted into the control-plane container
(`deploy/koyracloud-stack.yml`) from a manager node. `docker_ctl.CLIDockerControl`
shells out to the `docker` CLI against it for:

| Use | Docker command | Code path |
|---|---|---|
| Build a per-app image | `docker build` | `deployer._run_deploy` → `docker.image_build` |
| Tag it `:latest` | `docker tag` | `docker.image_tag` |
| Push to the internal registry | `docker push` | `docker.image_push` |
| Deploy/update the app's stack | `docker stack deploy` | `docker.deploy` |
| Tear an app down | `docker stack rm` | `docker.remove` (`delete_app`) |
| Read live replica/task state | `docker service inspect`, `docker service ps` | `docker.service_status` (deploy convergence, `/api/apps/{id}/status`) |
| List every service's replica counts | `docker service ls` | `docker.services_overview` (dashboard status dots, 5s cache) |
| Tail runtime logs | `docker service logs` | `docker.service_logs` |
| Run a cron job to completion | `docker service create --mode replicated-job`, then `docker service rm` | `scheduler.launch` → `docker.run_job` / `remove_service` |

**Be honest about what this means:** deploying and updating Swarm services is
the core of the product, so the socket grant has to include service create/
update. That alone is already root-equivalent on the node — a service spec can
set `privileged: true` or bind-mount `/` from the host, and nothing in the
Docker API validates against that. A **docker-socket-proxy** (endpoint-category
allow-listing, e.g. `tecnativa/docker-socket-proxy`) doesn't change this: it
gates *which* endpoints a caller may hit (`SERVICES`, `BUILD`, `IMAGES`,
`DISTRIBUTION`, `TASKS`, `NETWORKS`, `SECRETS`-read — koyracloud needs all of
these, since `docker stack deploy` alone touches most of them), not what a
permitted request's body contains. Since `SERVICES` write is non-negotiable
here, a proxy narrows the *attack surface* (fewer engine features reachable if
the process is compromised some other way) but not the *ceiling* (a compromised
control plane can still root the node either way). Treat "mounts the socket"
as "is root on that node," full stop, and mitigate at the placement layer
instead: run it on a manager you'd tolerate losing, keep it off nodes holding
anything more sensitive, and lean on the auth allowlist (§10) to keep untrusted
people from reaching it at all.

## 2. GitHub PAT (`koyra_github_pat`) — clone auth only

`deployer.git_clone` passes the token as an `http.extraHeader: Authorization:
Basic base64(x-access-token:<token>)` git config arg (`_auth_args`) — kept out
of argv/process listings and scrubbed from any error message
(`msg.replace(settings.github_pat, "***")`). It is used for exactly one thing:
authenticating `git clone` / `fetch` / `pull` over HTTPS against private repos.

- **Fine-grained token:** `Contents: Read-only`, scoped to the specific repos
  you'll deploy from. Nothing else is read or written through this token.
- **Classic token:** `repo` (fine-grained doesn't have a narrower classic
  equivalent for cloning).
- **Public-repo-only instance:** leave `koyra_github_pat` blank. `_auth_args`
  returns no header when the token is empty, so cloning falls back to
  anonymous HTTPS, which works fine for public repos.

## 3. GitHub OAuth App — login identity only

`auth.authorize_url` requests scope `read:user` — nothing else (`auth.py:47`).
The callback (`auth.exchange_code`) fetches `GET /user` and reads a single
field: `login`. No email, no repo access, no org membership is requested or
stored. This is a separate credential from the PAT in §2 — the OAuth app only
identifies who's signing into the dashboard.

## 4. Webhook secret (`koyra_webhook_secret`) — HMAC verification

`POST /api/webhooks/github` is unauthenticated but signature-gated:
`webhooks.verify_signature` does a constant-time HMAC-SHA256 check of GitHub's
`X-Hub-Signature-256` header against the raw request body. Only `push` and
`workflow_run` (completed+success) events map to a deploy
(`webhooks.deploy_target`); anything else, or a bad signature, is rejected
(401) or ignored. A blank secret makes `verify_signature` always return
`False` — the endpoint stays up but nothing it receives is trusted.

## 5. Cloudflare for SaaS token — scoped to the SaaS zone only

`cloudflare.py` calls exactly these endpoints, all under one zone
(`/zones/{zone_id}/...`):

| Call | Endpoint |
|---|---|
| Find / create a custom hostname | `GET`/`POST /custom_hostnames` |
| Poll cert status | `GET /custom_hostnames/{id}` |
| Remove on domain delete | `DELETE /custom_hostnames/{id}` |
| Zone's DCV delegation id | `GET /dcv_delegation/uuid` |

Required permission: **Zone → SSL and Certificates → Edit**, scoped to the one
SaaS zone (Zone Resources → Specific zone). **No DNS permission is needed** —
koyracloud never calls the DNS records API; `cloudflare.records_for` only
*computes* the CNAME values (`customer_records`) for the UI to show the user,
who adds them at their own registrar. Leave `KOYRA_CLOUDFLARE_ZONE_ID` blank
(or the token unset) to keep the whole feature off: `Cloudflare.configured` is
`False` and every method short-circuits to a no-op.

## 6. Resend key (`koyra_resend_api_key`) — email alerts only

`notifier.send_email` posts to `https://api.resend.com/emails` for deploy
live/failed, down/recovered alerts, the admin test-email button, and new
waitlist-signup notices. A blank key makes `send_email` return `False`
immediately — every caller already treats that as "notification skipped,"
never a hard failure.

## 7. Redis admin password (`koyra_redis_admin_password`)

Authenticates as the `default` user against the shared Redis instance the
control plane owns. Used only to run `ACL SETUSER` / `ACL DELUSER`
(`redisbus.RedisClientAdmin`), provisioning one scoped ACL user per app
(`~<app>:*` keys and channels, `+@all -@dangerous -@admin` — no `FLUSHALL`, no
reading another app's keyspace) on deploy, and dropping it on app delete. A
blank password disables the bus entirely: `redisbus.provision` raises loudly
if a manifest sets `redis: true`, and the `/metrics` Redis-reachability probe
is skipped (`app.py`'s `metrics_endpoint` only passes `_redis_ping` through
when the password is set — otherwise `redis_ping=None`).

## 8. Filesystem

| Var | Where | What touches it |
|---|---|---|
| `KOYRA_DB_DIR` | **Local disk** on the control node | The SQLite DB (WAL mode — unsupported on NFS, `#67`). Bind-mounted `/data`. |
| `KOYRA_NFS_BASE` | NFS export, mounted at the *same path* in the container | The control plane pre-creates each app's `persist:` directory here (`(nfs_base/app_name/d).mkdir(...)` in `deployer._run_deploy`) so the NFS-driver volume's device path resolves; app containers then mount their own subpath directly, not through the control plane. |
| `KOYRA_BUILD_DIR` | **Local disk** on the control node, never NFS | Scratch space for each deploy: `git_clone` checks out the repo here, `docker build` uses it as context, and it's `shutil.rmtree`'d in `_run_deploy`'s `finally` block once the image is pushed. |

## 9. Network exposure

- **Internal registry, port 5000, every node** — `registry:2` is published on
  the Swarm ingress mesh so any node can `docker pull 127.0.0.1:5000/...`, but
  the ingress mesh binds `0.0.0.0:5000` on *every* node, and the registry has
  no auth in front of it. Firewall 5000 from anything outside the swarm — see
  [`SECURITY.md`](../SECURITY.md) and tracking issue
  [#71](https://github.com/hikmahtech/koyracloud/issues/71) for a real fix.
- **`/metrics` stays off the public router** — the Traefik label
  ``!PathPrefix(`/metrics`)`` (`koyracloud-stack.yml`) blocks it at the edge;
  Prometheus reaches it only in-cluster over the `monitoring` overlay
  (`docs/MONITORING.md`). It's unauthenticated by design, so this exclusion is
  load-bearing, not cosmetic.
- **Ports 80/443** aren't opened by the control plane's own stack at all —
  they belong to whatever Traefik edge you deploy separately (see
  `deploy/examples/traefik-stack.yml`), a prerequisite this repo doesn't own.

## 10. Auth model

Access is a fail-closed allowlist, not a role system. `KOYRA_ALLOWED_LOGINS`
(comma-separated GitHub logins, env-configured) are **admins**: always allowed
in, and the only ones who can manage the invite list, the waitlist, and the
test-email button. An empty allowlist denies *everyone*, including whoever set
it up (`auth.is_allowed` — no logins in the list, no access). **Invited
members** are a separate, admin-managed set stored in the `allowed_users` DB
table (added/removed via `/api/allowed-users`, admin-only); they can sign in
and use the dashboard but can't touch access control. Every authenticated
route checks `is_admin(login) or is_member(login)`; app-scoped routes add a
second check (`obj.owner_login == login or is_admin(login)`) so a non-admin
member only ever sees their own apps.

---

The Docker secrets not covered above — `koyra_secret_key` (Fernet master key
for app-secret encryption at rest) and `koyra_session_secret` (signs the
session cookie) — are locally-generated entropy with no external access of
their own; see `deploy/README.md` §5 for how all eight are created.
