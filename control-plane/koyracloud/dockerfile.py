"""Render a per-app Dockerfile from its manifest. Pure + unit-tested.

The control plane builds this image locally (off NFS), pushes it to the internal
registry, and deploys the service from it — so the running container serves the
app from image layers, not an NFS-mounted workspace. NFS is used only for the
manifest's ``persist`` data dirs, mounted at runtime.
"""
from __future__ import annotations

import json

from koyracloud.manifest import Manifest

# Static sites are served by koyra_static.py (baked into the runtime base image),
# auto-detecting the build output dir the same way the old entrypoint did.
_STATIC_DETECT = (
    "d=; for c in dist build public out _site; do "
    "[ -d \"/app/$c\" ] && d=$c && break; done; "
    'exec python3 /koyra_static.py --dir "/app/${d:-.}" --port %d'
)


def render_dockerfile(manifest: Manifest, base_image: str) -> str:
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
