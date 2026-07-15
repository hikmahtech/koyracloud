"""Render a per-app Dockerfile from its manifest. Pure + unit-tested.

The control plane builds this image locally (off NFS), pushes it to the internal
registry, and deploys the service from it — so the running container serves the
app from image layers, not an NFS-mounted workspace. NFS is used only for the
manifest's ``persist`` data dirs, mounted at runtime.
"""
from __future__ import annotations

import json
import shlex

from koyracloud.manifest import Manifest

# Static sites are served by koyra_static.py (baked into the runtime base image),
# auto-detecting the build output dir the same way the old entrypoint did.
_STATIC_DETECT = (
    "d=; for c in dist build public out _site; do "
    "[ -d \"/app/$c\" ] && d=$c && break; done; "
    'exec python3 /koyra_static.py --dir "/app/${d:-.}" --port %d'
)

_GO_BINARY = "/app/server"
_GO_DEFAULT_BUILD = f"CGO_ENABLED=0 go build -o {_GO_BINARY} ."


def _render_go_dockerfile(manifest: Manifest) -> str:
    """go is the odd one out: a two-stage build (golang:1.23 compiles a static
    binary, then a distroless runner just copies it in) instead of a layer on
    top of the shared python+node runtime image `base_image` — so it ignores
    base_image entirely. distroless/static has no shell, which is why CMD must
    be exec-form and why manifest.py rejects healthcheck/predeploy for this
    runtime (both need a shell/python3 this image doesn't have)."""
    build_steps = manifest.build or [_GO_DEFAULT_BUILD]
    lines = [
        "FROM golang:1.23 AS build",
        "WORKDIR /app",
        "COPY . .",
    ]
    lines += [f"RUN {step}" for step in build_steps]
    lines += [
        "FROM gcr.io/distroless/static-debian12",
        "WORKDIR /app",
        f"COPY --from=build {_GO_BINARY} {_GO_BINARY}",
    ]
    # No shell to fall back on: honor a custom `start:` by exec-splitting it
    # (quoting works, shell operators like && or | do not), else run the
    # binary the default/custom build step produced at _GO_BINARY.
    cmd = shlex.split(manifest.start) if manifest.start else [_GO_BINARY]
    lines.append("CMD " + json.dumps(cmd))
    return "\n".join(lines) + "\n"


def render_dockerfile(manifest: Manifest, base_image: str) -> str:
    if manifest.runtime == "go":
        return _render_go_dockerfile(manifest)
    lines = [
        f"FROM {base_image}",
        "ENTRYPOINT []",        # drop the base image's koyra build entrypoint
        "WORKDIR /app",
        "COPY . /app",
    ]
    lines += [f"RUN {step}" for step in manifest.build]
    # persist dirs are NFS-mounted at runtime; create them so the mount has a
    # target and non-persisted runs still work.
    lines += [f"RUN mkdir -p /app/{d}" for d in manifest.persist]

    if manifest.runtime == "static":
        if manifest.static_dir:
            run = f'exec python3 /koyra_static.py --dir "/app/{manifest.static_dir}" --port {manifest.port}'
        else:
            run = _STATIC_DETECT % manifest.port
    else:
        run = f"exec {manifest.start}"

    if manifest.predeploy:                      # idempotent steps run every start
        run = " && ".join(manifest.predeploy) + " && " + run
    lines.append("CMD " + json.dumps(["sh", "-c", run]))
    return "\n".join(lines) + "\n"
