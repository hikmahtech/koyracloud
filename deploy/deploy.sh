#!/usr/bin/env bash
# Build + load the control-plane image onto the manager and deploy the stack.
# Instance config lives in deploy/koyracloud.env (gitignored). Prereqs and the
# four Docker secrets are described in deploy/README.md.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE=${KOYRA_ENV_FILE:-deploy/koyracloud.env}
if [ -f "$ENV_FILE" ]; then
  set -a; . "$ENV_FILE"; set +a
else
  echo "warning: $ENV_FILE not found — relying on the current environment" >&2
fi

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
docker --context "$CTX" stack deploy --resolve-image=never \
  -c deploy/koyracloud-stack.yml koyracloud
# Same image tag + unchanged spec won't recreate the task, so force a roll to
# pick up the rebuilt image.
docker --context "$CTX" service update --force koyracloud_control-plane >/dev/null

echo "==> done. service:"
docker --context "$CTX" service ls --filter name=koyracloud
