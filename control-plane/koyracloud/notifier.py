"""Email notifications via Resend. Inert (no-op) until RESEND_API_KEY is set, so
it's safe to wire everywhere and switch on later."""
from __future__ import annotations

import httpx

from koyracloud.config import Settings

RESEND_ENDPOINT = "https://api.resend.com/emails"


def _wrap(title: str, body_html: str) -> str:
    return (
        '<div style="font-family:system-ui,sans-serif;background:#0a0b0d;color:#e9ecf1;'
        'padding:28px;border-radius:12px;max-width:520px">'
        '<div style="font-weight:700;font-size:18px;color:#c8f04e">koyracloud</div>'
        f'<h2 style="font-size:20px;margin:14px 0 8px">{title}</h2>'
        f'<div style="color:#8a909c;line-height:1.6">{body_html}</div>'
        '</div>'
    )


# event -> (subject template, title, body) builders. Pure, unit-tested.
def render_event(event: str, app_name: str, detail: str = "", host: str = "") -> tuple[str, str]:
    link = f'<a href="https://{host}" style="color:#c8f04e">{host}</a>' if host else app_name
    table = {
        "deploy_live": (f"✅ {app_name} deployed",
                        _wrap("Deploy succeeded", f"{app_name} is live at {link}.")),
        "deploy_failed": (f"❌ {app_name} deploy failed",
                          _wrap("Deploy failed", f"{app_name} failed to deploy.<br><br>"
                                f"<code>{detail[:300]}</code>")),
        "deploy_rolled_back": (f"↩️ {app_name} rolled back",
                               _wrap("Rolled back", f"{app_name} was rolled back to a previous commit.")),
        "down": (f"🔴 {app_name} is down",
                 _wrap("Down alert", f"{app_name} ({link}) stopped responding.")),
        "recovered": (f"🟢 {app_name} recovered",
                      _wrap("Recovered", f"{app_name} ({link}) is responding again.")),
    }
    return table.get(event, (f"{app_name}: {event}", _wrap(event, app_name)))


def send_email(settings: Settings, to: str, subject: str, html: str,
               client: httpx.Client | None = None) -> bool:
    """Send via Resend. Returns False (no-op) if not configured or no recipient."""
    if not settings.resend_api_key or not to:
        return False
    owns = client is None
    client = client or httpx.Client(timeout=15)
    try:
        r = client.post(RESEND_ENDPOINT,
                        headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                        json={"from": settings.email_from, "to": [to],
                              "subject": subject, "html": html})
        return r.status_code < 300
    except Exception:  # noqa: BLE001 — never let a notification failure break a deploy
        return False
    finally:
        if owns:
            client.close()


def notify(settings: Settings, to: str, event: str, app_name: str,
           detail: str = "", host: str = "", client: httpx.Client | None = None) -> bool:
    subject, html = render_event(event, app_name, detail, host)
    return send_email(settings, to, subject, html, client=client)
