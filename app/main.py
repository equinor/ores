
from __future__ import annotations
import asyncio
import os
import re
import secrets
import urllib.parse
import logging
import json
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional, Set

import httpx
from httpx import HTTPStatusError
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from starlette.middleware.sessions import SessionMiddleware

# App modules
from .schemahandler import extract_osdu_links
from .schemahandler import extract_metadata_generic
from app.ingest_router import router as ingest_router
from . import osdu
from .auth import (
    router as auth_router,
    tokens_from_env,
    tokens_from_session,
    AUTH_MODE,
    PUBLIC_PATHS,
)
from .instances import get_instances, get_active, set_active, get_active_name
from .strat import router as strat_router
from .analyse import router as analyse_router
from .addgate import router as addgate_router
from .keys_router import router as keys_router
from .graphql_router import router as graphql_router
from .graphql_refdata import router as graphql_refdata_router
from .search_router import router as search_router
from .common import pretty_val as _jinja_pretty_val, access_token as _access_token
from .howto_router import router as howto_router

# ──────────────────────────────────────────────────────────────────────────────
# App setup & logging
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger("rddms-admin")


@asynccontextmanager
async def _lifespan(application: FastAPI):
    """Startup / shutdown lifecycle hook (replaces deprecated on_event)."""
    yield
    # ── Shutdown ──
    await osdu.close_shared_client()
    from .pg_backend import close_pool
    await close_pool()


app = FastAPI(title="RDDMS Admin", lifespan=_lifespan)

# ── Stable secret key (must be identical across workers) ─────────────────────
_SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(16)
_HTTPS_ONLY = os.getenv("HTTPS_ONLY", "false").lower() in ("1", "true", "yes")

# Security headers & cache hardening
@app.middleware("http")
async def no_transform_headers(request: Request, call_next):
    resp: Response = await call_next(request)
    resp.headers.setdefault("Cache-Control", "no-store, no-transform")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    return resp

# Auth middleware: env-token primary → per-user session fallback → redirect to /login
@app.middleware("http")
async def inject_access_token(request: Request, call_next):
    """
    Resolve an access_token and attach it to request.state.
    Priority:
      0) Per-user session token (PKCE) - if user explicitly signed in, honour it
      1) Active instance token (client_credentials / instance refresh)
      2) REFRESH_TOKEN from env (default instance)
      3) Redirect to /login
    """
    path = request.url.path

    # Let public paths through without a token
    if path in PUBLIC_PATHS or path.startswith("/static"):
        return await call_next(request)

    access_token: str | None = None

    # 0. Prefer per-user PKCE token when the user has an active session
    #    AND the session was created for the currently active instance.
    #    After an instance switch, the old session token would be scoped to
    #    the previous Azure AD tenant/app - skip it so we fall through to
    #    the new instance's own token (client_credentials or env RT).
    session_oid = request.session.get("oid", "")
    if session_oid:
        session_inst = request.session.get("instance_name", "")
        active_inst = get_active_name()
        if session_inst == active_inst:
            try:
                sess_tokens = await tokens_from_session(request)
                if sess_tokens:
                    access_token = sess_tokens.get("access_token")
                else:
                    log.debug("Session token expired for oid=%s… inst=%s", session_oid[:8], session_inst)
            except Exception as e:
                log.warning("Session token failed: %s", e)
        else:
            log.debug("Skipping session token: session=%s active=%s", session_inst, active_inst)

    # 1. Try active instance's own token (client_credentials or refresh)
    if not access_token:
        try:
            inst = get_active()
            inst_token = await inst.get_access_token()
            if inst_token:
                access_token = inst_token
        except Exception as e:
            log.warning("Instance token mint failed: %s", e)

    # 2. Try shared env-token (default instance, refresh_token from env)
    if not access_token:
        try:
            env_tokens = await tokens_from_env()
            if env_tokens:
                access_token = env_tokens.get("access_token")
        except Exception as e:
            log.warning("Env-token mint failed: %s", e)

    # 3. No token at all - redirect to login page (for browser) or 401 (for API)
    if not access_token:
        if path.startswith("/api"):
            return JSONResponse({"error": "Authentication required. No env token and no session."}, status_code=401)
        return RedirectResponse("/login-page")

    request.state.access_token = access_token
    resp = await call_next(request)
    # Set lightweight marker cookie so the nav bar JS can show
    # "Sign out" (green dot) instead of "Sign in" (grey dot).
    if "ores_user" not in request.cookies:
        resp.set_cookie("ores_user", "1", max_age=30 * 24 * 3600,
                        samesite="lax", httponly=False,
                        secure=_HTTPS_ONLY)
    return resp

# Attach routers & static
# Session middleware - added LAST so it is outermost and runs FIRST,
# making request.session available to all inner middleware.
app.add_middleware(
    SessionMiddleware,
    secret_key=_SECRET_KEY,
    session_cookie="ores_session",
    max_age=30 * 24 * 3600,    # 30-day session cookie (RT kept alive via tokenstore)
    same_site="lax",
    https_only=_HTTPS_ONLY,    # set HTTPS_ONLY=true in prod behind TLS
)

app.include_router(auth_router)  # keeps /auth diagnostics
app.include_router(ingest_router, prefix="/api")
app.include_router(strat_router)
app.include_router(analyse_router)
app.include_router(addgate_router)
app.include_router(keys_router)
app.include_router(graphql_router)
app.include_router(graphql_refdata_router)
app.include_router(search_router)
app.include_router(howto_router)


app.mount(
    "/static",
    StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")),
    name="static",
)
templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)
# Make auth_mode available in every template (for nav Sign-out link)
templates.env.globals["auth_mode"] = AUTH_MODE


# ─── Favicon (avoid 404 noise in logs) ───────────────────────────────────── #

_FAVICON_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    b'<circle cx="16" cy="16" r="14" fill="#FF1243"/>'
    b'<text x="16" y="22" font-size="16" text-anchor="middle" fill="#fff" '
    b'font-family="sans-serif" font-weight="bold">O</text></svg>'
)


@app.get("/favicon.ico", include_in_schema=False)
async def _favicon():
    return Response(content=_FAVICON_SVG, media_type="image/svg+xml")


templates.env.filters["pretty_val"] = _jinja_pretty_val

# ── Startup banner with PID (visible in terminal for easy kill) ──────────────
import sys as _sys
_pid = os.getpid()
_banner = (
    f"\n"
    f"  ╔══════════════════════════════════════════════╗\n"
    f"  ║  ORES  -  OSDU Record Explorer & Stratigraphy ║\n"
    f"  ║  PID: {_pid:<39d} ║\n"
    f"  ║  Kill: kill {_pid:<34d} ║\n"
    f"  ╚══════════════════════════════════════════════╝\n"
)
print(_banner, file=_sys.stderr, flush=True)
log.info("ORES starting - PID %d", _pid)

# Log routes at startup (helps when a route goes missing)
log.info("Routes registered: %d routes", len(app.routes))
log.debug("Route paths: %s", [getattr(r, "path", str(r)) for r in app.routes])

# ──────────────────────────────────────────────────────────────────────────────
# OSDU instance switching
# ──────────────────────────────────────────────────────────────────────────────

# Initialise instance registry at import time (reads INSTANCE_* env vars)
_all_instances = get_instances()
log.info("OSDU instances loaded: %s (active=%s)", list(_all_instances.keys()), get_active_name())

# Re-sync template globals after instance init (auth_mode may have changed)
from .auth import AUTH_MODE as _AUTH_MODE_AFTER_INIT
templates.env.globals["auth_mode"] = _AUTH_MODE_AFTER_INIT

# Add /api/instances/* to PUBLIC_PATHS so they work before auth
# (switching / adding happens before a valid token exists for the new instance)
PUBLIC_PATHS.add("/api/instances")
PUBLIC_PATHS.add("/api/instances/probe")
PUBLIC_PATHS.add("/api/instances/switch")
PUBLIC_PATHS.add("/api/instances/add")


@app.get("/api/instances")
async def api_instances():
    """Return all registered OSDU instances and which is active."""
    insts = get_instances()
    return {
        "active": get_active_name(),
        "instances": {
            name: {
                "name": inst.name,
                "hostname": inst.hostname,
                "data_partition_id": inst.data_partition_id,
                "auth_mode": inst.auth_mode,
            }
            for name, inst in insts.items()
        },
    }


@app.get("/api/instances/probe")
async def api_probe_instance(request: Request):
    """Test whether the active instance can mint a token right now."""
    inst = get_active()
    # For per_user_pkce instances, check if the user has an active session
    has_session = False
    if inst.auth_mode == "per_user_pkce":
        oid = request.session.get("oid", "")
        session_inst = request.session.get("instance_name", "")
        if oid and session_inst == inst.name:
            sess_tokens = await tokens_from_session(request)
            has_session = sess_tokens is not None
    try:
        token = await inst.get_access_token()
        ok = token is not None or has_session
        return {
            "ok": ok,
            "instance": inst.name,
            "auth_mode": inst.auth_mode,
            "has_session": has_session,
            # Non-secret diagnostics to help troubleshoot token failures
            "tenant_id": inst.tenant_id[:8] + "…" if inst.tenant_id else "",
            "client_id": inst.client_id[:8] + "…" if inst.client_id else "",
            "scope": inst.scope or f"{inst.client_id}/.default",
            "has_secret": bool(inst.client_secret),
            "has_refresh": bool(inst.refresh_token),
        }
    except Exception as e:
        return {
            "ok": has_session,
            "instance": inst.name,
            "auth_mode": inst.auth_mode,
            "has_session": has_session,
            "error": str(e),
            "tenant_id": inst.tenant_id[:8] + "…" if inst.tenant_id else "",
            "client_id": inst.client_id[:8] + "…" if inst.client_id else "",
            "scope": inst.scope or f"{inst.client_id}/.default",
            "has_secret": bool(inst.client_secret),
            "has_refresh": bool(inst.refresh_token),
        }


@app.post("/api/instances/switch")
async def api_switch_instance(name: str = Form(...)):
    """Switch the active OSDU instance."""
    try:
        inst = set_active(name)
        # Re-sync Jinja globals after auth.py update
        from .auth import AUTH_MODE as _am
        templates.env.globals["auth_mode"] = _am
        # Try to mint a token immediately to validate connectivity
        token = await inst.get_access_token()
        return {
            "ok": True,
            "active": name,
            "hostname": inst.hostname,
            "partition": inst.data_partition_id,
            "auth_mode": inst.auth_mode,
            "token_ok": token is not None,
        }
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    except Exception as e:
        log.exception("Instance switch failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/instances/add")
async def api_add_instance(request: Request):
    """Add a new OSDU instance to k8s YAML files, register it, and activate it."""
    from .instances import _instances, _load_instances, OsduInstance

    form = await request.form()
    name = (form.get("name") or "").strip().lower()
    if not name or not name.isalnum():
        return JSONResponse({"ok": False, "error": "Name must be non-empty alphanumeric"}, status_code=400)
    if name in _instances:
        return JSONResponse({"ok": False, "error": f"Instance '{name}' already exists"}, status_code=409)

    PREFIX = f"INSTANCE_{name.upper()}_"

    # ── Sanitize form values for safe YAML inclusion (#14) ──
    def _safe(v: str) -> str:
        return re.sub(r'["\n\r\\]', '', (v or '')).strip()

    # ── Collect fields from form ──
    config_fields = {
        "HOSTNAME": _safe(form.get("hostname", "")),
        "DATA_PARTITION_ID": _safe(form.get("data_partition_id", "opendes")),
        "AUTHORITY": _safe(form.get("authority", "osdu")),
        "SCHEMA_SOURCE": _safe(form.get("schema_source", "wks")),
        "DEFAULT_LEGAL_TAG": _safe(form.get("default_legal_tag", "")),
        "DEFAULT_OWNERS": _safe(form.get("default_owners", "")),
        "DEFAULT_VIEWERS": _safe(form.get("default_viewers", "")),
        "DEFAULT_COUNTRIES": _safe(form.get("default_countries", "NO")),
    }
    secret_fields = {
        "TENANT_ID": _safe(form.get("tenant_id", "")),
        "CLIENT_ID": _safe(form.get("client_id", "")),
        "CLIENT_SECRET": _safe(form.get("client_secret", "")),
        "SCOPE": _safe(form.get("scope", "")),
        "REFRESH_TOKEN": _safe(form.get("refresh_token", "")),
    }

    if not config_fields["HOSTNAME"]:
        return JSONResponse({"ok": False, "error": "Hostname is required"}, status_code=400)

    k8s_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "k8s")
    cm_path = os.path.join(k8s_dir, "configmap.yaml")
    sec_path = os.path.join(k8s_dir, "secret.yaml")

    try:
        # ── Try to persist to k8s YAML files (will fail on read-only FS like Radix) ──
        files_written = False
        try:
            cm_lines = [f"\n  # ── \"{name}\" - added via ORES UI ──"]
            for field, val in config_fields.items():
                cm_lines.append(f'  {PREFIX}{field}: "{val}"')
            with open(cm_path, "a") as f:
                f.write("\n".join(cm_lines) + "\n")

            sec_lines = [f"\n  # ── \"{name}\" - added via ORES UI ──"]
            for field, val in secret_fields.items():
                if val:
                    sec_lines.append(f'  {PREFIX}{field}: "{val}"')
                else:
                    sec_lines.append(f'  # {PREFIX}{field}: ""')
            with open(sec_path, "a") as f:
                f.write("\n".join(sec_lines) + "\n")
            files_written = True
        except OSError as io_err:
            log.info("Could not write k8s YAMLs (%s) - registering in-memory only", io_err)

        # ── Set env vars so _load_instances picks them up ──
        for field, val in config_fields.items():
            os.environ[f"{PREFIX}{field}"] = val
        for field, val in secret_fields.items():
            if val:
                os.environ[f"{PREFIX}{field}"] = val

        # ── Register and activate ──
        _instances.clear()
        _load_instances()
        inst = set_active(name)

        # Re-sync Jinja globals
        from .auth import AUTH_MODE as _am
        templates.env.globals["auth_mode"] = _am

        token = await inst.get_access_token()
        log.info("Added and activated instance '%s' → %s (persisted=%s)", name, inst.hostname, files_written)

        return {
            "ok": True,
            "active": name,
            "hostname": inst.hostname,
            "partition": inst.data_partition_id,
            "auth_mode": inst.auth_mode,
            "token_ok": token is not None,
            "persisted": files_written,
        }

    except Exception as e:
        log.exception("Failed to add instance '%s'", name)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ──────────────────────────────────────────────────────────────────────────────
# Login landing page (per-user PKCE mode)
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/login-page", response_class=HTMLResponse)
async def login_page(request: Request):
    """Serve the sign-in landing page (only reached when no env token is set)."""
    insts = get_instances()
    return templates.TemplateResponse(request, "login.html", {
        "instances": {
            n: {"hostname": i.hostname, "partition": i.data_partition_id, "auth_mode": i.auth_mode}
            for n, i in insts.items()
        },
        "active_instance": get_active_name(),
    })

# Pages & actions
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/", response_class=RedirectResponse, summary="Redirect to ORES landing")
async def root_redirect():
    return RedirectResponse("/ores", status_code=302)


@app.get("/admin", response_class=HTMLResponse, summary="Admin: list dataspaces")
async def home(request: Request):
    # Render the shell immediately - dataspaces loaded async via JS
    return templates.TemplateResponse(
        request, "admin.html",
        {
            "view": "home",
            "dataspaces": [],
            # Defaults for the "Create Dataspace" form (prefilled values)
            "ds_default": os.getenv("DEFAULT_DATASPACE", ""),
            "default_legal_tag": osdu.DEFAULT_LEGAL_TAG,
            "default_owners": ",".join(osdu.DEFAULT_OWNERS),
            "default_viewers": ",".join(osdu.DEFAULT_VIEWERS),
            "default_countries": ",".join(osdu.DEFAULT_COUNTRIES),
        },
    )


@app.get("/admin/dataspaces.json", summary="Async dataspace list for admin page")
async def admin_dataspaces_json(request: Request):
    """JSON endpoint for client-side dataspace loading (cached 120 s)."""
    try:
        at = _access_token(request)
        dataspaces = await osdu.list_dataspaces(at)
    except Exception as e:
        log.warning("admin_dataspaces_json failed: %s", e)
        dataspaces = []
    items = []
    for x in dataspaces:
        if isinstance(x, dict):
            p = x.get("path") or x.get("Path") or x.get("DataspaceId") or ""
            if p:
                items.append({"path": p, "uri": x.get("uri", "")})
        elif isinstance(x, str) and x:
            items.append({"path": x, "uri": ""})
    return JSONResponse({"items": items})

@app.post("/dataspaces/create", summary="Create a dataspace with default legal/ACL")
async def dataspaces_create(
    request: Request,
    path: str = Form(...),
    legal: str = Form(osdu.DEFAULT_LEGAL_TAG),
    owners: str = Form(",".join(osdu.DEFAULT_OWNERS)),
    viewers: str = Form(",".join(osdu.DEFAULT_VIEWERS)),
    countries: str = Form(",".join(osdu.DEFAULT_COUNTRIES)),
    custom_json: str = Form("", description="Optional JSON to merge into CustomData"),
):
    at = _access_token(request)

    # Parse optional JSON block
    extra_custom: Dict[str, Any] = {}
    if custom_json and custom_json.strip():
        try:
            extra_custom = json.loads(custom_json)
            if not isinstance(extra_custom, dict):
                raise ValueError("Custom data must be a JSON object")
        except Exception as ex:
            return templates.TemplateResponse(
                request, "admin.html",
                {
                    "view": "home",
                    "dataspaces": [],
                    "ds_default": os.getenv("DEFAULT_DATASPACE", ""),
                    "default_legal_tag": osdu.DEFAULT_LEGAL_TAG,
                    "default_owners": ",".join(osdu.DEFAULT_OWNERS),
                    "default_viewers": ",".join(osdu.DEFAULT_VIEWERS),
                    "default_countries": ",".join(osdu.DEFAULT_COUNTRIES),
                    "error": "Invalid custom JSON",
                    "error_detail": str(ex),
                },
                status_code=400,
            )

    try:
        await osdu.create_dataspace(
            at,
            path,
            legal_tag=legal,
            owners=[x.strip() for x in owners.split(",") if x.strip()],
            viewers=[x.strip() for x in viewers.split(",") if x.strip()],
            countries=[x.strip() for x in countries.split(",") if x.strip()],
            extra_custom=extra_custom,
        )
        # Invalidate cached dataspace list so the new one appears immediately
        from .cache import cache_invalidate
        cache_invalidate("list_dataspaces")
    except HTTPStatusError as e:
        r = e.response
        return templates.TemplateResponse(
            request, "admin.html",
            {
                "view": "home",
                "dataspaces": [],
                "ds_default": os.getenv("DEFAULT_DATASPACE", ""),
                "default_legal_tag": osdu.DEFAULT_LEGAL_TAG,
                "default_owners": ",".join(osdu.DEFAULT_OWNERS),
                "default_viewers": ",".join(osdu.DEFAULT_VIEWERS),
                "default_countries": ",".join(osdu.DEFAULT_COUNTRIES),
                "error": f"Create failed: {r.status_code} {r.reason_phrase}",
                "error_detail": (r.text[:2000] if r.text else ""),
            },
            status_code=400,
        )
    return RedirectResponse(url=f"/keys?ds={urllib.parse.quote(path, safe='')}", status_code=302)
