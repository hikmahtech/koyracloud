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
    port: int = 8000
    build: list[str] = Field(default_factory=list)
    predeploy: list[str] = Field(default_factory=list)
    start: str = ""                   # required except for static sites
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
        if v not in {"python", "node", "python+node", "static"}:
            raise ValueError(f"runtime must be python|node|python+node|static, got {v!r}")
        return v

    @model_validator(mode="after")
    def _static_defaults(self):
        if self.runtime != "static" and not self.start:
            raise ValueError("start is required (except for runtime: static)")
        if self.runtime == "static" and not self.healthcheck:
            self.healthcheck = "/"   # the static server answers / with 200
        return self

    @field_validator("name")
    @classmethod
    def _name_valid(cls, v: str) -> str:
        if not v or not all(c.isalnum() or c in "-_" for c in v):
            raise ValueError("name must be non-empty alphanumeric/-/_")
        return v


def parse_manifest(text: str) -> Manifest:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("manifest must be a YAML mapping")
    return Manifest.model_validate(data)
