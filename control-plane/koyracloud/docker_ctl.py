"""Docker Swarm control. The real implementation shells out to the docker CLI
(using the mounted socket in production). A Protocol lets tests inject a fake.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Iterator, Protocol

import yaml


class DockerControl(Protocol):
    def build(self, image: str, env: dict, volume: str) -> Iterator[str]:
        """Run a one-off build container (docker run --rm); yields output lines.
        Raises on non-zero exit."""

    def deploy(self, stack: str, stack_dict: dict) -> Iterator[str]:
        """Deploy/update a stack; yields output lines. Raises on failure."""

    def remove(self, stack: str) -> Iterator[str]:
        """Remove a stack; yields output lines."""


class CLIDockerControl:
    def __init__(self, docker_bin: str = "docker", context: str | None = None,
                 resolve_image_never: bool = False):
        ctx = ["--context", context] if context else []
        self._base = [docker_bin, *ctx]
        self._resolve_image_never = resolve_image_never

    def _stream(self, args: list[str]) -> Iterator[str]:
        proc = subprocess.Popen(
            [*self._base, *args],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            yield line.rstrip("\n")
        if proc.wait() != 0:
            raise RuntimeError(f"`docker {' '.join(args)}` exited {proc.returncode}")

    def build(self, image: str, env: dict, volume: str) -> Iterator[str]:
        args = ["run", "--rm"]
        for k, v in {**env, "KOYRA_BUILD_ONLY": "1"}.items():
            args += ["-e", f"{k}={v}"]
        args += ["-v", volume, image]
        yield "running one-off build container"
        yield from self._stream(args)

    def deploy(self, stack: str, stack_dict: dict) -> Iterator[str]:
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
            yaml.safe_dump(stack_dict, f, sort_keys=False)
            path = f.name
        try:
            yield f"deploying stack {stack}"
            args = ["stack", "deploy", "-c", path, "--with-registry-auth", "--prune"]
            if self._resolve_image_never:
                args.append("--resolve-image=never")
            yield from self._stream([*args, stack])
        finally:
            os.unlink(path)

    def remove(self, stack: str) -> Iterator[str]:
        yield from self._stream(["stack", "rm", stack])
