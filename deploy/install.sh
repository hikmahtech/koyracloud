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
command -v openssl >/dev/null || { echo "openssl is required (secret generation)"; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required (Fernet key generation)"; exit 1; }
python3 -c 'import cryptography.fernet' 2>/dev/null || {
  echo "the python 'cryptography' package is required: pip install cryptography"; exit 1; }
if [ "$(d info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null || true)" != "active" ]; then
  warn "This node is not part of a Docker Swarm."
  read -rp "  Run 'docker swarm init' now? [y/N] " yn
  [ "${yn:-}" = y ] || { echo "Initialize/join a swarm first, then re-run."; exit 1; }
  d swarm init
fi
# Secrets + stack deploy only work against a MANAGER; a worker context fails
# late with "This node is not a swarm manager".
if [ "$(d info --format '{{.Swarm.ControlAvailable}}')" != "true" ]; then
  echo "docker context '$CTX' points at a swarm WORKER — use a manager context."; exit 1
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

# Values that deploy fine but leave the instance unreachable or locked out —
# refuse placeholders/blanks up front instead of debugging a 0/1 service later.
case "${KOYRA_ALLOWED_LOGINS:-}" in
  ""|your-github-login)
    echo "Set KOYRA_ALLOWED_LOGINS in deploy/koyracloud.env to YOUR GitHub login —"
    echo "the allowlist is fail-closed, so the placeholder locks you out after OAuth."
    exit 1;;
esac
case "${KOYRA_HOST:-}" in
  ""|koyracloud.example.com)
    echo "Set KOYRA_HOST in deploy/koyracloud.env to your control-plane hostname."; exit 1;;
esac
if [ -z "${GITHUB_CLIENT_ID:-}" ]; then
  echo "Set GITHUB_CLIENT_ID in deploy/koyracloud.env — register a GitHub OAuth App"
  echo "with callback ${KOYRA_BASE_URL:-https://<KOYRA_HOST>}/api/auth/callback first"
  echo "(deploy/README.md §6); without it nobody can sign in."
  exit 1
fi
# Empty KOYRA_CONTROL_NODE renders the placement constraint `node.hostname ==`
# (matches nothing; the service silently never schedules). Auto-pick when the
# swarm has exactly one manager, else make the user choose.
if [ -z "${KOYRA_CONTROL_NODE:-}" ]; then
  MANAGERS=$(d node ls --filter role=manager --format '{{.Hostname}}')
  if [ "$(printf '%s\n' "$MANAGERS" | wc -l)" = 1 ] && [ -n "$MANAGERS" ]; then
    KOYRA_CONTROL_NODE="$MANAGERS"; export KOYRA_CONTROL_NODE
    sed -i "s/^KOYRA_CONTROL_NODE=$/KOYRA_CONTROL_NODE=${KOYRA_CONTROL_NODE}/" deploy/koyracloud.env
    warn "KOYRA_CONTROL_NODE was empty — using the only manager '${KOYRA_CONTROL_NODE}' (saved to deploy/koyracloud.env)."
  else
    echo "Set KOYRA_CONTROL_NODE in deploy/koyracloud.env to one of your managers:"
    printf '%s\n' "$MANAGERS"
    exit 1
  fi
fi

# --- 4. Docker secrets (idempotent) -----------------------------------------
have() { d secret inspect "$1" >/dev/null 2>&1; }
mk() {   # mk <name> <value>   — create only if missing; refuse an empty value
  if have "$1"; then echo "  • $1 (exists)"; return; fi
  # A failed generator inside "$( )" doesn't trip set -e — catch it here so we
  # never silently create an empty Fernet key / session secret.
  [ -n "$2" ] || { echo "refusing to create EMPTY secret $1 — its generator failed"; exit 1; }
  printf '%s' "$2" | d secret create "$1" - >/dev/null && echo "  • $1 (generated)"
}
ask() {  # ask <name> <prompt>  — create from a hidden prompt if missing (blank ok)
  if have "$1"; then echo "  • $1 (exists)"; return; fi
  printf '  %s (blank to skip): ' "$2" >&2; read -rs v; echo >&2
  # Skipped → store a single space: some Docker versions reject zero-byte
  # secrets, and the control plane strips whitespace, so " " reads as
  # "feature off" exactly like an empty value.
  printf '%s' "${v:- }" | d secret create "$1" - >/dev/null \
    && echo "  • $1 ($([ -n "$v" ] && echo set || echo blank — feature off))"
}

say "Creating Docker secrets"
mk koyra_secret_key        "$(python3 -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())' || true)"
mk koyra_session_secret    "$(openssl rand -hex 32)"
mk koyra_webhook_secret    "$(openssl rand -hex 32)"
mk koyra_redis_admin_password "$(openssl rand -hex 24)"
ask koyra_github_client_secret "GitHub OAuth app client secret"
ask koyra_github_pat           "GitHub PAT for cloning private repos"
ask koyra_resend_api_key       "Resend API key (email alerts, optional)"
ask koyra_cloudflare_api_token "Cloudflare for SaaS token (custom domains, optional)"

# --- 5. Host dirs -------------------------------------------------------------
# Swarm bind mounts do NOT auto-create missing host dirs (the task is rejected
# with "bind source path does not exist"), so the control node needs the DB dir
# and the NFS-base dir before deploy. When the context's daemon IS the control
# node (always true single-node), create them via a helper container; otherwise
# tell the user exactly what to run there.
DB_DIR="${KOYRA_DB_DIR:-${KOYRA_NFS_BASE:-/mnt/koyracloud}/cp}"
NFS_BASE="${KOYRA_NFS_BASE:-/mnt/koyracloud}"
if [ "$(d info --format '{{.Name}}')" = "${KOYRA_CONTROL_NODE}" ]; then
  say "Creating host dirs on ${KOYRA_CONTROL_NODE}: ${DB_DIR} ${NFS_BASE}"
  d run --rm -v /:/host busybox mkdir -p "/host${DB_DIR}" "/host${NFS_BASE}" >/dev/null
else
  warn "Create these once on ${KOYRA_CONTROL_NODE} (bind-mount sources must pre-exist):"
  warn "    sudo mkdir -p ${DB_DIR} ${NFS_BASE}"
fi
if [ -n "${KOYRA_NFS_SERVER:-}" ]; then
  warn "Create these once on your NFS export (${KOYRA_NFS_SERVER}:${NFS_BASE}):"
  warn "    ${NFS_BASE}/registry   ${NFS_BASE}/redis"
fi

# --- 6. Base buildpack image (FROM for generated app images) -----------------
RUNTIME="${KOYRA_RUNTIME_IMAGE:-${KOYRA_REGISTRY:-127.0.0.1:5000}/koyracloud-runtime:latest}"
say "Building the base buildpack image: $RUNTIME"
docker build -f runtime-image/Dockerfile -t "$RUNTIME" runtime-image/
if [ "$CTX" != default ]; then
  say "Loading $RUNTIME onto $CTX"
  docker save "$RUNTIME" | d load
fi

# --- 7. Deploy the control plane + registry + redis --------------------------
say "Deploying the koyracloud stack"
DOCKER_CONTEXT="$CTX" bash deploy/deploy.sh

# --- 8. Push the buildpack image into the instance registry ------------------
# The image is a build-time-only FROM — no running container references it — so
# a local-only copy is silently deleted by any `docker system prune` and every
# manifest build then fails with "pull access denied" (#66). Pushing it to the
# stack's own registry makes `docker build` re-pull it on demand. Skipped when
# KOYRA_RUNTIME_IMAGE points outside the instance registry (you manage it).
case "$RUNTIME" in
  "${KOYRA_REGISTRY:-127.0.0.1:5000}"/*)
    say "Pushing $RUNTIME to the instance registry"
    for i in $(seq 1 30); do
      if d push "$RUNTIME" >/dev/null 2>&1; then echo "  • pushed"; break; fi
      [ "$i" = 30 ] && { warn "registry not answering — push it later: docker push $RUNTIME"; break; }
      sleep 2
    done;;
  *) warn "KOYRA_RUNTIME_IMAGE is not in the instance registry — make sure it survives image prunes.";;
esac

say "Done. Open https://${KOYRA_HOST:-<your KOYRA_HOST>} and sign in with GitHub."
