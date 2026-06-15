"""Parsing and validation of a consumer repo's ``.paas/app.yaml``.

This is the control-plane view of the manifest — it must agree with what the
runtime entrypoint reads. The entrypoint cares about build/predeploy/start; the
control plane additionally needs port/subdomain/healthcheck/persist/env/secrets
to render the Docker stack.
"""
from __future__ import annotations

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


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

    @field_validator("runtime")
    @classmethod
    def _runtime_valid(cls, v: str) -> str:
        if v not in {"python", "node", "python+node", "static", "dockerfile"}:
            raise ValueError(
                f"runtime must be python|node|python+node|static|dockerfile, got {v!r}")
        return v

    @property
    def uses_dockerfile(self) -> bool:
        """True when a repo Dockerfile (explicit path or runtime: dockerfile)
        owns the build + run, so koyracloud builds it as-is."""
        return bool(self.dockerfile) or self.runtime == "dockerfile"

    @model_validator(mode="after")
    def _defaults(self):
        if not self.uses_dockerfile and self.runtime != "static" and not self.start:
            raise ValueError("start is required (except for runtime: static / dockerfile)")
        if self.runtime == "static" and not self.healthcheck:
            self.healthcheck = "/"   # the static server answers / with 200
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
