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

CTX=${DOCKER_CONTEXT:-swarm-baa}
IMAGE=${KOYRA_IMAGE:-koyracloud:local}

echo "==> building $IMAGE locally"
docker build -f control-plane/Dockerfile -t "$IMAGE" .

echo "==> loading $IMAGE onto $CTX"
docker save "$IMAGE" | docker --context "$CTX" load

echo "==> deploying stack"
export KOYRA_IMAGE="$IMAGE"
docker --context "$CTX" stack deploy --resolve-image=never \
  -c deploy/koyracloud-stack.yml koyracloud
# Same image tag + unchanged spec won't recreate the task, so force a roll to
# pick up the rebuilt image.
docker --context "$CTX" service update --force koyracloud_control-plane >/dev/null

echo "==> done. service:"
docker --context "$CTX" service ls --filter name=koyracloud
