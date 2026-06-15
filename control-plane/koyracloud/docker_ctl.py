"""Docker Swarm control. The real implementation shells out to the docker CLI
(using the mounted socket in production). A Protocol lets tests inject a fake.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from typing import Iterator, Protocol

import yaml


class DockerControl(Protocol):
    def image_build(self, tag: str, context_dir: str,
                    build_args: dict | None = None,
                    dockerfile: str | None = None) -> Iterator[str]:
        """`docker build` a per-app image from a local context; yields output.
        Raises on non-zero exit."""

    def image_tag(self, src: str, dst: str) -> None:
        """`docker tag` — add a second tag (e.g. :latest) to a built image."""

    def image_push(self, tag: str) -> Iterator[str]:
        """`docker push` an image to the registry; yields output."""

    def deploy(self, stack: str, stack_dict: dict) -> Iterator[str]:
        """Deploy/update a stack; yields output lines. Raises on failure."""

    def remove(self, stack: str) -> Iterator[str]:
        """Remove a stack; yields output lines."""

    def service_logs(self, service: str, tail: int = 200) -> str:
        """Recent runtime logs of a running service."""

    def service_status(self, service: str) -> dict:
        """Live swarm status: running/desired replicas + per-task state."""

    def services_overview(self) -> dict:
        """One-shot {service_name: {running, desired}} for all services."""

    def run_job(self, name: str, image: str, command: str,
                env: dict | None = None, networks: list[str] | None = None) -> None:
        """Launch a Swarm run-to-completion job (``service create --mode
        replicated-job``) from an image; returns once created (poll with
        ``job_wait``). Raises on a create failure."""

    def job_wait(self, name: str, timeout: int = 600) -> int:
        """Block until the job's task reaches a terminal state; return 0 on
        Complete, non-zero otherwise. Raises ``TimeoutError`` past ``timeout``."""

    def remove_service(self, name: str) -> None:
        """``service rm`` — reap a finished job (or any service)."""


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

    def image_build(self, tag: str, context_dir: str,
                    build_args: dict | None = None,
                    dockerfile: str | None = None) -> Iterator[str]:
        args = ["build", "-t", tag]
        if dockerfile:
            args += ["-f", dockerfile]
        for k, v in (build_args or {}).items():
            args += ["--build-arg", f"{k}={v}"]
        args.append(context_dir)
        yield f"building image {tag}"
        yield from self._stream(args)

    def image_tag(self, src: str, dst: str) -> None:
        subprocess.run([*self._base, "tag", src, dst], check=True)

    def image_push(self, tag: str) -> Iterator[str]:
        yield f"pushing {tag}"
        yield from self._stream(["push", tag])

    def deploy(self, stack: str, stack_dict: dict) -> Iterator[str]:
        # `docker stack deploy` interpolates ${...}/$VAR in the compose file, so a
        # literal $ in any env value must be escaped to $$ or the deploy errors
        # ("invalid interpolation format"). Env/secret values are the only
        # user-controlled free text in the rendered stack; escape them in place.
        for svc in stack_dict.get("services", {}).values():
            env = svc.get("environment")
            if isinstance(env, dict):
                svc["environment"] = {
                    k: (v.replace("$", "$$") if isinstance(v, str) else v)
                    for k, v in env.items()
                }
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

    def service_logs(self, service: str, tail: int = 200) -> str:
        r = subprocess.run(
            [*self._base, "service", "logs", "--no-task-ids", "--timestamps",
             "--tail", str(tail), service],
            capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return (r.stderr or "").strip() or "(no logs yet — service not running)"
        return (r.stdout or "") + (r.stderr or "")

    def service_status(self, service: str) -> dict:
        desired = subprocess.run(
            [*self._base, "service", "inspect", service,
             "--format", "{{.Spec.Mode.Replicated.Replicas}}"],
            capture_output=True, text=True, timeout=15)
        if desired.returncode != 0:
            return {"exists": False, "running": 0, "desired": 0, "tasks": []}
        try:
            desired_n = int((desired.stdout or "0").strip() or 0)
        except ValueError:
            desired_n = 0
        ps = subprocess.run(
            [*self._base, "service", "ps", service, "--no-trunc",
             "--format", "{{.CurrentState}}||{{.DesiredState}}||{{.Error}}||{{.Node}}"],
            capture_output=True, text=True, timeout=15)
        tasks, running = [], 0
        for line in ps.stdout.splitlines():
            parts = (line.split("||") + ["", "", "", ""])[:4]
            cur, des, err, node = parts
            if des == "Running":  # current desired-state tasks only (skip history)
                tasks.append({"state": cur, "desired": des, "error": err, "node": node})
                if cur.startswith("Running"):
                    running += 1
        return {"exists": True, "running": running, "desired": desired_n,
                "tasks": tasks[:6]}

    def services_overview(self) -> dict:
        r = subprocess.run(
            [*self._base, "service", "ls", "--format", "{{.Name}}\t{{.Replicas}}"],
            capture_output=True, text=True, timeout=15)
        out: dict = {}
        for line in r.stdout.splitlines():
            if "\t" not in line:
                continue
            name, rep = line.split("\t", 1)
            token = rep.strip().split(" ")[0]  # "1/1" (ignore "(max N per node)")
            try:
                run_s, des_s = token.split("/")
                out[name] = {"running": int(run_s), "desired": int(des_s)}
            except ValueError:
                continue
        return out

    def run_job(self, name: str, image: str, command: str,
                env: dict | None = None, networks: list[str] | None = None) -> None:
        args = ["service", "create", "--mode", "replicated-job",
                "--restart-condition", "none", "--with-registry-auth",
                "--detach", "--name", name]
        if self._resolve_image_never:
            args.append("--resolve-image=never")
        for k, v in (env or {}).items():
            args += ["--env", f"{k}={v}"]
        for net in (networks or []):
            args += ["--network", net]
        # command runs as `sh -c "<command>"` inside the image; passed as argv
        # (no host shell), so the only shell is the container's.
        args += [image, "sh", "-c", command]
        r = subprocess.run([*self._base, *args], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout or "").strip()
                               or f"`docker service create {name}` failed")

    def job_wait(self, name: str, timeout: int = 600) -> int:
        # A replicated-job task ends in "Complete" (exit 0) or a failure state.
        # `service ps` lists the task; the newest is first.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            r = subprocess.run(
                [*self._base, "service", "ps", name, "--no-trunc",
                 "--format", "{{.CurrentState}}"],
                capture_output=True, text=True, timeout=15)
            states = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
            if states:
                cur = states[0]
                if cur.startswith("Complete"):
                    return 0
                if cur.startswith(("Failed", "Rejected", "Shutdown", "Orphaned")):
                    return 1
            time.sleep(2.0)
        raise TimeoutError(f"cron job {name} did not finish within {timeout}s")

    def remove_service(self, name: str) -> None:
        subprocess.run([*self._base, "service", "rm", name],
                       capture_output=True, text=True, timeout=30)
