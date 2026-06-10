#!/usr/bin/env python3
"""koyracloud generic runtime entrypoint — the shared "buildpack".

Every app deployed by koyracloud runs THIS script as PID 1 inside the shared
``koyracloud-runtime`` image. No app code is baked into the image; instead the
app's git checkout, virtualenv and build caches live on an NFS volume mounted at
``/workspace``. On start the entrypoint:

  1. clones/pulls the repo at the target ref (offline-safe),
  2. reads ``.paas/app.yaml``,
  3. (re)runs build steps only when the dependency hash changed,
  4. runs predeploy steps every start (must be idempotent),
  5. execs the start command as PID 1.

The pure helpers (`compute_dep_hash`, `read_manifest`, `build_path`,
`needs_build`, `clone_url_with_token`) are import-safe and unit-tested.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

WORKSPACE = Path(os.environ.get("KOYRA_WORKSPACE", "/workspace"))
REPO_DIR = WORKSPACE / "repo"
VENV_DIR = WORKSPACE / "venv"
DEP_HASH_FILE = WORKSPACE / ".dep-hash"
MANIFEST_REL = ".paas/app.yaml"

# Files whose contents define the dependency hash. Missing files are skipped.
DEP_FILES = ("requirements.txt", "web/package-lock.json", "package-lock.json")


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested)
# --------------------------------------------------------------------------- #
def compute_dep_hash(repo_dir: Path, dep_files=DEP_FILES) -> str:
    """sha256 over the concatenated contents of the dependency files present.

    Deterministic and order-stable. A file's absence is recorded distinctly
    from an empty file so adding/removing a lockfile changes the hash.
    """
    h = hashlib.sha256()
    for rel in dep_files:
        p = repo_dir / rel
        h.update(rel.encode())
        if p.is_file():
            h.update(b"\x01")
            h.update(p.read_bytes())
        else:
            h.update(b"\x00")
    return h.hexdigest()


def read_manifest(path: Path) -> dict:
    """Parse and minimally validate ``.paas/app.yaml``."""
    if not path.is_file():
        raise FileNotFoundError(f"manifest not found: {path}")
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError("manifest must be a YAML mapping")
    for required in ("name", "start"):
        if not data.get(required):
            raise ValueError(f"manifest missing required field: {required}")
    return data


def build_path(venv_dir: Path, base_path: str | None) -> str:
    """Prepend the venv's bin dir to PATH so generic commands resolve to it."""
    base = base_path or os.environ.get("PATH", "")
    return f"{venv_dir / 'bin'}:{base}" if base else str(venv_dir / "bin")


def needs_build(current_hash: str, hash_file: Path, venv_dir: Path,
                uses_python: bool) -> bool:
    """Rebuild when the cache is cold or the dependency hash changed."""
    if uses_python and not (venv_dir / "bin").exists():
        return True
    if not hash_file.is_file():
        return True
    return hash_file.read_text().strip() != current_hash


_SAFE_REF = re.compile(r"^[A-Za-z0-9._/-]+$")


def validate_repo_ref(repo_url: str, ref: str) -> None:
    """Reject values that could smuggle git flags or unexpected transports."""
    if repo_url.startswith("-") or not (
            repo_url.startswith("https://") or repo_url.startswith("git@")):
        raise ValueError(f"unsafe repo_url: {repo_url!r}")
    if ref.startswith("-") or not _SAFE_REF.match(ref):
        raise ValueError(f"unsafe git ref: {ref!r}")


def auth_args(token: str | None) -> list[str]:
    """git -c args passing the token via an Authorization header rather than in
    the URL, keeping it out of argv / process listings."""
    if not token:
        return []
    cred = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return ["-c", f"http.extraHeader=Authorization: Basic {cred}"]


# --------------------------------------------------------------------------- #
# Side-effecting steps
# --------------------------------------------------------------------------- #
def log(phase: str, msg: str = "") -> None:
    sys.stdout.write(f"\n=== [koyra:{phase}] {msg}\n")
    sys.stdout.flush()


def run(cmd, cwd: Path, env: dict) -> None:
    """Run a shell command, streaming output; raise on non-zero exit."""
    log("run", cmd if isinstance(cmd, str) else " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd), env=env, shell=isinstance(cmd, str),
                   check=True)


def sync_repo(repo_url: str, ref: str, token: str, repo_dir: Path) -> None:
    """Clone if absent, else fetch+checkout. Offline-safe: a fetch failure on an
    existing checkout is a warning, not fatal — we run what's on disk."""
    validate_repo_ref(repo_url, ref)
    auth = auth_args(token)
    env = dict(os.environ)
    if not (repo_dir / ".git").is_dir():
        log("clone", f"{repo_url} @ {ref}")
        repo_dir.mkdir(parents=True, exist_ok=True)
        run(["git", *auth, "clone", "--no-single-branch", "--", repo_url, "."], repo_dir, env)
        run(["git", "checkout", ref, "--"], repo_dir, env)
        return
    log("pull", f"{repo_url} @ {ref}")
    try:
        run(["git", "remote", "set-url", "origin", repo_url], repo_dir, env)
        run(["git", *auth, "fetch", "--all", "--prune"], repo_dir, env)
        run(["git", "checkout", ref, "--"], repo_dir, env)
        # Fast-forward if ref is a branch; ignore failure (detached/tag).
        subprocess.run(["git", *auth, "pull", "--ff-only"], cwd=str(repo_dir),
                       env=env, check=False)
    except subprocess.CalledProcessError:
        log("pull", "WARNING: fetch/checkout failed; using on-disk checkout")


def main() -> None:
    repo_url = os.environ["KOYRA_REPO_URL"]
    ref = os.environ.get("KOYRA_REF") or os.environ.get("KOYRA_BRANCH", "main")
    token = os.environ.get("KOYRA_GIT_TOKEN", "")

    sync_repo(repo_url, ref, token, REPO_DIR)
    manifest = read_manifest(REPO_DIR / MANIFEST_REL)

    runtime = str(manifest.get("runtime", "python+node"))
    uses_python = "python" in runtime

    env = dict(os.environ)
    if uses_python:
        if not (VENV_DIR / "bin").exists():
            log("venv", f"creating {VENV_DIR}")
            run([sys.executable, "-m", "venv", str(VENV_DIR)], WORKSPACE, env)
        env["PATH"] = build_path(VENV_DIR, env.get("PATH"))
        env["VIRTUAL_ENV"] = str(VENV_DIR)

    dep_hash = compute_dep_hash(REPO_DIR)
    if needs_build(dep_hash, DEP_HASH_FILE, VENV_DIR, uses_python):
        log("build", f"dep-hash {dep_hash[:12]} — running build steps")
        for step in manifest.get("build", []):
            run(step, REPO_DIR, env)
        DEP_HASH_FILE.write_text(dep_hash)
    else:
        log("build", f"dep-hash {dep_hash[:12]} unchanged — skipping build")

    for d in manifest.get("persist", []):
        (REPO_DIR / d).mkdir(parents=True, exist_ok=True)

    # Build-only mode (used by the control plane's one-off build container):
    # sync + build + persist dirs, then exit. predeploy + start run in the
    # long-running service, so the build never races a healthcheck/restart.
    if os.environ.get("KOYRA_BUILD_ONLY") == "1":
        log("build-only", "build complete; predeploy + start run in the service")
        return

    for step in manifest.get("predeploy", []):
        run(step, REPO_DIR, env)

    start = manifest["start"]
    log("start", start)
    os.chdir(REPO_DIR)
    os.execve("/bin/sh", ["/bin/sh", "-c", start], env)


if __name__ == "__main__":
    main()
