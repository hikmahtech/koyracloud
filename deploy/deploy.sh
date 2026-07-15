#!/usr/bin/env bash
# Build + load the control-plane image onto the manager and deploy the stack.
# Instance config lives in deploy/koyracloud.env (gitignored). Prereqs and the
# eight Docker secrets are described in deploy/README.md.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE=${KOYRA_ENV_FILE:-deploy/koyracloud.env}
if [ -f "$ENV_FILE" ]; then
  set -a; . "$ENV_FILE"; set +a
else
  echo "warning: $ENV_FILE not found — relying on the current environment" >&2
fi

# Fail fast on config that deploys fine but never schedules/routes: an empty
# KOYRA_CONTROL_NODE renders the constraint `node.hostname ==` (matches no
# node, service silently stays 0/1); an empty KOYRA_HOST renders an invalid
# Traefik rule Host(``).
: "${KOYRA_CONTROL_NODE:?set KOYRA_CONTROL_NODE in $ENV_FILE — a manager hostname (docker node ls)}"
: "${KOYRA_HOST:?set KOYRA_HOST in $ENV_FILE — the control-plane hostname}"

# Your swarm's docker context (see `docker context ls`); falls back to the
# current/active context.
CTX=${DOCKER_CONTEXT:-default}
IMAGE=${KOYRA_IMAGE:-koyracloud:local}

echo "==> building $IMAGE locally"
# KOYRA_GA_MEASUREMENT_ID (from koyracloud.env, optional) is baked into the SPA at
# build time; empty => no analytics tag.
docker build -f control-plane/Dockerfile -t "$IMAGE" \
  --build-arg KOYRA_GA_MEASUREMENT_ID="${KOYRA_GA_MEASUREMENT_ID:-}" .

echo "==> loading $IMAGE onto $CTX"
docker save "$IMAGE" | docker --context "$CTX" load

echo "==> deploying stack"
export KOYRA_IMAGE="$IMAGE"
# DB dir default: the legacy NFS path, so installs that predate KOYRA_DB_DIR
# keep their DB. Set KOYRA_DB_DIR (koyracloud.env) to a local path on the
# control node — SQLite WAL is unsupported on NFS (#67).
export KOYRA_DB_DIR="${KOYRA_DB_DIR:-${KOYRA_NFS_BASE:-/mnt/koyracloud}/cp}"
# Base stack + opt-in overlays: NFS-backed registry/redis volumes when an NFS
# server is configured (multi-node), and the `monitoring` network join for
# swarms that run the Prometheus overlay (see the files for details).
STACK_FILES=(-c deploy/koyracloud-stack.yml)
if [ -n "${KOYRA_NFS_SERVER:-}" ]; then
  STACK_FILES+=(-c deploy/koyracloud-nfs.yml)
fi
if [ "${KOYRA_MONITORING:-}" = "1" ]; then
  STACK_FILES+=(-c deploy/koyracloud-monitoring.yml)
fi
docker --context "$CTX" stack deploy --resolve-image=never \
  "${STACK_FILES[@]}" koyracloud
# Same image tag + unchanged spec won't recreate the task, so force a roll to
# pick up the rebuilt image.
docker --context "$CTX" service update --force koyracloud_control-plane >/dev/null

echo "==> done. service:"
docker --context "$CTX" service ls --filter name=koyracloud
