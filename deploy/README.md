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

### 4. The runtime image
Apps run the shared runtime image. Build it and either push it to a registry
reachable by all nodes, or (single-node / no-registry) load it onto the node and
set `KOYRA_APP_NODE` + `KOYRA_RESOLVE_IMAGE_NEVER=1`:
```bash
docker build -f runtime-image/Dockerfile -t koyracloud-runtime:latest runtime-image/
# registry:  docker tag … <registry>/koyracloud-runtime && docker push …
```

### 5. Secrets (Docker secrets, created once)
```bash
python3 -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())' \
  | tr -d '\n' | docker --context <ctx> secret create koyra_secret_key -
openssl rand -hex 32 | tr -d '\n' | docker --context <ctx> secret create koyra_session_secret -
printf '%s' '<github oauth client secret>' | docker --context <ctx> secret create koyra_github_client_secret -
printf '%s' '<github pat for cloning>'     | docker --context <ctx> secret create koyra_github_pat -
```
> Secrets are immutable. To rotate: detach, `secret rm`, recreate, redeploy.
> Never rotate `koyra_secret_key` (the Fernet master key) without re-encrypting
> stored app secrets.

### 6. GitHub OAuth App
Register an OAuth App with callback `https://<your host>/api/auth/callback`; put
the Client ID in `koyracloud.env` and the Client Secret in the Docker secret above.

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
