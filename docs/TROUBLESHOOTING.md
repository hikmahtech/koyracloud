# Troubleshooting — first-run & deploy failures

The known failure modes, by the exact error you'll see. `install.sh` prevents
most of these up front; this is the reference for when you hit one anyway.

## Stack deploy fails immediately

**`network "traefik_public" is declared as external, but could not be found`**
The edge overlay doesn't exist yet. `install.sh` creates it; by hand:
`docker network create --driver overlay --attachable traefik_public`.
If your edge network has a different name, set `KOYRA_TRAEFIK_NETWORK`.

**`network "monitoring" is declared as external, but could not be found`**
You set `KOYRA_MONITORING=1` (or run a pre-2026-07 stack file that hardwired
the network) without the `monitoring` overlay existing. Either create it —
`docker network create --driver overlay --attachable monitoring` — or leave
`KOYRA_MONITORING` blank: the monitoring join is optional and off by default.

**`secret not found`**
All eight Docker secrets are `external: true` and must exist before deploy:
`koyra_secret_key`, `koyra_session_secret`, `koyra_webhook_secret`,
`koyra_redis_admin_password`, `koyra_github_client_secret`, `koyra_github_pat`,
`koyra_resend_api_key`, `koyra_cloudflare_api_token`. `install.sh` creates all
of them (a skipped optional secret is stored as a single space — the control
plane treats it as "feature off"). By hand, see `deploy/README.md` §5.

## A service stays 0/1

Diagnose with `docker service ps <service> --no-trunc` — the `ERROR` column has
the real reason.

**`invalid mount config for type "bind": bind source path does not exist`**
Swarm bind mounts do NOT auto-create host directories (unlike `docker run -v`).
Create them on the control node: `sudo mkdir -p /var/lib/koyracloud
/mnt/koyracloud` (your `KOYRA_DB_DIR` and `KOYRA_NFS_BASE`). `install.sh` does
this for you when the docker context points at the control node.

**`no suitable node (scheduling constraints not satisfied on N nodes)`**
The control plane is pinned with `node.hostname == ${KOYRA_CONTROL_NODE}`.
An empty or wrong value matches no node. Set `KOYRA_CONTROL_NODE` to a manager
hostname exactly as `docker node ls` prints it, and redeploy.

**registry / redis stuck 0/1 with an NFS mount error (`invalid argument`,
`failed to resolve server`, `permission denied`)**
Their volumes are NFS-backed only when `KOYRA_NFS_SERVER` is set (deploy.sh
then applies `deploy/koyracloud-nfs.yml`). Check: the server IP is right, the
export allows every node, and `<KOYRA_NFS_BASE>/registry` + `/redis` exist on
the export. Single node? Leave `KOYRA_NFS_SERVER` blank — local volumes are
used and NFS never enters the picture. (Redis writes its AOF as root through
`root_squash` by design — the volume mounts with `nocopy` to skip the chown
that squash would deny.)

## Sign-in problems

**GitHub OAuth succeeds but you get "not allowed" / bounced back**
The allowlist is fail-closed: an empty `KOYRA_ALLOWED_LOGINS` (or the literal
`your-github-login` placeholder) denies everyone, including you. Set it to your
GitHub login (comma-separated for several), redeploy, sign in again.

**OAuth error / redirect mismatch before the allowlist even runs**
`GITHUB_CLIENT_ID` unset, or the OAuth app's callback isn't
`${KOYRA_BASE_URL}/api/auth/callback`.

## First app deploy fails

**Build/push works, then the container starts and is killed ~30–60 s later**
Your image has no `python3` and the manifest sets `healthcheck:` — the probe
execs `python3 -c` *inside the container*, so on a slim/alpine/scratch base it
always fails and swarm kills the healthy-looking task. Install python3
(`RUN apk add --no-cache python3`) or remove the `healthcheck:` field.
(Generated-runtime apps aren't affected — the base image ships python3.)

**Deploy fails with a convergence timeout on a slow first build/start**
The deploy waits for every replica to be Running (and healthy) on the new
image, up to `KOYRA_DEPLOY_CONVERGE_TIMEOUT` (default 660 s); healthcheck
failures don't count during `KOYRA_HEALTHCHECK_START_PERIOD` (default 600 s).
A first start that compiles/installs for longer needs both raised — keep the
converge timeout above the grace period.

**Manifest builds fail with the runtime image missing**
Generated app images build `FROM` the base buildpack image
(`KOYRA_RUNTIME_IMAGE`), which lives only in the control node's local daemon —
a `docker system prune` can delete it (#66). Rebuild it:
`docker build -f runtime-image/Dockerfile -t koyracloud-runtime:latest runtime-image/`
(or re-run `install.sh`, which is idempotent).

**`http: server gave HTTP response to HTTPS client` when a node pulls an app
image**
Docker treats `127.0.0.1` registries as insecure-OK by default, which the
internal registry relies on. A daemon hardened to disable that needs
`"insecure-registries": ["127.0.0.1:5000"]` in `/etc/docker/daemon.json` on
every node.

**`database is locked` in the deploy log**
The control-plane SQLite is on a network filesystem. It must live on the
control node's LOCAL disk (`KOYRA_DB_DIR`); WAL mode is unsupported on NFS.
Migration runbook: [`DISASTER-RECOVERY.md`](DISASTER-RECOVERY.md) § "Moving the
DB off NFS".

## The dashboard 404s / has no TLS

Traefik isn't routing it: confirm Traefik is attached to `traefik_public`
(or your `KOYRA_TRAEFIK_NETWORK`), its HTTPS entrypoint matches
`KOYRA_HTTPS_ENTRYPOINT` (default `websecure`), its ACME resolver name matches
`KOYRA_CERT_RESOLVER` (default `letsencrypt`), and the `KOYRA_HOST` DNS record
points at the edge node. The example edge in
`deploy/examples/traefik-stack.yml` satisfies all of it.

## Still stuck?

`docker service logs koyracloud_control-plane --tail 100` usually names the
problem — and please open an issue with that output (minus anything secret).
