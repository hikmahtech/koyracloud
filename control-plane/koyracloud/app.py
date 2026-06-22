"""FastAPI application factory for the koyracloud control plane."""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import secrets as _secrets
import socket
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

from koyracloud import (analytics, auth, metrics as kmetrics, monitor, notifier,
                        scheduler, webhooks)
from koyracloud.ratelimit import RateLimiter
from koyracloud.cloudflare import Cloudflare
from koyracloud.config import Settings, get_settings
from koyracloud.crypto import CryptoBox
from koyracloud.db import Database
from koyracloud.deployer import Deployer
from koyracloud.docker_ctl import CLIDockerControl, DockerControl
from koyracloud.models import (AllowedUser, App, AppAnalytics, AppNotify,
                                AppRedis, CronJob, CronRun, Deploy, Domain,
                                DomainCert, EnvVar, Hit, Secret, User, Waitlist)
from koyracloud.schemas import (AllowedUserIn, AppCreate, AppOut, AppUpdate,
                                DeployOut, DeployTrigger, DnsRecord, DomainIn,
                                DomainOut, EnvVarIn, RollbackRequest, SecretIn,
                                WaitlistIn)
from koyracloud.stack_render import auto_subdomain, worker_service_name

import re as _re

WEB_DIST = Path(os.environ.get(
    "KOYRA_WEB_DIST", str(Path(__file__).resolve().parents[2] / "web" / "dist")))
TERMINAL = {"live", "failed", "rolled_back", "superseded"}
_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _ensure_sqlite_dir(db_url: str) -> None:
    prefix = "sqlite:///"
    if db_url.startswith(prefix):
        path = Path(db_url[len(prefix):])
        if path.parent and not path.is_absolute():
            path.parent.mkdir(parents=True, exist_ok=True)


def create_app(
    *,
    settings: Settings | None = None,
    db: Database | None = None,
    docker: DockerControl | None = None,
    deployer: Deployer | None = None,
    cloudflare: Cloudflare | None = None,
    run_async: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    _ensure_sqlite_dir(settings.db_url)
    db = db or Database(settings.db_url)
    db.create_all()
    crypto = CryptoBox(settings.secret_key)
    docker = docker or CLIDockerControl(resolve_image_never=settings.resolve_image_never)
    deployer = deployer or Deployer(settings=settings, docker=docker, crypto=crypto)
    cloudflare = cloudflare or Cloudflare(settings)

    # Disable FastAPI's built-in Swagger/OpenAPI routes so the SPA owns /docs.
    app = FastAPI(title="koyracloud", docs_url=None, redoc_url=None, openapi_url=None)

    def schedule(deploy_id: int) -> None:
        if run_async:
            threading.Thread(target=deployer.run_deploy, args=(db, deploy_id),
                             daemon=True).start()
        else:
            deployer.run_deploy(db, deploy_id)

    def launch_cron(cron_job_id: int) -> None:
        args = (db, docker, settings, crypto, cron_job_id)
        if run_async:
            threading.Thread(target=scheduler.launch, args=args, daemon=True).start()
        else:
            scheduler.launch(*args)

    def notify_event(app_id: int, event: str, detail: str = "") -> None:
        """Resolve recipient + app info and send an email (fire-and-forget)."""
        with db.session() as s:
            obj = s.get(App, app_id)
            if obj is None:
                return
            n = obj.notify
            to = (n.notify_email if n and n.notify_email else "") or settings.default_notify_email
            name = obj.name
            primary = next((d for d in obj.domains if d.is_primary), None) \
                or (obj.domains[0] if obj.domains else None)
            host = primary.host if primary else ""
        if not to:
            return
        threading.Thread(target=notifier.notify,
                         args=(settings, to, event, name, detail, host), daemon=True).start()

    if deployer.on_event is None:
        deployer.on_event = lambda aid, ev, detail, host: notify_event(aid, ev, detail)

    def _redeploy_if_live(s, obj: App) -> int | None:
        """Queue a redeploy when routing changes so Traefik re-renders the
        Host(...) rule. Only when the app already has a live service — a
        never-deployed app picks the change up on its first real deploy.

        Returns the new deploy id (caller schedules it after commit) or None.
        """
        if not any(d.status == "live" for d in obj.deploys):
            return None
        dep = Deploy(app_id=obj.id, ref=obj.branch, status="pending")
        s.add(dep)
        s.flush()
        return dep.id

    # ----- auth -----------------------------------------------------------
    def is_admin(login: str) -> bool:
        if settings.dev_login and login == settings.dev_login:
            return True
        return auth.is_allowed(login, settings.allowed_logins)

    def is_member(login: str) -> bool:
        with db.session() as s:
            return s.query(AllowedUser).filter_by(login=login.lower()).first() is not None

    def access_allowed(login: str) -> bool:
        return is_admin(login) or is_member(login)

    def current_login(request: Request) -> str:
        if settings.dev_login:
            return settings.dev_login
        token = request.cookies.get(auth.SESSION_COOKIE)
        login = auth.read_session(token, settings.session_secret) if token else None
        if not login:
            raise HTTPException(status_code=401, detail="not authenticated")
        if not access_allowed(login):
            raise HTTPException(status_code=403, detail="not allowed")
        return login

    def current_admin(login: str = Depends(current_login)) -> str:
        if not is_admin(login):
            raise HTTPException(status_code=403, detail="admin only")
        return login

    Auth = Depends(current_login)
    AdminAuth = Depends(current_admin)

    def get_app_or_404(app_id: int, s, login: str) -> App:
        obj = s.get(App, app_id)
        # 404 (not 403) when not owned, to avoid leaking app existence.
        if obj is None or (obj.owner_login != login and not is_admin(login)):
            raise HTTPException(status_code=404, detail="app not found")
        return obj

    def owned_deploy_or_404(deploy_id: int, s, login: str) -> Deploy:
        d = s.get(Deploy, deploy_id)
        if d is None:
            raise HTTPException(status_code=404, detail="deploy not found")
        app = s.get(App, d.app_id)
        if app is None or (app.owner_login != login and not is_admin(login)):
            raise HTTPException(status_code=404, detail="deploy not found")
        return d

    _collect_rl = RateLimiter(limit=600, window=60)   # per IP/min for /_k/e
    _webhook_rl = RateLimiter(limit=60, window=60)     # per IP/min for the webhook
    _waitlist_rl = RateLimiter(limit=10, window=60)    # per IP/min for /api/waitlist

    def _client_ip(request: Request) -> str:
        fwd = request.headers.get("x-forwarded-for", "")
        return (fwd or (request.client.host if request.client else "")).split(",")[0].strip() or "?"

    def get_or_create_analytics(s, app_id: int) -> AppAnalytics:
        a = s.get(AppAnalytics, app_id)
        if a is None:
            a = AppAnalytics(app_id=app_id, token=analytics.new_token(), enabled=True)
            s.add(a)
            s.commit()
        return a

    # ----- health / auth routes ------------------------------------------
    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    # Prometheus scrape target (unauthenticated; reached in-cluster over the
    # `monitoring` overlay). Exposes only platform-unique signal — per-app
    # uptime, app/deploy counts, Redis reachability.
    def _redis_ping() -> bool:
        try:
            import redis
            return bool(redis.Redis(
                host=settings.redis_host, port=settings.redis_port,
                username="default", password=settings.redis_admin_password,
                socket_timeout=3, decode_responses=True).ping())
        except Exception:
            return False

    @app.get("/metrics")
    def metrics_endpoint():
        ping = _redis_ping if settings.redis_admin_password else None
        return Response(kmetrics.render(db, redis_ping=ping),
                        media_type="text/plain; version=0.0.4")

    @app.get("/api/config")
    def public_config():
        # Non-sensitive instance config for the UI (e.g. the DNS hint).
        return {"apps_domain": settings.apps_domain, "public_ip": settings.public_ip}

    @app.get("/_k/a.js")
    def analytics_beacon():
        return Response(analytics.BEACON_JS, media_type="application/javascript",
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.post("/_k/e")
    async def analytics_collect(request: Request):
        cors = {"Access-Control-Allow-Origin": "*"}
        ip = _client_ip(request)
        cl = request.headers.get("content-length")
        if (cl and cl.isdigit() and int(cl) > 4096) or not _collect_rl.allow(ip):
            return Response(status_code=204, headers=cors)  # drop oversized/abusive silently
        try:
            payload = json.loads(await request.body())
        except ValueError:
            return Response(status_code=204, headers=cors)
        site = (payload.get("site") or "")[:32]
        with db.session() as s:
            rec = s.query(AppAnalytics).filter_by(token=site, enabled=True).first()
            if rec:
                ua = request.headers.get("user-agent", "")
                s.add(Hit(
                    app_id=rec.app_id,
                    path=(payload.get("path") or "/")[:512],
                    referrer=(payload.get("ref") or "")[:512],
                    visitor=analytics.visitor_hash(settings.session_secret, site, ip, ua),
                ))
                s.commit()
        return Response(status_code=204, headers=cors)

    @app.post("/api/webhooks/github")
    async def github_webhook(request: Request):
        # Unauthenticated but HMAC-verified: GitHub push → auto-deploy matching apps.
        if not _webhook_rl.allow(_client_ip(request)):
            raise HTTPException(status_code=429, detail="rate limited")
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > 1_000_000:
            raise HTTPException(status_code=413, detail="payload too large")
        body = await request.body()
        if not webhooks.verify_signature(settings.webhook_secret, body,
                                         request.headers.get("X-Hub-Signature-256")):
            raise HTTPException(status_code=401, detail="invalid signature")
        event = request.headers.get("X-GitHub-Event", "")
        if event == "ping":
            return {"ok": True}
        try:
            payload = json.loads(body)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid payload")
        # push → deploy now (no-CI repos); workflow_run(success) → deploy after
        # CI passes. The repo's webhook sends whichever event suits it.
        target = webhooks.deploy_target(event, payload)
        if target is None:
            return {"ignored": event}
        full, branch, sha = target
        triggered = []
        with db.session() as s:
            for a in s.query(App).filter_by(auto_deploy=True).all():
                if webhooks.repo_slug(a.repo_url) != full or a.branch != branch:
                    continue
                # Dedup: skip a commit already deployed/in-flight (e.g. if a repo
                # ends up sending both push and workflow_run for the same sha).
                latest = (s.query(Deploy).filter_by(app_id=a.id)
                          .order_by(Deploy.id.desc()).first())
                if latest and sha and latest.commit == sha and latest.status != "failed":
                    continue
                d = Deploy(app_id=a.id, ref=a.branch, status="pending")
                s.add(d)
                s.commit()
                triggered.append((d.id, a.name))
        for did, _ in triggered:
            schedule(did)
        return {"triggered": [n for _, n in triggered]}

    @app.get("/api/auth/login")
    def login():
        if not settings.github_client_id:
            raise HTTPException(status_code=500, detail="GitHub OAuth not configured")
        state = _secrets.token_urlsafe(16)
        url = auth.authorize_url(settings.github_client_id,
                                 f"{settings.base_url}/api/auth/callback", state)
        resp = RedirectResponse(url)
        resp.set_cookie(auth.OAUTH_STATE_COOKIE, state, httponly=True,
                        samesite="lax", max_age=600)
        return resp

    @app.get("/api/auth/callback")
    def callback(request: Request, code: str, state: str = ""):
        # CSRF: the state echoed back must match the one we set at /login.
        cookie_state = request.cookies.get(auth.OAUTH_STATE_COOKIE)
        if not cookie_state or not state or not _secrets.compare_digest(state, cookie_state):
            raise HTTPException(status_code=400, detail="invalid oauth state")
        login = auth.exchange_code(code, settings.github_client_id,
                                   settings.github_client_secret)
        if not access_allowed(login):
            raise HTTPException(status_code=403, detail=f"{login} is not allowed")
        with db.session() as s:
            if not s.query(User).filter_by(github_login=login).first():
                s.add(User(github_login=login))
                s.commit()
        resp = RedirectResponse("/")
        resp.set_cookie(auth.SESSION_COOKIE,
                        auth.make_session(login, settings.session_secret),
                        httponly=True, samesite="lax", max_age=auth.SESSION_MAX_AGE)
        resp.delete_cookie(auth.OAUTH_STATE_COOKIE)
        return resp

    @app.post("/api/auth/logout")
    def logout():
        resp = Response(status_code=204)
        resp.delete_cookie(auth.SESSION_COOKIE)
        return resp

    @app.get("/api/me")
    def me(login: str = Auth):
        return {"login": login, "is_admin": is_admin(login)}

    @app.post("/api/test-email")
    def test_email(body: dict, login: str = AdminAuth):
        to = (body.get("to") or "").strip()
        if not to:
            raise HTTPException(status_code=400, detail="to is required")
        if not settings.resend_api_key:
            return {"sent": False, "reason": "RESEND_API_KEY not configured"}
        ok = notifier.send_email(
            settings, to, "koyracloud test email",
            notifier._wrap("Test email", "If you got this, email alerts work. 🎉"))
        return {"sent": ok, "from": settings.email_from}

    # ----- team / access (admin-managed invite list) ----------------------
    @app.get("/api/allowed-users")
    def list_allowed_users(login: str = AdminAuth):
        with db.session() as s:
            members = [{"login": u.login, "added_by": u.added_by}
                       for u in s.query(AllowedUser).order_by(AllowedUser.login).all()]
        return {"admins": sorted(settings.allowed_logins), "members": members}

    @app.post("/api/allowed-users", status_code=201)
    def add_allowed_user(body: AllowedUserIn, login: str = AdminAuth):
        target = body.login.lower()
        if auth.is_allowed(target, settings.allowed_logins):
            raise HTTPException(status_code=409, detail="already an admin")
        with db.session() as s:
            if s.query(AllowedUser).filter_by(login=target).first():
                raise HTTPException(status_code=409, detail="already invited")
            s.add(AllowedUser(login=target, added_by=login))
            s.commit()
        return {"login": target, "added_by": login}

    @app.delete("/api/allowed-users/{member}", status_code=204)
    def remove_allowed_user(member: str, login: str = AdminAuth):
        with db.session() as s:
            u = s.query(AllowedUser).filter_by(login=member.lower()).first()
            if u:
                s.delete(u)
                s.commit()
        return Response(status_code=204)

    # ----- managed-koyracloud waitlist (public demand validation) ---------
    @app.post("/api/waitlist", status_code=201)
    def join_waitlist(body: WaitlistIn, request: Request):
        # Public + unauthenticated. Rate-limited per IP; duplicate email is a
        # quiet success (idempotent), so re-submits don't error or double-notify.
        if not _waitlist_rl.allow(_client_ip(request)):
            raise HTTPException(status_code=429, detail="rate limited")
        with db.session() as s:
            existing = s.query(Waitlist).filter_by(email=body.email).first()
            is_new = existing is None
            if is_new:
                s.add(Waitlist(email=body.email, site_count=body.site_count))
            else:
                # Re-submit: no new row, but keep the latest ICP bucket so an
                # upgrade (e.g. 1-2 → 10+) isn't silently dropped. created_at
                # stays at first signup.
                existing.site_count = body.site_count
            s.commit()
        if is_new and settings.default_notify_email:
            threading.Thread(
                target=notifier.send_email,
                args=(settings, settings.default_notify_email,
                      "New koyracloud waitlist signup",
                      notifier._wrap("New waitlist signup",
                                     f"{html.escape(body.email)} · {body.site_count} sites")),
                daemon=True).start()
        return {"ok": True}

    @app.get("/api/waitlist")
    def list_waitlist(login: str = AdminAuth):
        with db.session() as s:
            rows = s.query(Waitlist).order_by(Waitlist.id.desc()).all()
        return {"count": len(rows),
                "signups": [{"email": w.email, "site_count": w.site_count,
                             "created_at": w.created_at.isoformat()} for w in rows]}

    # ----- apps -----------------------------------------------------------
    def _app_out(obj: App) -> AppOut:
        out = AppOut.model_validate(obj)
        out.latest_status = obj.deploys[0].status if obj.deploys else None
        primary = next((d for d in obj.domains if d.is_primary), None) \
            or (obj.domains[0] if obj.domains else None)
        out.primary_host = primary.host if primary else None
        return out

    from urllib.parse import urlparse
    _control_host = urlparse(settings.base_url).netloc.lower().split(":")[0]

    def _is_reserved_host(host: str, own_auto: str) -> bool:
        """Block claiming the control-plane host, the apps-domain apex, or any
        in-zone subdomain other than this app's own auto-subdomain (``own_auto``).
        The whole apps_domain is the platform's namespace, so a custom domain a
        user attaches must be external."""
        host = host.lower()
        apps = settings.apps_domain.lower()
        reserved = {apps, _control_host, *(h.lower() for h in settings.reserved_hosts)}
        if host in reserved:
            return True
        if host.endswith("." + apps):
            return host != own_auto.lower()
        return False

    def _new_subdomain_token(s) -> str:
        """A short random slug that no existing app already uses (so default
        URLs are collision-free)."""
        while True:
            token = _secrets.token_hex(3)
            if not s.query(App).filter_by(subdomain_token=token).first():
                return token

    def _dns_ok(host: str) -> bool | None:
        """True if host resolves to the homelab IP, False if it resolves
        elsewhere, None if unknown (no configured IP or resolution failed)."""
        if not settings.public_ip:
            return None
        try:
            return socket.gethostbyname(host) == settings.public_ip
        except OSError:
            return False

    def _in_apps_zone(host: str) -> bool:
        """The app's own auto-subdomain (under the configured apps_domain) is
        already in the SaaS zone — no Cloudflare custom hostname is needed."""
        apps = settings.apps_domain.lower()
        h = host.lower()
        return h == apps or h.endswith("." + apps)

    def _domain_out(d: Domain) -> DomainOut:
        """Serialize a Domain, layering in DNS + Cloudflare custom-hostname
        state. For Cloudflare-managed hosts (those with a DomainCert) the status
        comes from the cert: such a host CNAMEs to the SaaS origin → Cloudflare
        anycast, so the WAN-IP ``dns_ok`` check is meaningless and is suppressed
        in favour of the edge cert status."""
        out = DomainOut.model_validate(d)
        if d.cert is not None:
            out.dns_ok = None
            out.ssl_status = d.cert.ssl_status or None
            out.verified = d.cert.ssl_status == "active"
            out.records = [DnsRecord(**r) for r in cloudflare.records_for(d.host)]
            # Only when ownership hasn't auto-validated (rare with the proxied
            # traffic CNAME) does the customer need the extra TXT record.
            if d.cert.ownership_status != "active" and d.cert.ownership_name:
                out.records.append(DnsRecord(
                    type="TXT", name=d.cert.ownership_name, value=d.cert.ownership_value))
        else:
            out.dns_ok = _dns_ok(d.host)
        return out

    def _ensure_cert(s, d: Domain) -> DomainCert | None:
        """Register/adopt a Cloudflare custom hostname for a custom host that
        lacks a DomainCert, persisting the row. No-op (returns None) for the
        in-zone auto-subdomain, when Cloudflare isn't configured, or on error.
        ``create_custom_hostname`` adopts an already-existing hostname, so this
        is safe to call repeatedly and as a backfill for pre-existing domains."""
        if d.cert is not None:
            return d.cert
        if not cloudflare.configured or _in_apps_zone(d.host):
            return None
        created = cloudflare.create_custom_hostname(d.host)
        if not created or not created.get("id"):  # guard against a malformed/empty result
            return None
        dcv = cloudflare.dcv_uuid()
        own = created.get("ownership") or {}
        d.cert = DomainCert(
            cf_hostname_id=created["id"], ssl_status=created["ssl_status"],
            ownership_status=created["status"],
            dcv_target=(f"{d.host}.{dcv}.dcv.cloudflare.com" if dcv else ""),
            ownership_name=own.get("name", ""), ownership_value=own.get("value", ""),
            last_checked=dt.datetime.now(dt.timezone.utc))
        s.flush()
        return d.cert

    def _backfill_certs() -> None:
        """One-shot: register/adopt CF custom hostnames for existing custom
        domains that predate the feature (no DomainCert yet)."""
        if not cloudflare.configured:
            return
        try:
            with db.session() as s:
                for d in s.query(Domain).all():
                    if d.cert is None and not _in_apps_zone(d.host):
                        _ensure_cert(s, d)
                s.commit()
        except Exception as e:  # noqa: BLE001 — best-effort; never block startup
            print(f"[koyra:cf] backfill failed: {e}", flush=True)

    @app.get("/api/apps", response_model=list[AppOut])
    def list_apps(login: str = Auth):
        with db.session() as s:
            q = s.query(App).order_by(App.name)
            if not is_admin(login):
                q = q.filter(App.owner_login == login)
            return [_app_out(a) for a in q.all()]

    @app.post("/api/apps", response_model=AppOut, status_code=201)
    def create_app_route(body: AppCreate, login: str = Auth):
        with db.session() as s:
            if s.query(App).filter_by(name=body.name).first():
                raise HTTPException(status_code=409, detail="app name already exists")
            obj = App(name=body.name, repo_url=body.repo_url, branch=body.branch,
                      auto_deploy=body.auto_deploy, owner_login=login,
                      subdomain_token=_new_subdomain_token(s))
            s.add(obj)
            s.flush()
            # Seed the default auto-subdomain (<name>-<token>.<apps_domain>) as
            # the primary domain.
            s.add(Domain(app_id=obj.id,
                         host=auto_subdomain(obj.name, obj.subdomain_token, settings),
                         is_primary=True))
            s.add(AppAnalytics(app_id=obj.id, token=analytics.new_token(), enabled=True))
            s.add(AppNotify(app_id=obj.id, owner_login=login, notify_email=""))
            s.commit()
            return _app_out(obj)

    @app.patch("/api/apps/{app_id}", response_model=AppOut)
    def update_app(app_id: int, body: AppUpdate, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            if body.branch is not None:
                obj.branch = body.branch
            if body.auto_deploy is not None:
                obj.auto_deploy = body.auto_deploy
            s.commit()
            return _app_out(obj)

    @app.get("/api/apps/status")
    def apps_status(login: str = Auth):
        # One docker call for the whole list; mapped to each app by service name.
        overview = docker.services_overview()
        with db.session() as s:
            q = s.query(App)
            if not is_admin(login):
                q = q.filter(App.owner_login == login)
            apps = q.all()
            result = {}
            for a in apps:
                svc = f"koyra-{a.name}_{a.name}"
                st = overview.get(svc)
                result[str(a.id)] = ({"exists": True, **st} if st
                                     else {"exists": False, "running": 0, "desired": 0})
        return result

    @app.get("/api/apps/{app_id}", response_model=AppOut)
    def get_app(app_id: int, login: str = Auth):
        with db.session() as s:
            return _app_out(get_app_or_404(app_id, s, login))

    @app.delete("/api/apps/{app_id}", status_code=204)
    def delete_app(app_id: int, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            name = obj.name
            # Background state isn't an App relationship — clean it explicitly so
            # no cron jobs/runs or Redis credential are orphaned.
            for j in s.query(CronJob).filter_by(app_id=app_id).all():
                s.delete(j)   # cascades its CronRun history
            ar = s.get(AppRedis, app_id)
            redis_user = ar.username if ar else ""
            if ar:
                s.delete(ar)
            s.delete(obj)
            s.commit()
        try:  # best-effort teardown; never block the delete on swarm state
            for _ in docker.remove(f"koyra-{name}"):
                pass
        except Exception:  # noqa: BLE001
            pass
        if redis_user:  # drop the scoped ACL user from the shared instance
            try:
                deployer._get_redis_admin().delete_user(redis_user)
            except Exception:  # noqa: BLE001
                pass
        return Response(status_code=204)

    # ----- env vars -------------------------------------------------------
    @app.get("/api/apps/{app_id}/env", response_model=list[EnvVarIn])
    def get_env(app_id: int, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            return [EnvVarIn(key=e.key, value=e.value) for e in obj.env_vars]

    @app.put("/api/apps/{app_id}/env", response_model=list[EnvVarIn])
    def put_env(app_id: int, body: list[EnvVarIn], login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            obj.env_vars.clear()
            s.flush()
            for item in body:
                s.add(EnvVar(app_id=obj.id, key=item.key, value=item.value))
            s.commit()
            return [EnvVarIn(key=e.key, value=e.value) for e in obj.env_vars]

    # ----- secrets (values never returned) --------------------------------
    @app.get("/api/apps/{app_id}/secrets", response_model=list[str])
    def list_secret_keys(app_id: int, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            return [sec.key for sec in obj.secrets]

    @app.put("/api/apps/{app_id}/secrets", status_code=204)
    def put_secret(app_id: int, body: SecretIn, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            existing = next((x for x in obj.secrets if x.key == body.key), None)
            token = crypto.encrypt(body.value)
            if existing:
                existing.value_encrypted = token
            else:
                s.add(Secret(app_id=obj.id, key=body.key, value_encrypted=token))
            s.commit()
        return Response(status_code=204)

    @app.delete("/api/apps/{app_id}/secrets/{key}", status_code=204)
    def delete_secret(app_id: int, key: str, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            sec = next((x for x in obj.secrets if x.key == key), None)
            if sec:
                s.delete(sec)
                s.commit()
        return Response(status_code=204)

    # ----- domains --------------------------------------------------------
    @app.get("/api/apps/{app_id}/domains", response_model=list[DomainOut])
    def list_domains(app_id: int, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            return [_domain_out(d) for d in obj.domains]

    @app.post("/api/apps/{app_id}/domains", response_model=DomainOut, status_code=201)
    def add_domain(app_id: int, body: DomainIn, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            own_auto = auto_subdomain(obj.name, obj.subdomain_token, settings)
            if _is_reserved_host(body.host, own_auto):
                raise HTTPException(status_code=400, detail="that host is reserved")
            if s.query(Domain).filter_by(host=body.host).first():
                raise HTTPException(status_code=409, detail="domain already in use")
            d = Domain(app_id=obj.id, host=body.host,
                       is_primary=len(obj.domains) == 0)
            s.add(d)
            s.flush()
            # Register external custom domains with Cloudflare for SaaS so the
            # edge mints + renews their cert (adopts an existing hostname if one
            # is already there). The app's own in-zone auto-subdomain needs none.
            # CF failures are non-fatal: the domain is still saved; records
            # simply won't appear until a later verify/backfill succeeds.
            _ensure_cert(s, d)
            deploy_id = _redeploy_if_live(s, obj)
            s.commit()
            out = _domain_out(d)
        if deploy_id is not None:
            schedule(deploy_id)
        return out

    @app.post("/api/apps/{app_id}/domains/{domain_id}/primary", response_model=DomainOut)
    def set_primary_domain(app_id: int, domain_id: int, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            target = next((d for d in obj.domains if d.id == domain_id), None)
            if target is None:
                raise HTTPException(status_code=404, detail="domain not found")
            for d in obj.domains:
                d.is_primary = d.id == domain_id
            s.commit()
            return _domain_out(target)

    @app.delete("/api/apps/{app_id}/domains/{domain_id}", status_code=204)
    def delete_domain(app_id: int, domain_id: int, login: str = Auth):
        cf_hostname_id = ""
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            target = next((d for d in obj.domains if d.id == domain_id), None)
            if target is None:
                raise HTTPException(status_code=404, detail="domain not found")
            if target.cert is not None:
                cf_hostname_id = target.cert.cf_hostname_id
            was_primary = target.is_primary
            s.delete(target)
            s.flush()
            remaining = s.query(Domain).filter_by(app_id=obj.id).order_by(Domain.id).all()
            if was_primary and remaining:
                remaining[0].is_primary = True
            deploy_id = _redeploy_if_live(s, obj)
            s.commit()
        # Best-effort: drop the Cloudflare custom hostname (non-fatal).
        if cf_hostname_id:
            cloudflare.delete_custom_hostname(cf_hostname_id)
        if deploy_id is not None:
            schedule(deploy_id)
        return Response(status_code=204)

    @app.post("/api/apps/{app_id}/domains/{domain_id}/verify", response_model=DomainOut)
    def verify_domain(app_id: int, domain_id: int, login: str = Auth):
        """Poll Cloudflare for the custom hostname's live status and persist it."""
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            target = next((d for d in obj.domains if d.id == domain_id), None)
            if target is None:
                raise HTTPException(status_code=404, detail="domain not found")
            # Backfill: a custom host with no cert yet (added before the feature,
            # or while CF was unconfigured) gets registered/adopted here.
            cert = _ensure_cert(s, target)
            if cert is not None and cert.cf_hostname_id:
                info = cloudflare.get_custom_hostname(cert.cf_hostname_id)
                if info:
                    cert.ssl_status = info["ssl_status"]
                    cert.ownership_status = info["status"]
                    own = info.get("ownership") or {}
                    cert.ownership_name = own.get("name", "")
                    cert.ownership_value = own.get("value", "")
                    cert.last_checked = dt.datetime.now(dt.timezone.utc)
            s.commit()
            return _domain_out(target)

    # ----- runtime (live service) ----------------------------------------
    def _service_name(name: str) -> str:
        return f"koyra-{name}_{name}"

    @app.get("/api/apps/{app_id}/status")
    def runtime_status(app_id: int, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            name = obj.name
        return docker.service_status(_service_name(name))

    @app.get("/api/apps/{app_id}/runtime-logs")
    def runtime_logs(app_id: int, tail: int = 200, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            name = obj.name
        return {"logs": docker.service_logs(_service_name(name), min(max(tail, 10), 1000))}

    @app.get("/api/apps/{app_id}/uptime")
    def app_uptime(app_id: int, login: str = Auth):
        with db.session() as s:
            get_app_or_404(app_id, s, login)
        return monitor.uptime_summary(db, app_id)

    @app.get("/api/apps/{app_id}/notify")
    def get_notify(app_id: int, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            n = obj.notify
            return {"owner_login": n.owner_login if n else "",
                    "notify_email": n.notify_email if n else "",
                    "email_configured": bool(settings.resend_api_key)}

    @app.put("/api/apps/{app_id}/notify", status_code=204)
    def set_notify(app_id: int, body: dict, login: str = Auth):
        email = (body.get("notify_email") or "").strip()
        if email and not _EMAIL_RE.match(email):
            raise HTTPException(status_code=422, detail="invalid email")
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            n = obj.notify or AppNotify(app_id=obj.id)
            n.notify_email = email
            s.add(n)
            s.commit()
        return Response(status_code=204)

    @app.get("/api/apps/{app_id}/analytics")
    def app_analytics(app_id: int, days: int = 7, login: str = Auth):
        with db.session() as s:
            get_app_or_404(app_id, s, login)
            rec = get_or_create_analytics(s, app_id)
            token, enabled = rec.token, rec.enabled
        data = analytics.aggregate(db, app_id, days=min(max(days, 1), 30))
        snippet = (f'<script defer src="{settings.base_url}/_k/a.js" '
                   f'data-site="{token}"></script>')
        return {**data, "enabled": enabled, "snippet": snippet}

    @app.put("/api/apps/{app_id}/analytics", status_code=204)
    def set_analytics(app_id: int, body: dict, login: str = Auth):
        with db.session() as s:
            get_app_or_404(app_id, s, login)
            rec = get_or_create_analytics(s, app_id)
            rec.enabled = bool(body.get("enabled", True))
            s.commit()
        return Response(status_code=204)

    # ----- background: workers, cron, redis -------------------------------
    def _worker_status(app_name: str) -> list[dict]:
        """Worker services are ``koyra-<app>_<app>-<worker>``; derive the list +
        replica counts from the one services overview (no per-worker DB rows)."""
        prefix = f"koyra-{app_name}_{app_name}-"
        out = []
        for svc, st in docker.services_overview().items():
            if svc.startswith(prefix):
                out.append({"name": svc[len(prefix):],
                            "running": st.get("running", 0),
                            "desired": st.get("desired", 0)})
        return sorted(out, key=lambda w: w["name"])

    def _owned_cron_job(app_id: int, job_id: int, s, login: str) -> CronJob:
        obj = get_app_or_404(app_id, s, login)
        j = s.get(CronJob, job_id)
        if j is None or j.app_id != obj.id:
            raise HTTPException(status_code=404, detail="cron job not found")
        return j

    @app.get("/api/apps/{app_id}/background")
    def app_background(app_id: int, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            name = obj.name
            redis_on = s.get(AppRedis, app_id) is not None
            cron = []
            for j in s.query(CronJob).filter_by(app_id=app_id).order_by(CronJob.name).all():
                last = (s.query(CronRun).filter_by(cron_job_id=j.id)
                        .order_by(CronRun.id.desc()).first())
                cron.append({
                    "id": j.id, "name": j.name, "schedule": j.schedule,
                    "command": j.command, "enabled": j.enabled,
                    "last_run_at": j.last_run_at.isoformat() if j.last_run_at else None,
                    "last_status": last.status if last else None,
                })
        return {"redis": {"enabled": redis_on, "prefix": name},
                "workers": _worker_status(name), "cron": cron}

    @app.get("/api/apps/{app_id}/workers/{worker}/logs")
    def worker_logs(app_id: int, worker: str, tail: int = 200, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            name = obj.name
        svc = f"koyra-{name}_{worker_service_name(name, worker)}"
        return {"logs": docker.service_logs(svc, min(max(tail, 10), 1000))}

    @app.get("/api/apps/{app_id}/cron/{job_id}/runs")
    def cron_runs(app_id: int, job_id: int, limit: int = 20, login: str = Auth):
        with db.session() as s:
            _owned_cron_job(app_id, job_id, s, login)
            runs = (s.query(CronRun).filter_by(cron_job_id=job_id)
                    .order_by(CronRun.id.desc()).limit(min(max(limit, 1), 100)).all())
            return [{
                "id": r.id, "status": r.status, "exit_code": r.exit_code,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            } for r in runs]

    @app.get("/api/apps/{app_id}/cron/{job_id}/runs/{run_id}/log")
    def cron_run_log(app_id: int, job_id: int, run_id: int, login: str = Auth):
        with db.session() as s:
            _owned_cron_job(app_id, job_id, s, login)
            r = s.get(CronRun, run_id)
            if r is None or r.cron_job_id != job_id:
                raise HTTPException(status_code=404, detail="run not found")
            return {"status": r.status, "exit_code": r.exit_code, "log": r.log or ""}

    @app.post("/api/apps/{app_id}/cron/{job_id}/run", status_code=202)
    def cron_run_now(app_id: int, job_id: int, login: str = Auth):
        with db.session() as s:
            _owned_cron_job(app_id, job_id, s, login)
        launch_cron(job_id)
        return {"launched": True}

    # ----- deploys --------------------------------------------------------
    @app.get("/api/apps/{app_id}/deploys", response_model=list[DeployOut])
    def list_deploys(app_id: int, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            return [DeployOut.model_validate(d) for d in obj.deploys]

    @app.post("/api/apps/{app_id}/deploys", response_model=DeployOut, status_code=201)
    def trigger_deploy(app_id: int, body: DeployTrigger | None = None, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            ref = (body.ref if body and body.ref else None) or obj.branch
            d = Deploy(app_id=obj.id, ref=ref, status="pending")
            s.add(d)
            s.commit()
            deploy_id = d.id
            out = DeployOut.model_validate(d)
        schedule(deploy_id)
        return out

    @app.get("/api/deploys/{deploy_id}", response_model=DeployOut)
    def get_deploy(deploy_id: int, login: str = Auth):
        with db.session() as s:
            return DeployOut.model_validate(owned_deploy_or_404(deploy_id, s, login))

    @app.get("/api/deploys/{deploy_id}/log")
    def get_deploy_log(deploy_id: int, login: str = Auth):
        with db.session() as s:
            d = owned_deploy_or_404(deploy_id, s, login)
            return {"status": d.status, "log": d.log or ""}

    @app.get("/api/deploys/{deploy_id}/logs")
    def stream_deploy_logs(deploy_id: int, login: str = Auth):
        with db.session() as s:  # authorize once before streaming
            owned_deploy_or_404(deploy_id, s, login)

        def gen():
            sent = 0
            while True:
                with db.session() as s:
                    d = s.get(Deploy, deploy_id)
                    if d is None:
                        return
                    log, status = d.log or "", d.status
                if len(log) > sent:
                    for line in log[sent:].splitlines():
                        yield f"data: {line}\n\n"
                    sent = len(log)
                if status in TERMINAL:
                    yield f"event: done\ndata: {status}\n\n"
                    return
                time.sleep(0.5)
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/api/apps/{app_id}/rollback", response_model=DeployOut, status_code=201)
    def rollback(app_id: int, body: RollbackRequest, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s, login)
            target = s.get(Deploy, body.deploy_id)
            if target is None or target.app_id != obj.id or not target.commit:
                raise HTTPException(status_code=400, detail="invalid rollback target")
            d = Deploy(app_id=obj.id, ref=target.commit, status="pending")
            s.add(d)
            s.commit()
            deploy_id = d.id
            out = DeployOut.model_validate(d)
        schedule(deploy_id)
        return out

    # ----- SPA ------------------------------------------------------------
    if WEB_DIST.is_dir():
        _web_root = WEB_DIST.resolve()

        @app.get("/{full_path:path}")
        def spa(full_path: str):
            # Serve a real static file only if it resolves INSIDE web/dist
            # (blocks ../ path traversal); otherwise fall back to the SPA shell.
            if full_path:
                candidate = (WEB_DIST / full_path).resolve()
                if (candidate == _web_root or
                        str(candidate).startswith(str(_web_root) + os.sep)) \
                        and candidate.is_file():
                    return FileResponse(candidate)
            return FileResponse(_web_root / "index.html")

    # Background uptime monitor (production only; run_async gates real bg work).
    if run_async and settings.uptime_enabled:
        def _on_transition(app_id: int, state: str) -> None:
            print(f"[koyra:uptime] app {app_id} -> {state}", flush=True)
            notify_event(app_id, "recovered" if state == "up" else "down")
        monitor.UptimeMonitor(db, settings.uptime_interval,
                              on_transition=_on_transition).start()

    # Cron scheduler: launch due jobs as Swarm run-to-completion jobs each tick.
    if run_async and settings.cron_enabled:
        scheduler.CronScheduler(db, docker, settings, crypto,
                                settings.cron_tick_seconds).start()

    # One-shot backfill of Cloudflare custom hostnames for pre-existing custom
    # domains (run off-thread so a slow/unreachable CF API never blocks boot).
    if run_async and cloudflare.configured:
        threading.Thread(target=_backfill_certs, daemon=True).start()

    if run_async and settings.backup_enabled:
        from koyracloud import backup
        dbf = backup.sqlite_file(settings.db_url)
        if dbf:
            backup.BackupLoop(dbf, dbf.parent / "backups",
                              settings.backup_interval_hours * 3600,
                              settings.backup_keep).start()

    app.state.db = db
    app.state.settings = settings
    return app
