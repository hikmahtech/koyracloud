"""Parsing and validation of a consumer repo's ``.paas/app.yaml``.

This is the control-plane view of the manifest — it must agree with what the
runtime entrypoint reads. The entrypoint cares about build/predeploy/start; the
control plane additionally needs port/subdomain/healthcheck/persist/env/secrets
to render the Docker stack, plus any background workers, cron jobs, and whether
the app wants the shared Redis bus.
"""
from __future__ import annotations

import re

import yaml
from croniter import croniter
from pydantic import BaseModel, Field, field_validator, model_validator

# A worker/cron name becomes a Swarm service-name suffix, so keep it a strict
# DNS label (same rule the API enforces on app names).
_PROC_NAME = re.compile(r"^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$")


def _valid_proc_name(v: str) -> str:
    if not _PROC_NAME.match(v):
        raise ValueError(
            "name must be lowercase letters/digits/hyphens (1-40 chars, "
            "no leading/trailing hyphen)")
    if v == "web":
        raise ValueError("'web' is reserved for the app's main process")
    return v


class Worker(BaseModel):
    """An always-on background process run from the app's image — no HTTP port,
    no Traefik router. One Swarm service per worker."""
    name: str
    start: str
    replicas: int = 1
    cpu: str = ""                     # falls back to the instance default
    memory: str = ""

    _v_name = field_validator("name")(_valid_proc_name)

    @field_validator("start")
    @classmethod
    def _start_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("worker start command must not be empty")
        return v

    @field_validator("replicas")
    @classmethod
    def _replicas_pos(cls, v: int) -> int:
        if v < 1:
            raise ValueError("worker replicas must be >= 1")
        return v


class CronJob(BaseModel):
    """A command run from the app's image on a schedule (5-field cron, UTC),
    launched to completion each tick by the control-plane scheduler."""
    name: str
    schedule: str
    command: str

    _v_name = field_validator("name")(_valid_proc_name)

    @field_validator("schedule")
    @classmethod
    def _schedule_valid(cls, v: str) -> str:
        if not croniter.is_valid(v):
            raise ValueError(f"invalid cron schedule: {v!r}")
        return v

    @field_validator("command")
    @classmethod
    def _command_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("cron command must not be empty")
        return v


class Manifest(BaseModel):
    name: str
    runtime: str = "python+node"
    subdomain: str = ""               # full host; if blank, control plane derives one
    # Path to the repo's own Dockerfile (relative to repo root). When set — or
    # runtime is "dockerfile" — koyracloud builds that Dockerfile as-is instead
    # of generating one, then runs the resulting image. build/start are ignored.
    dockerfile: str = ""
    root: str = ""                    # build-context subdir for monorepo apps (blank = repo root)
    port: int = 8000
    build: list[str] = Field(default_factory=list)
    predeploy: list[str] = Field(default_factory=list)
    start: str = ""                   # required except for static / dockerfile
    static_dir: str = ""              # static runtime: dir to serve (auto-detected if blank)
    persist: list[str] = Field(default_factory=list)
    cpu: str = ""                     # e.g. "0.5"; falls back to the instance default
    memory: str = ""                  # e.g. "256M"; falls back to the instance default
    healthcheck: str = ""             # path, e.g. /health
    env: dict[str, str] = Field(default_factory=dict)
    secrets: list[str] = Field(default_factory=list)
    # Background work, all run from the same image as the web process.
    redis: bool = False               # provision a shared-Redis ACL user + inject REDIS_URL
    workers: list[Worker] = Field(default_factory=list)
    cron: list[CronJob] = Field(default_factory=list)

    @field_validator("runtime")
    @classmethod
    def _runtime_valid(cls, v: str) -> str:
        if v not in {"python", "node", "python+node", "static", "dockerfile", "go"}:
            raise ValueError(
                f"runtime must be python|node|python+node|static|dockerfile|go, got {v!r}")
        return v

    @property
    def uses_dockerfile(self) -> bool:
        """True when a repo Dockerfile (explicit path or runtime: dockerfile)
        owns the build + run, so koyracloud builds it as-is."""
        return bool(self.dockerfile) or self.runtime == "dockerfile"

    @model_validator(mode="after")
    def _defaults(self):
        if not self.uses_dockerfile and self.runtime not in ("static", "go") and not self.start:
            raise ValueError("start is required (except for runtime: static / go / dockerfile)")
        if self.runtime == "static" and not self.healthcheck:
            self.healthcheck = "/"   # the static server answers / with 200
        if self.runtime == "go" and self.healthcheck:
            raise ValueError(
                "healthcheck is not supported for runtime: go — the probe execs "
                "python3 inside the container, and the distroless runner image has "
                "none; drop healthcheck (or bring your own Dockerfile with python3)")
        if self.runtime == "go" and self.predeploy:
            raise ValueError(
                "predeploy is not supported for runtime: go — the distroless "
                "runner image has no shell to chain commands; do startup work "
                "(e.g. migrations) from the Go binary itself")
        # Worker + cron names share one namespace (they become distinct service
        # names) and must be unique so status/logs/launch are unambiguous.
        names = [w.name for w in self.workers] + [c.name for c in self.cron]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate worker/cron name(s): {', '.join(sorted(dupes))}")
        return self

    @field_validator("name")
    @classmethod
    def _name_valid(cls, v: str) -> str:
        if not v or not all(c.isalnum() or c in "-_" for c in v):
            raise ValueError("name must be non-empty alphanumeric/-/_")
        return v

    @field_validator("root")
    @classmethod
    def _root_safe(cls, v: str) -> str:
        # Must stay inside the cloned repo: relative, no parent escapes.
        if v.startswith("/") or ".." in v.split("/"):
            raise ValueError("root must be a relative subdirectory within the repo")
        return v.strip("/")


def parse_manifest(text: str) -> Manifest:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("manifest must be a YAML mapping")
    return Manifest.model_validate(data)
