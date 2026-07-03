"""Heuristics that turn a raw build/push log into a one-line "Hint: …" for the
most common failure signatures. Pure + unit-tested; see
docs/MIGRATING-FROM-VERCEL.md for the failure modes these are drawn from.
"""
from __future__ import annotations

from typing import Callable


def _pnpm_version_mismatch(text: str) -> str | None:
    if "ERR_UNKNOWN_BUILTIN_MODULE" in text:
        return ("pnpm/node version mismatch — corepack pulled a pnpm "
                 "incompatible with the pinned node base. Pin a known-good "
                 "version, e.g. `corepack prepare pnpm@9.15.9 --activate` "
                 "for node:20 (see docs/MIGRATING-FROM-VERCEL.md).")
    if "packages field missing or empty" in text:
        return ("pnpm-workspace.yaml uses pnpm-10-style fields (e.g. "
                 "ignoredBuiltDependencies) with no `packages:` — pnpm 9 "
                 "rejects it. Use pnpm 10: `RUN npm install -g pnpm@10` "
                 "(see docs/MIGRATING-FROM-VERCEL.md).")
    return None


def _missing_public_build_arg(text: str) -> str | None:
    if "Failed to collect page data" in text:
        return ("build failed collecting page data — likely a "
                 "NEXT_PUBLIC_*/VITE_* var read at import time that isn't "
                 "set. Set it as app env (not a secret) so it's passed as "
                 "a --build-arg (see docs/MIGRATING-FROM-VERCEL.md).")
    return None


# Ordered so detect_log_hints() returns hints in a stable order. Adding a
# heuristic is a one-line append here, not a change to detect_log_hints
# itself or its callers.
_DETECTORS: tuple[Callable[[str], str | None], ...] = (
    _pnpm_version_mismatch,
    _missing_public_build_arg,
)


def detect_log_hints(lines: list[str]) -> list[str]:
    """Scan accumulated build/push output for known failure signatures;
    return zero or more one-line hints, in detector order."""
    text = "\n".join(lines)
    hints = []
    for detector in _DETECTORS:
        hint = detector(text)
        if hint:
            hints.append(hint)
    return hints
