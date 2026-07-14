"""Pydantic request/response schemas for the REST API."""
from __future__ import annotations

import datetime as dt
import re
from typing import Literal

from pydantic import BaseModel, field_validator

_SAFE_REF = re.compile(r"^[A-Za-z0-9._/-]+$")
# Loose email shape — enough to reject garbage without pulling in email-validator.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# App name becomes a DNS label, a Traefik router/service name, and an NFS path
# segment — keep it strictly lowercase-alnum + hyphen, no dots/slashes/underscores.
_DNS_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$")


def _check_name(v: str) -> str:
    if not _DNS_LABEL.match(v):
        raise ValueError("name must be lowercase letters/digits/hyphens "
                         "(1-40 chars, no leading/trailing hyphen)")
    return v


def _check_repo_url(v: str) -> str:
    if v.startswith("-") or not (v.startswith("https://") or v.startswith("git@")):
        raise ValueError("repo_url must be an https:// or git@ URL")
    return v


def _check_ref(v: str) -> str:
    if v.startswith("-") or not _SAFE_REF.match(v):
        raise ValueError("ref/branch contains unsafe characters")
    return v


class AppCreate(BaseModel):
    name: str
    repo_url: str
    branch: str = "main"
    auto_deploy: bool = False

    _v_name = field_validator("name")(_check_name)
    _v_repo = field_validator("repo_url")(_check_repo_url)
    _v_branch = field_validator("branch")(_check_ref)


class DeployOut(BaseModel):
    id: int
    app_id: int
    status: str
    ref: str
    commit: str
    created_at: dt.datetime
    finished_at: dt.datetime | None

    model_config = {"from_attributes": True}


class AppOut(BaseModel):
    id: int
    name: str
    repo_url: str
    branch: str
    auto_deploy: bool
    webhook_seen_at: dt.datetime | None = None
    created_at: dt.datetime
    latest_status: str | None = None
    last_deployed_at: dt.datetime | None = None
    primary_host: str | None = None
    pinned: bool = False
    pinned_node: str | None = None  # recorded node once learned (null until then)

    model_config = {"from_attributes": True}


class EnvVarIn(BaseModel):
    key: str
    value: str


class SecretIn(BaseModel):
    key: str
    value: str


class DeployTrigger(BaseModel):
    ref: str | None = None


class RollbackRequest(BaseModel):
    deploy_id: int


class AppUpdate(BaseModel):
    branch: str | None = None
    auto_deploy: bool | None = None
    pinned: bool | None = None

    @field_validator("branch")
    @classmethod
    def _vb(cls, v):
        return _check_ref(v) if v is not None else v


class AllowedUserIn(BaseModel):
    login: str

    @field_validator("login")
    @classmethod
    def _vl(cls, v: str) -> str:
        v = v.strip().lstrip("@")
        if not v or not all(c.isalnum() or c == "-" for c in v):
            raise ValueError("invalid GitHub login")
        return v


class WaitlistIn(BaseModel):
    """Public managed-koyracloud waitlist signup. ``site_count`` is the ICP
    qualifier; Literal makes a bad bucket a 422 with no extra code."""
    email: str
    site_count: Literal["1-2", "3-9", "10+"]

    @field_validator("email")
    @classmethod
    def _ve(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL.match(v):
            raise ValueError("invalid email")
        return v


class DomainIn(BaseModel):
    host: str

    @field_validator("host")
    @classmethod
    def _vh(cls, v: str) -> str:
        v = v.strip().lower().rstrip(".")
        if not v or v.startswith("-") or " " in v or "/" in v or "." not in v:
            raise ValueError("host must be a valid domain name")
        if not all(c.isalnum() or c in ".-" for c in v):
            raise ValueError("host contains invalid characters")
        return v


class DnsRecord(BaseModel):
    """A CNAME the customer adds at their own registrar (traffic / DCV)."""
    type: str
    name: str
    value: str


class DomainOut(BaseModel):
    id: int
    host: str
    is_primary: bool
    dns_ok: bool | None = None  # resolves to the homelab IP (None = unknown)
    # Cloudflare-for-SaaS custom-hostname status (defaults when CF isn't managing it)
    verified: bool = False      # cert is active at the edge
    ssl_status: str | None = None
    records: list[DnsRecord] = []  # CNAMEs the customer must add at their registrar

    model_config = {"from_attributes": True}
