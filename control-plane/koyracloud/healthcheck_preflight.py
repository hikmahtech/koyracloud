"""Pre-flight (not log-based) check for a healthcheck that will never pass:
an own-Dockerfile app whose final stage looks like alpine with no python3
install. Unlike build_hints.py this never shows up in the build log — the
build succeeds, the container starts, and swarm kills it ~30-60s later when
the `python3 -c ...` healthcheck exec fails. See
docs/MIGRATING-FROM-VERCEL.md.
"""
from __future__ import annotations

import re

from koyracloud.manifest import Manifest

_FROM_RE = re.compile(r"^\s*FROM\s+(\S+)", re.IGNORECASE | re.MULTILINE)
# Matches an actual apk install of python3 in a real `RUN` instruction (any
# flags/other packages on the same line, e.g. `apk add --no-cache python3`,
# `apk add --update python3`, `apk add git python3 make`, or a `RUN` chain
# like `RUN set -e && apk add python3`). Anchored to the start of the line so
# a `# RUN apk add python3` comment or an `ENV FOO="apk add python3"` value
# — neither of which installs anything — can't be mistaken for a real
# install.
_APK_PYTHON3_RE = re.compile(
    r"^\s*run(?:\s+--[^\n]+)?\b.*?\bapk\s+add\b[^\n]*\bpython3\b",
    re.MULTILINE,
)
_LINE_CONTINUATION_RE = re.compile(r"\\\s*\n\s*")


def _final_stage_is_alpine_without_python3(dockerfile_text: str) -> bool:
    matches = list(_FROM_RE.finditer(dockerfile_text))
    if not matches:
        return False  # can't identify a stage; stay conservative, no false warning
    image = matches[-1].group(1).lower()
    if "alpine" not in image:
        return False
    final_stage = dockerfile_text[matches[-1].start():].lower()
    # `RUN apk add --no-cache \` / `    python3` (a line-continued install) is
    # a common Alpine pattern — collapse backslash continuations so the
    # single-line install regex below still matches it.
    final_stage = _LINE_CONTINUATION_RE.sub(" ", final_stage)
    return not _APK_PYTHON3_RE.search(final_stage)


def detect_healthcheck_hint(manifest: Manifest, dockerfile_text: str) -> str | None:
    """Warn when manifest.healthcheck will run against an own-Dockerfile final
    stage that looks like alpine without python3 — the exec koyracloud uses
    for healthchecks (see stack_render.py) needs python3 in the container."""
    if not manifest.healthcheck or not manifest.uses_dockerfile:
        return None
    if not _final_stage_is_alpine_without_python3(dockerfile_text):
        return None
    return ("healthcheck is set but the final image stage looks like alpine "
            "without python3 — koyracloud healthchecks run `python3 -c ...` "
            "inside the container, so swarm will start it, then kill it once "
            "the healthcheck fails. Drop `healthcheck:`, or install python3 "
            "in the final stage (see docs/MIGRATING-FROM-VERCEL.md).")
