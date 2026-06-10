"""FastAPI application factory for the koyracloud control plane."""
from __future__ import annotations

import json
import os
import secrets as _secrets
import socket
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

from koyracloud import auth, webhooks
from koyracloud.config import Settings, get_settings
from koyracloud.crypto import CryptoBox
from koyracloud.db import Database
from koyracloud.deployer import Deployer
from koyracloud.docker_ctl import CLIDockerControl, DockerControl
from koyracloud.models import (AllowedUser, App, Deploy, Domain, EnvVar,
                                Secret, User)
from koyracloud.schemas import (AllowedUserIn, AppCreate, AppOut, AppUpdate,
                                DeployOut, DeployTrigger, DomainIn, DomainOut,
                                EnvVarIn, RollbackRequest, SecretIn)

WEB_DIST = Path(os.environ.get(
    "KOYRA_WEB_DIST", str(Path(__file__).resolve().parents[2] / "web" / "dist")))
TERMINAL = {"live", "failed", "rolled_back"}


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
    run_async: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    _ensure_sqlite_dir(settings.db_url)
    db = db or Database(settings.db_url)
    db.create_all()
    crypto = CryptoBox(settings.secret_key)
    docker = docker or CLIDockerControl(resolve_image_never=settings.resolve_image_never)
    deployer = deployer or Deployer(settings=settings, docker=docker, crypto=crypto)

    # Disable FastAPI's built-in Swagger/OpenAPI routes so the SPA owns /docs.
    app = FastAPI(title="koyracloud", docs_url=None, redoc_url=None, openapi_url=None)

    def schedule(deploy_id: int) -> None:
        if run_async:
            threading.Thread(target=deployer.run_deploy, args=(db, deploy_id),
                             daemon=True).start()
        else:
            deployer.run_deploy(db, deploy_id)

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

    def get_app_or_404(app_id: int, s) -> App:
        obj = s.get(App, app_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="app not found")
        return obj

    # ----- health / auth routes ------------------------------------------
    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/config")
    def public_config():
        # Non-sensitive instance config for the UI (e.g. the DNS hint).
        return {"apps_domain": settings.apps_domain, "public_ip": settings.public_ip}

    @app.post("/api/webhooks/github")
    async def github_webhook(request: Request):
        # Unauthenticated but HMAC-verified: GitHub push → auto-deploy matching apps.
        body = await request.body()
        if not webhooks.verify_signature(settings.webhook_secret, body,
                                         request.headers.get("X-Hub-Signature-256")):
            raise HTTPException(status_code=401, detail="invalid signature")
        event = request.headers.get("X-GitHub-Event", "")
        if event == "ping":
            return {"ok": True}
        if event != "push":
            return {"ignored": event}
        try:
            payload = json.loads(body)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid payload")
        full = (payload.get("repository") or {}).get("full_name", "").lower()
        branch = webhooks.branch_from_ref(payload.get("ref", ""))
        triggered = []
        if full and branch:
            with db.session() as s:
                for a in s.query(App).filter_by(auto_deploy=True).all():
                    if webhooks.repo_slug(a.repo_url) == full and a.branch == branch:
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

    # ----- apps -----------------------------------------------------------
    def _app_out(obj: App) -> AppOut:
        out = AppOut.model_validate(obj)
        out.latest_status = obj.deploys[0].status if obj.deploys else None
        primary = next((d for d in obj.domains if d.is_primary), None) \
            or (obj.domains[0] if obj.domains else None)
        out.primary_host = primary.host if primary else None
        return out

    def _dns_ok(host: str) -> bool | None:
        """True if host resolves to the homelab IP, False if it resolves
        elsewhere, None if unknown (no configured IP or resolution failed)."""
        if not settings.public_ip:
            return None
        try:
            return socket.gethostbyname(host) == settings.public_ip
        except OSError:
            return False

    @app.get("/api/apps", response_model=list[AppOut])
    def list_apps(login: str = Auth):
        with db.session() as s:
            return [_app_out(a) for a in s.query(App).order_by(App.name).all()]

    @app.post("/api/apps", response_model=AppOut, status_code=201)
    def create_app_route(body: AppCreate, login: str = Auth):
        with db.session() as s:
            if s.query(App).filter_by(name=body.name).first():
                raise HTTPException(status_code=409, detail="app name already exists")
            obj = App(name=body.name, repo_url=body.repo_url, branch=body.branch,
                      auto_deploy=body.auto_deploy)
            s.add(obj)
            s.flush()
            # Seed the default auto-subdomain as the primary domain.
            s.add(Domain(app_id=obj.id, host=f"{obj.name}.{settings.apps_domain}",
                         is_primary=True))
            s.commit()
            return _app_out(obj)

    @app.patch("/api/apps/{app_id}", response_model=AppOut)
    def update_app(app_id: int, body: AppUpdate, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s)
            if body.branch is not None:
                obj.branch = body.branch
            if body.auto_deploy is not None:
                obj.auto_deploy = body.auto_deploy
            s.commit()
            return _app_out(obj)

    @app.get("/api/apps/{app_id}", response_model=AppOut)
    def get_app(app_id: int, login: str = Auth):
        with db.session() as s:
            return _app_out(get_app_or_404(app_id, s))

    @app.delete("/api/apps/{app_id}", status_code=204)
    def delete_app(app_id: int, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s)
            name = obj.name
            s.delete(obj)
            s.commit()
        try:  # best-effort teardown; never block the delete on swarm state
            for _ in docker.remove(f"koyra-{name}"):
                pass
        except Exception:  # noqa: BLE001
            pass
        return Response(status_code=204)

    # ----- env vars -------------------------------------------------------
    @app.get("/api/apps/{app_id}/env", response_model=list[EnvVarIn])
    def get_env(app_id: int, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s)
            return [EnvVarIn(key=e.key, value=e.value) for e in obj.env_vars]

    @app.put("/api/apps/{app_id}/env", response_model=list[EnvVarIn])
    def put_env(app_id: int, body: list[EnvVarIn], login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s)
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
            obj = get_app_or_404(app_id, s)
            return [sec.key for sec in obj.secrets]

    @app.put("/api/apps/{app_id}/secrets", status_code=204)
    def put_secret(app_id: int, body: SecretIn, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s)
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
            obj = get_app_or_404(app_id, s)
            sec = next((x for x in obj.secrets if x.key == key), None)
            if sec:
                s.delete(sec)
                s.commit()
        return Response(status_code=204)

    # ----- domains --------------------------------------------------------
    @app.get("/api/apps/{app_id}/domains", response_model=list[DomainOut])
    def list_domains(app_id: int, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s)
            out = []
            for d in obj.domains:
                item = DomainOut.model_validate(d)
                item.dns_ok = _dns_ok(d.host)
                out.append(item)
            return out

    @app.post("/api/apps/{app_id}/domains", response_model=DomainOut, status_code=201)
    def add_domain(app_id: int, body: DomainIn, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s)
            if s.query(Domain).filter_by(host=body.host).first():
                raise HTTPException(status_code=409, detail="domain already in use")
            d = Domain(app_id=obj.id, host=body.host,
                       is_primary=len(obj.domains) == 0)
            s.add(d)
            deploy_id = _redeploy_if_live(s, obj)
            s.commit()
            out = DomainOut.model_validate(d)
        out.dns_ok = _dns_ok(body.host)
        if deploy_id is not None:
            schedule(deploy_id)
        return out

    @app.post("/api/apps/{app_id}/domains/{domain_id}/primary", response_model=DomainOut)
    def set_primary_domain(app_id: int, domain_id: int, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s)
            target = next((d for d in obj.domains if d.id == domain_id), None)
            if target is None:
                raise HTTPException(status_code=404, detail="domain not found")
            for d in obj.domains:
                d.is_primary = d.id == domain_id
            s.commit()
            return DomainOut.model_validate(target)

    @app.delete("/api/apps/{app_id}/domains/{domain_id}", status_code=204)
    def delete_domain(app_id: int, domain_id: int, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s)
            target = next((d for d in obj.domains if d.id == domain_id), None)
            if target is None:
                raise HTTPException(status_code=404, detail="domain not found")
            was_primary = target.is_primary
            s.delete(target)
            s.flush()
            remaining = s.query(Domain).filter_by(app_id=obj.id).order_by(Domain.id).all()
            if was_primary and remaining:
                remaining[0].is_primary = True
            deploy_id = _redeploy_if_live(s, obj)
            s.commit()
        if deploy_id is not None:
            schedule(deploy_id)
        return Response(status_code=204)

    # ----- runtime (live service) ----------------------------------------
    def _service_name(name: str) -> str:
        return f"koyra-{name}_{name}"

    @app.get("/api/apps/{app_id}/status")
    def runtime_status(app_id: int, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s)
            name = obj.name
        return docker.service_status(_service_name(name))

    @app.get("/api/apps/{app_id}/runtime-logs")
    def runtime_logs(app_id: int, tail: int = 200, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s)
            name = obj.name
        return {"logs": docker.service_logs(_service_name(name), min(max(tail, 10), 1000))}

    # ----- deploys --------------------------------------------------------
    @app.get("/api/apps/{app_id}/deploys", response_model=list[DeployOut])
    def list_deploys(app_id: int, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s)
            return [DeployOut.model_validate(d) for d in obj.deploys]

    @app.post("/api/apps/{app_id}/deploys", response_model=DeployOut, status_code=201)
    def trigger_deploy(app_id: int, body: DeployTrigger | None = None, login: str = Auth):
        with db.session() as s:
            obj = get_app_or_404(app_id, s)
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
            d = s.get(Deploy, deploy_id)
            if d is None:
                raise HTTPException(status_code=404, detail="deploy not found")
            return DeployOut.model_validate(d)

    @app.get("/api/deploys/{deploy_id}/log")
    def get_deploy_log(deploy_id: int, login: str = Auth):
        with db.session() as s:
            d = s.get(Deploy, deploy_id)
            if d is None:
                raise HTTPException(status_code=404, detail="deploy not found")
            return {"status": d.status, "log": d.log or ""}

    @app.get("/api/deploys/{deploy_id}/logs")
    def stream_deploy_logs(deploy_id: int, login: str = Auth):
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
            obj = get_app_or_404(app_id, s)
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

    app.state.db = db
    app.state.settings = settings
    return app
