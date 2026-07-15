#!/usr/bin/env bash
# Guided installer for koyracloud — an EXAMPLE / starting point. Idempotent:
# safe to re-run (it skips anything already in place). It sets up the Docker-side
# prerequisites (overlay network + secrets), builds the images, and deploys the
# stack. The host-side prerequisites it CANNOT reliably do for you across a remote
# context — a Traefik edge, NFS export + its dirs, and DNS — are pointed out as it
# goes; the full walkthrough is in docs/SELF-HOST-TUTORIAL.md.
#
# Usage:
#   DOCKER_CONTEXT=<your-swarm-context> ./deploy/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."

CTX="${DOCKER_CONTEXT:-default}"
d() { docker --context "$CTX" "$@"; }
say()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$*" >&2; }

say "Installing koyracloud onto docker context: $CTX  (override with DOCKER_CONTEXT=...)"

# --- 1. Docker + Swarm -------------------------------------------------------
command -v docker >/dev/null || { echo "docker is not installed"; exit 1; }
if [ "$(d info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null || true)" != "active" ]; then
  warn "This node is not part of a Docker Swarm."
  read -rp "  Run 'docker swarm init' now? [y/N] " yn
  [ "${yn:-}" = y ] || { echo "Initialize/join a swarm first, then re-run."; exit 1; }
  d swarm init
fi

# --- 2. Traefik overlay network ---------------------------------------------
NET="${KOYRA_TRAEFIK_NETWORK:-traefik_public}"
if ! d network inspect "$NET" >/dev/null 2>&1; then
  say "Creating attachable overlay network: $NET"
  d network create --driver overlay --attachable "$NET" >/dev/null
fi
warn "koyracloud needs Traefik running on '$NET' (the HTTPS edge). If you don't"
warn "have one yet: deploy/examples/traefik-stack.yml is a ready starting point."

# --- 3. Instance config ------------------------------------------------------
if [ ! -f deploy/koyracloud.env ]; then
  cp deploy/koyracloud.env.example deploy/koyracloud.env
  warn "Created deploy/koyracloud.env from the example."
  warn "Edit it (your apps domain, NFS server, GitHub login, host), then re-run."
  exit 0
fi
set -a; . deploy/koyracloud.env; set +a

# --- 4. Docker secrets (idempotent) -----------------------------------------
have() { d secret inspect "$1" >/dev/null 2>&1; }
mk() {   # mk <name> <value>   — create only if missing
  if have "$1"; then echo "  • $1 (exists)"; else
    printf '%s' "$2" | d secret create "$1" - >/dev/null && echo "  • $1 (generated)"
  fi
}
ask() {  # ask <name> <prompt>  — create from a hidden prompt if missing (blank ok)
  if have "$1"; then echo "  • $1 (exists)"; return; fi
  printf '  %s (blank to skip): ' "$2" >&2; read -rs v; echo >&2
  printf '%s' "$v" | d secret create "$1" - >/dev/null && echo "  • $1 (set)"
}

say "Creating Docker secrets"
command -v python3 >/dev/null || { echo "python3 needed to generate the Fernet key"; exit 1; }
mk koyra_secret_key        "$(python3 -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
mk koyra_session_secret    "$(openssl rand -hex 32)"
mk koyra_webhook_secret    "$(openssl rand -hex 32)"
mk koyra_redis_admin_password "$(openssl rand -hex 24)"
ask koyra_github_client_secret "GitHub OAuth app client secret"
ask koyra_github_pat           "GitHub PAT for cloning private repos"
ask koyra_resend_api_key       "Resend API key (email alerts, optional)"
ask koyra_cloudflare_api_token "Cloudflare for SaaS token (custom domains, optional)"

# --- 5. NFS dirs (reminder) --------------------------------------------------
if [ -n "${KOYRA_NFS_SERVER:-}" ]; then
  warn "Create these once on your NFS export (${KOYRA_NFS_SERVER}:${KOYRA_NFS_BASE:-/mnt/koyracloud}):"
  warn "    ${KOYRA_NFS_BASE:-/mnt/koyracloud}/registry   ${KOYRA_NFS_BASE:-/mnt/koyracloud}/redis"
fi
if [ -n "${KOYRA_DB_DIR:-}" ]; then
  warn "Create the DB dir once on ${KOYRA_CONTROL_NODE:-the control node} (local disk): sudo mkdir -p ${KOYRA_DB_DIR}"
fi

# --- 6. Base buildpack image (FROM for generated app images) -----------------
RUNTIME="${KOYRA_RUNTIME_IMAGE:-koyracloud-runtime:latest}"
say "Building the base buildpack image: $RUNTIME"
docker build -f runtime-image/Dockerfile -t "$RUNTIME" runtime-image/
if [ "$CTX" != default ]; then
  say "Loading $RUNTIME onto $CTX"
  docker save "$RUNTIME" | d load
fi

# --- 7. Deploy the control plane + registry + redis --------------------------
say "Deploying the koyracloud stack"
DOCKER_CONTEXT="$CTX" bash deploy/deploy.sh

say "Done. Open https://${KOYRA_HOST:-<your KOYRA_HOST>} and sign in with GitHub."
