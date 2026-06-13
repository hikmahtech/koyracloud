"""Cloudflare for SaaS custom hostnames. Registers a user-supplied domain as a
custom hostname so the edge mints + auto-renews its TLS cert, and reports the
CNAME records the customer must add at their own registrar (Vercel-style).

Every network call is a graceful no-op (returns None / [] / False) until both a
token and a zone id are configured, so local/dev and existing deploys keep
working unchanged. Mirrors notifier.py: an optional injected httpx.Client makes
the client testable without network access."""
from __future__ import annotations

import httpx

from koyracloud.config import Settings

API_BASE = "https://api.cloudflare.com/client/v4"


def customer_records(host: str, origin: str, dcv_uuid: str) -> list[dict]:
    """The CNAMEs a customer adds once at their own registrar: one routing
    traffic to the fallback origin, one delegating ACME/DCV so the edge can
    issue + renew the cert. Pure; safe to call without network access. The DCV
    record is omitted when the zone's delegation uuid isn't known yet."""
    records = [{"type": "CNAME", "name": host, "value": origin}]
    if dcv_uuid:
        records.append({
            "type": "CNAME",
            "name": f"_acme-challenge.{host}",
            "value": f"{host}.{dcv_uuid}.dcv.cloudflare.com",
        })
    return records


def _hostname_view(result: dict) -> dict:
    """Flatten a custom_hostnames API result to the fields we persist/return."""
    return {
        "id": result.get("id", ""),
        "status": result.get("status", ""),
        "ssl_status": (result.get("ssl") or {}).get("status", ""),
        "ownership": result.get("ownership_verification") or {},
    }


class Cloudflare:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self._client = client
        self._dcv_uuid: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.settings.cloudflare_api_token and self.settings.cloudflare_zone_id)

    def _request(self, method: str, path: str, **kw) -> dict | None:
        """Authenticated API call. Returns the parsed ``result`` on success,
        None on any failure (network, non-2xx, or ``success: false``) — a
        Cloudflare hiccup must never break adding/removing a domain."""
        owns = self._client is None
        client = self._client or httpx.Client(timeout=15)
        try:
            r = client.request(
                method, f"{API_BASE}{path}",
                headers={"Authorization": f"Bearer {self.settings.cloudflare_api_token}"},
                **kw)
            data = r.json()
            if r.status_code >= 300 or not data.get("success", False):
                return None
            return data.get("result") or {}
        except Exception:  # noqa: BLE001 — failures are non-fatal by design
            return None
        finally:
            if owns:
                client.close()

    def find_custom_hostname(self, host: str) -> dict | None:
        """Look up an existing custom hostname by exact name. Returns its view or
        None when not present / unconfigured / on error."""
        if not self.configured:
            return None
        result = self._request(
            "GET", f"/zones/{self.settings.cloudflare_zone_id}/custom_hostnames",
            params={"hostname": host})
        items = result if isinstance(result, list) else []
        return _hostname_view(items[0]) if items else None

    def create_custom_hostname(self, host: str) -> dict | None:
        """Register ``host`` for SaaS TLS, idempotently. If CF already has the
        hostname (e.g. created in a prior session or a re-add), adopt and return
        its existing record instead of failing. Returns {id, status, ssl_status,
        ownership} or None when unconfigured / on error."""
        if not self.configured:
            return None
        existing = self.find_custom_hostname(host)
        if existing:
            return existing
        # HTTP validation: once the proxied traffic CNAME (host → SaaS origin) is
        # in place, Cloudflare auto-validates ownership + issues the cert at the
        # edge with nothing for the customer to add. The DCV-delegation CNAME we
        # also surface lets CF renew hands-off. (The one live custom hostname,
        # lm.eyelookoptics.in, validated this way — ssl.method=http.)
        body = {"hostname": host, "ssl": {
            "method": "http", "type": "dv",
            "settings": {"min_tls_version": "1.2"},
            "bundle_method": "ubiquitous", "wildcard": False}}
        result = self._request(
            "POST", f"/zones/{self.settings.cloudflare_zone_id}/custom_hostnames", json=body)
        return _hostname_view(result) if result is not None else None

    def get_custom_hostname(self, hostname_id: str) -> dict | None:
        if not self.configured or not hostname_id:
            return None
        result = self._request(
            "GET", f"/zones/{self.settings.cloudflare_zone_id}/custom_hostnames/{hostname_id}")
        return _hostname_view(result) if result is not None else None

    def delete_custom_hostname(self, hostname_id: str) -> bool:
        if not self.configured or not hostname_id:
            return False
        result = self._request(
            "DELETE", f"/zones/{self.settings.cloudflare_zone_id}/custom_hostnames/{hostname_id}")
        return result is not None

    def dcv_uuid(self) -> str:
        """The zone's DCV delegation uuid (stable; cached per instance). Returns
        '' when unconfigured or on error so a transient failure can retry."""
        if self._dcv_uuid:
            return self._dcv_uuid
        if not self.configured:
            return ""
        result = self._request(
            "GET", f"/zones/{self.settings.cloudflare_zone_id}/dcv_delegation/uuid")
        uuid = (result or {}).get("uuid", "")
        if uuid:
            self._dcv_uuid = uuid
        return uuid

    def records_for(self, host: str) -> list[dict]:
        """The customer-facing CNAMEs for ``host`` (traffic + DCV delegation)."""
        return customer_records(host, self.settings.cloudflare_saas_origin, self.dcv_uuid())
