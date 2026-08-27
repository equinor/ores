
from __future__ import annotations
import os
import secrets
import time
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, JSONResponse
from authlib.integrations.httpx_client import AsyncOAuth2Client
from .tokenstore import (
    upsert as _ts_upsert,
    fetch as _ts_fetch,
    delete as _ts_delete,
    decode_id_token_payload,
    get_cached_at as _ts_get_cached_at,
    set_cached_at as _ts_set_cached_at,
)

log = logging.getLogger("rddms-admin")

# ─────────────────────────────────────────────────────────────
# Azure AD / Microsoft identity platform
# Mode 1: shared refresh_token from env  (zero-click, demo)
# Mode 2: per-user PKCE login            (fallback when no env token)
#
# NOTE: These module-level vars are overwritten by instances.py
#       _apply_instance() at startup and on every instance switch.
#       Initial values are just safe defaults.
# ─────────────────────────────────────────────────────────────
TENANT = os.getenv("AZURE_TENANT_ID", "") or os.getenv("INSTANCE_EQNDEV_TENANT_ID", "")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "") or os.getenv("INSTANCE_EQNDEV_CLIENT_ID", "")
SCOPES = (os.getenv("AZURE_SCOPE", "") or os.getenv("INSTANCE_EQNDEV_SCOPE", "openid offline_access")).split()

# SMDA API resource App ID (audience) - used by az CLI to mint tokens.
SMDA_CLIENT_ID = os.getenv("SMDA_CLIENT_ID", "")
SMDA_SCOPE = os.getenv("SMDA_SCOPE", "")
# Dedicated SMDA refresh token (obtained from az CLI session, uses CLI public client)
SMDA_REFRESH_TOKEN = os.getenv("SMDA_REFRESH_TOKEN", "")

AUTH_BASE = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0"
AUTHORIZE_URL = f"{AUTH_BASE}/authorize"
TOKEN_URL = f"{AUTH_BASE}/token"

# True when a shared refresh-token is available (from active instance)
ENV_REFRESH_TOKEN: Optional[str] = (
    os.getenv("REFRESH_TOKEN")
    or os.getenv("refresh_token")
    or None
)
AUTH_MODE = "env_token" if ENV_REFRESH_TOKEN else "per_user_pkce"

router = APIRouter(tags=["auth"])

# Paths that must be accessible without any token
PUBLIC_PATHS: set[str] = {"/login", "/login-page",
                          "/auth/callback", "/auth", "/logout"}

# ─────────────────────────────────────────────────────────────
# Mode 1 - shared env token
# ─────────────────────────────────────────────────────────────
_cached_env_token: Dict[str, Any] = {}
_cached_env_token_exp: float = 0.0

async def tokens_from_env() -> Optional[Dict[str, Any]]:
    """Mint access_token from the shared REFRESH_TOKEN in env.  Returns None if unavailable."""
    global _cached_env_token, _cached_env_token_exp, ENV_REFRESH_TOKEN
    if not ENV_REFRESH_TOKEN or not CLIENT_ID or not TENANT:
        return None
    if _cached_env_token and time.time() < _cached_env_token_exp:
        return _cached_env_token

    # Confidential clients require client_secret in every token request
    client_secret = _get_client_secret()
    oauth_kwargs: Dict[str, Any] = dict(client_id=CLIENT_ID, scope=SCOPES)
    if client_secret:
        oauth_kwargs["client_secret"] = client_secret

    async with AsyncOAuth2Client(**oauth_kwargs) as cli:
        token = await cli.fetch_token(
            TOKEN_URL,
            grant_type="refresh_token",
            refresh_token=ENV_REFRESH_TOKEN,
            scope=" ".join(SCOPES),
        )
    # Rotate the refresh token if Azure AD issued a new one (#15)
    new_rt = token.get("refresh_token") or ENV_REFRESH_TOKEN
    if new_rt != ENV_REFRESH_TOKEN:
        ENV_REFRESH_TOKEN = new_rt
        try:
            from .instances import get_active
            active = get_active()
            if active.refresh_token:
                active.refresh_token = new_rt
        except Exception:
            pass
        log.info("Env refresh token rotated")
    result = {
        "access_token": token.get("access_token"),
        "refresh_token": new_rt,
        "expires_in": token.get("expires_in"),
        "id_token": token.get("id_token", ""),
    }
    _cached_env_token = result
    _cached_env_token_exp = time.time() + max(int(token.get("expires_in", 3600)) - 60, 60)
    return result


# ─────────────────────────────────────────────────────────────
# Mode 2 - per-user PKCE login (Authorization Code + PKCE)
# ─────────────────────────────────────────────────────────────

# Server-side PKCE store — fallback when session cookies are dropped
# during the Azure AD cross-origin redirect (common on localhost).
_pkce_store: Dict[str, Dict[str, Any]] = {}
_PKCE_MAX_AGE = 600  # 10 minutes


def _pkce_store_set(state: str, code_verifier: str, redirect_uri: str) -> None:
    """Store PKCE params server-side, keyed by state."""
    # Evict expired entries
    now = time.time()
    expired = [k for k, v in _pkce_store.items() if now - v["t"] > _PKCE_MAX_AGE]
    for k in expired:
        del _pkce_store[k]
    _pkce_store[state] = {"cv": code_verifier, "ru": redirect_uri, "t": now}


def _pkce_store_pop(state: str) -> Optional[Dict[str, str]]:
    """Retrieve and remove PKCE params by state. Returns None if missing/expired."""
    entry = _pkce_store.pop(state, None)
    if entry and time.time() - entry["t"] <= _PKCE_MAX_AGE:
        return {"code_verifier": entry["cv"], "redirect_uri": entry["ru"]}
    return None

def _get_client_secret() -> str:
    """Return the active instance's client_secret (empty string if none)."""
    try:
        from .instances import get_active
        return get_active().client_secret or ""
    except Exception:
        return ""


def _build_redirect_uri(request: Request) -> str:
    """Build callback URI from the incoming request (works behind proxies / Codespaces)."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.hostname
    # Normalize 127.0.0.1 → localhost so Azure AD redirect URI always matches
    if host and host.startswith("127.0.0.1"):
        host = host.replace("127.0.0.1", "localhost", 1)
    return f"{proto}://{host}/auth/callback"


@router.get("/login")
async def login(request: Request):
    """Redirect user to Azure AD authorize endpoint with PKCE (OSDU scopes)."""
    if not CLIENT_ID or not TENANT:
        return JSONResponse({"error": "AZURE_CLIENT_ID / AZURE_TENANT_ID not configured"}, status_code=500)

    # Allow PKCE login even for client_credentials instances, so users can
    # fall back to their own Microsoft account when the service-principal
    # token fails (e.g. expired secret).  The app registration just needs a
    # redirect URI configured for this to work.

    redirect_uri = _build_redirect_uri(request)
    code_verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(32)
    request.session["pkce_verifier"] = code_verifier
    request.session["pkce_state"] = state
    request.session["redirect_uri"] = redirect_uri

    # Server-side fallback (survives when session cookie is dropped)
    _pkce_store_set(state, code_verifier, redirect_uri)

    # Ensure offline_access and openid are present.
    # offline_access → Azure AD returns a refresh token (#16)
    # openid → Azure AD returns an id_token with oid/upn (required for session)
    login_scopes = list(SCOPES)
    if "offline_access" not in login_scopes:
        login_scopes.append("offline_access")
        log.warning("offline_access missing from SCOPES - added for PKCE login")
    if "openid" not in login_scopes:
        login_scopes.append("openid")
        log.warning("openid missing from SCOPES - added for PKCE login")

    client_secret = _get_client_secret()
    oauth_kwargs: Dict[str, Any] = dict(
        client_id=CLIENT_ID,
        scope=" ".join(login_scopes),
        redirect_uri=redirect_uri,
        code_challenge_method="S256",
    )
    if client_secret:
        oauth_kwargs["client_secret"] = client_secret

    async with AsyncOAuth2Client(**oauth_kwargs) as cli:
        url, _state = cli.create_authorization_url(
            AUTHORIZE_URL,
            state=state,
            code_verifier=code_verifier,
        )
    return RedirectResponse(url)


@router.get("/auth/callback")
async def auth_callback(request: Request):
    """Exchange authorization code for tokens (OSDU PKCE flow)."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code:
        return JSONResponse({"error": "Missing authorization code"}, status_code=400)

    expected_state = request.session.get("pkce_state")
    if state != expected_state:
        # Fallback: session cookie may have been dropped during the cross-
        # origin redirect (common on http://localhost).  Try server-side store.
        ss = _pkce_store_pop(state) if state else None
        if ss:
            log.info("PKCE state recovered from server-side store (session cookie lost)")
            code_verifier = ss["code_verifier"]
            redirect_uri = ss["redirect_uri"]
        else:
            log.warning("State mismatch: received=%s expected=%s session_keys=%s",
                        (state or "")[:12], (expected_state or "")[:12],
                        list(request.session.keys()))
            return JSONResponse({"error": "State mismatch - possible CSRF"}, status_code=400)
    else:
        # Normal path — session cookie survived
        _pkce_store_pop(state)  # clean up server-side entry
        code_verifier = request.session.get("pkce_verifier", "")
        redirect_uri = request.session.get("redirect_uri", _build_redirect_uri(request))

    # Confidential clients (those with a client_secret) require it in the
    # token exchange - otherwise Azure AD returns AADSTS7000218.
    client_secret = _get_client_secret()
    oauth_kwargs: Dict[str, Any] = dict(
        client_id=CLIENT_ID,
        scope=" ".join(SCOPES),
        redirect_uri=redirect_uri,
        code_challenge_method="S256",
    )
    if client_secret:
        oauth_kwargs["client_secret"] = client_secret

    async with AsyncOAuth2Client(**oauth_kwargs) as cli:
        try:
            token = await cli.fetch_token(
                TOKEN_URL,
                code=code,
                code_verifier=code_verifier,
            )
        except Exception as exc:
            log.error("PKCE token exchange failed: %s", exc)
            return JSONResponse({"error": f"Token exchange failed: {exc}"}, status_code=502)

    # Clean up PKCE state
    request.session.pop("pkce_verifier", None)
    request.session.pop("pkce_state", None)
    request.session.pop("redirect_uri", None)

    # ── Extract identity from token response ──────────────────────────
    rt = token.get("refresh_token", "")
    at = token.get("access_token", "")
    exp = time.time() + int(token.get("expires_in", 3600)) - 60

    # Try id_token first (preferred, returned when scope includes 'openid')
    id_token_raw = token.get("id_token", "")
    claims = decode_id_token_payload(id_token_raw) if id_token_raw else {}
    oid = claims.get("oid", "")
    upn = claims.get("preferred_username") or claims.get("upn") or claims.get("email", "")

    if not oid:
        # Fallback: Azure AD access tokens are also JWTs containing oid/upn.
        # This covers cases where the token endpoint omits id_token
        # (e.g. .default scope, certain confidential-client configurations).
        at_claims = decode_id_token_payload(at) if at else {}
        oid = at_claims.get("oid", "")
        upn = upn or at_claims.get("preferred_username") or at_claims.get("upn") or at_claims.get("email", "")
        if not oid:
            log.warning("PKCE callback: no oid found in id_token or access_token")

    # ── Persist session & tokens ──────────────────────────────────────
    from .instances import get_active_name
    inst_name = get_active_name()
    request.session["oid"] = oid
    request.session["instance_name"] = inst_name

    # Tokens stored server-side only (encrypted in SQLite, AT cached in-memory)
    if oid and at:
        _ts_set_cached_at(oid, inst_name, at, exp)
    if oid and rt:
        _ts_upsert(oid, inst_name, rt, upn)
        log.info("PKCE login OK: oid=%s… inst=%s (AT + RT)", oid[:8], inst_name)
    elif oid and at:
        log.info("PKCE login OK: oid=%s… inst=%s (AT only)", oid[:8], inst_name)
    else:
        log.warning("PKCE login: no oid - session will not authenticate")
    response = RedirectResponse("/")
    response.set_cookie("ores_user", "1", max_age=30 * 24 * 3600,
                        samesite="lax", httponly=False)
    return response


@router.get("/logout")
async def logout(request: Request):
    """Clear session, remove persisted token, and redirect to home."""
    oid = request.session.get("oid", "")
    instance_name = request.session.get("instance_name", "")
    if oid:
        _ts_delete(oid, instance_name)
    request.session.clear()
    response = RedirectResponse("/login-page")
    response.delete_cookie("ores_user")
    return response


async def tokens_from_session(request: Request) -> Optional[Dict[str, Any]]:
    """Return access token using server-side stores only.

    The session cookie contains **only** the user's ``oid`` and the
    ``instance_name`` they logged in against.  All sensitive tokens live
    server-side (encrypted in SQLite + in-memory AT cache).

    Recovery order:
      1. In-memory AT cache still valid → return immediately.
      2. SQLite RT → mint a new AT, cache it, return.
      3. Nothing available → return None (caller redirects to /login).
    """
    oid = request.session.get("oid", "")
    instance_name = request.session.get("instance_name", "")
    if not oid:
        return None

    # 1. In-memory AT cache
    cached_at = _ts_get_cached_at(oid, instance_name)
    if cached_at:
        return {"access_token": cached_at}

    # 2. Fetch RT from SQLite
    rt = _ts_fetch(oid, instance_name)
    if not rt:
        log.debug("No stored RT for oid=%s inst=%s", oid[:8], instance_name)
        return None

    # Resolve instance config for the correct token endpoint (#5)
    try:
        from .instances import get_instances, get_active
        instances = get_instances()
        inst = instances.get(instance_name) or get_active()
        client_id = inst.client_id
        client_secret = inst.client_secret or ""
        scopes = (inst.scope or "openid offline_access").split()
        token_url = inst.token_url
    except Exception:
        client_id = CLIENT_ID
        client_secret = _get_client_secret()
        scopes = SCOPES
        token_url = TOKEN_URL

    try:
        oauth_kwargs: Dict[str, Any] = dict(client_id=client_id, scope=scopes)
        if client_secret:
            oauth_kwargs["client_secret"] = client_secret
        async with AsyncOAuth2Client(**oauth_kwargs) as cli:
            token = await cli.fetch_token(
                token_url,
                grant_type="refresh_token",
                refresh_token=rt,
                scope=" ".join(scopes),
            )
        new_rt = token.get("refresh_token") or rt
        new_at = token.get("access_token", "")
        new_exp = time.time() + int(token.get("expires_in", 3600)) - 60

        # Update server-side stores
        _ts_set_cached_at(oid, instance_name, new_at, new_exp)
        if new_rt != rt:
            _ts_upsert(oid, instance_name, new_rt)

        log.info("Minted AT from stored RT for oid=%s inst=%s", oid[:8], instance_name)
        return {"access_token": new_at}
    except Exception as e:
        log.warning("Session refresh failed: %s - redirecting to login", e)
        return None


# ─────────────────────────────────────────────────────────────
# SMDA token  (separate audience - uses session SMDA refresh token)
# ─────────────────────────────────────────────────────────────

async def smda_access_token(request: Request) -> Optional[str]:
    """Return SMDA access token.

    Strategy order:
      1. Per-user cache (keyed by session OID) still valid → return immediately.
      2. Azure CLI (`az account get-access-token`) → works locally with `az login`.
      3. User's session refresh token exchanged for SMDA scope → works on Radix
         when user has done a PKCE login.
      4. Shared env refresh token exchanged for SMDA scope → works on Radix
         when ENV_REFRESH_TOKEN is set (no per-user login needed).
      5. Client credentials grant (app-level permission on SMDA) → works when
         the app registration has application-level access to the SMDA API.

    Returns None if all strategies fail.
    """
    if not SMDA_CLIENT_ID:
        log.debug("SMDA_CLIENT_ID not configured")
        return None

    # 1. Check per-user cache
    oid = request.session.get("oid", "") if hasattr(request, "session") else ""
    cache_key = oid or "__global__"
    cached = _smda_token_cache.get(cache_key)
    if cached and time.time() < cached[1]:
        return cached[0]

    # 2. Try az CLI (works locally)
    result = await _smda_token_from_az_cli()
    if result:
        _smda_token_cache[cache_key] = (result["access_token"], result["exp"])
        return result["access_token"]

    # 3. Fallback: mint SMDA token from user's session refresh token
    result = await _smda_token_from_session(request)
    if result:
        _smda_token_cache[cache_key] = (result["access_token"], result["exp"])
        return result["access_token"]

    # 4. Fallback: dedicated SMDA refresh token (from az CLI session)
    result = await _smda_token_from_dedicated_rt()
    if result:
        _smda_token_cache["__global__"] = (result["access_token"], result["exp"])
        return result["access_token"]

    # 5. Fallback: use shared ENV_REFRESH_TOKEN to get SMDA token
    result = await _smda_token_from_env_rt()
    if result:
        _smda_token_cache["__global__"] = (result["access_token"], result["exp"])
        return result["access_token"]

    # 6. Fallback: client_credentials grant (app-level permission)
    result = await _smda_token_from_client_credentials()
    if result:
        _smda_token_cache["__global__"] = (result["access_token"], result["exp"])
        return result["access_token"]

    log.debug("No SMDA token available (all strategies failed)")
    return None


# Per-user SMDA token cache: {cache_key: (access_token, expiry_timestamp)}
_smda_token_cache: Dict[str, tuple] = {}


async def _smda_token_from_session(request: Request) -> Optional[Dict[str, Any]]:
    """Mint SMDA-scoped token using the user's session refresh token.

    Uses the same refresh token from PKCE login but requests SMDA_SCOPE
    instead of the OSDU scope.  Requires SMDA_SCOPE to be configured and
    the app registration to have consent for the SMDA API.
    """
    smda_scope = SMDA_SCOPE or f"{SMDA_CLIENT_ID}/user_impersonation openid offline_access"

    oid = request.session.get("oid", "") if hasattr(request, "session") else ""
    instance_name = request.session.get("instance_name", "") if hasattr(request, "session") else ""
    if not oid:
        log.debug("SMDA session fallback: no user session (oid)")
        return None

    # Get the user's refresh token from the token store
    rt = _ts_fetch(oid, instance_name)
    if not rt:
        log.debug("SMDA session fallback: no stored RT for oid=%s", oid[:8])
        return None

    # Resolve instance config for client_id/secret/token_url
    try:
        from .instances import get_instances, get_active
        instances = get_instances()
        inst = instances.get(instance_name) or get_active()
        client_id = inst.client_id
        client_secret = inst.client_secret or ""
        token_url = inst.token_url
    except Exception:
        client_id = CLIENT_ID
        client_secret = _get_client_secret()
        token_url = TOKEN_URL

    try:
        import httpx
        data: Dict[str, str] = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": rt,
            "scope": smda_scope,
        }
        if client_secret:
            data["client_secret"] = client_secret

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(token_url, data=data)
            if r.status_code >= 400:
                log.warning("SMDA session token failed (%d): %s", r.status_code, r.text[:200])
                return None
            body = r.json()

        at = body.get("access_token", "")
        if not at:
            return None

        # Rotate refresh token if a new one was issued
        new_rt = body.get("refresh_token")
        if new_rt and new_rt != rt:
            _ts_upsert(oid, instance_name, new_rt)

        exp = time.time() + max(int(body.get("expires_in", 3600)) - 60, 60)
        log.info("Got SMDA token via session RT for oid=%s", oid[:8])
        return {"access_token": at, "exp": exp}
    except Exception as e:
        log.warning("SMDA session token error: %s", e)
        return None


async def _smda_token_from_az_cli() -> Optional[Dict[str, Any]]:
    """Get SMDA-scoped token via Azure CLI (`az account get-access-token`).

    Azure CLI uses Microsoft's first-party app registration (04b07795-...)
    which has broad consent in most enterprise tenants.  This is the
    "standard token" approach.
    """
    import asyncio
    import json as _json
    try:
        proc = await asyncio.create_subprocess_exec(
            "az", "account", "get-access-token",
            "--resource", SMDA_CLIENT_ID,
            "-o", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()[:200]
            log.debug("az CLI SMDA token failed (rc=%d): %s", proc.returncode, err)
            return None
        data = _json.loads(stdout)
        at = data.get("accessToken", "")
        if not at:
            return None
        exp_ts = data.get("expires_on", 0)
        if isinstance(exp_ts, str):
            exp_ts = int(exp_ts)
        exp = exp_ts - 60 if exp_ts > 0 else time.time() + 3000
        log.info("Got SMDA token via az CLI (expires %s)", data.get("expiresOn", "?"))
        return {"access_token": at, "exp": exp}
    except FileNotFoundError:
        log.debug("az CLI not found - skipping az token strategy")
    except asyncio.TimeoutError:
        log.warning("az CLI timed out getting SMDA token")
    except Exception as e:
        log.debug("az CLI SMDA token error: %s", e)
    return None


# Azure CLI public client_id (pre-consented for most APIs, no secret needed)
_AZ_CLI_CLIENT_ID = "04b07795-ee78-4fb6-8785-8d1300675261"


async def _smda_token_from_dedicated_rt() -> Optional[Dict[str, Any]]:
    """Mint SMDA token using a dedicated SMDA_REFRESH_TOKEN.

    This RT should be obtained locally from 'az login' session and stored
    as a Radix secret.  It uses the Azure CLI public client_id (no secret)
    because the ores-dev app lacks consent for the SMDA API.

    The RT auto-rotates (new one returned in response) - we update the
    module-level variable so subsequent calls use the fresh RT.
    """
    global SMDA_REFRESH_TOKEN
    if not SMDA_REFRESH_TOKEN or not SMDA_CLIENT_ID:
        return None

    # Azure CLI uses the organization's tenant for token exchange
    tenant = TENANT or "<your-tenant-id>"  # set AZURE_TENANT_ID
    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    smda_scope = f"{SMDA_CLIENT_ID}/.default offline_access openid"

    try:
        import httpx
        data: Dict[str, str] = {
            "grant_type": "refresh_token",
            "client_id": _AZ_CLI_CLIENT_ID,
            "refresh_token": SMDA_REFRESH_TOKEN,
            "scope": smda_scope,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(token_url, data=data)
            if r.status_code >= 400:
                log.warning("SMDA dedicated RT failed (%d): %s", r.status_code, r.text[:200])
                return None
            body = r.json()

        at = body.get("access_token", "")
        if not at:
            return None

        # Rotate the RT in memory (lasts until pod restart)
        new_rt = body.get("refresh_token")
        if new_rt:
            SMDA_REFRESH_TOKEN = new_rt

        exp = time.time() + max(int(body.get("expires_in", 3600)) - 60, 60)
        log.info("Got SMDA token via dedicated SMDA_REFRESH_TOKEN")
        return {"access_token": at, "exp": exp}
    except Exception as e:
        log.warning("SMDA dedicated RT error: %s", e)
        return None


async def _smda_token_from_env_rt() -> Optional[Dict[str, Any]]:
    """Mint SMDA-scoped token using the shared ENV_REFRESH_TOKEN.

    This works on Radix when no per-user PKCE login has occurred but a
    shared refresh token is configured (env_token mode).  Exchanges the
    shared RT for an SMDA-scoped access token.
    """
    if not ENV_REFRESH_TOKEN or not CLIENT_ID or not TENANT:
        log.debug("SMDA env-RT strategy: no ENV_REFRESH_TOKEN or CLIENT_ID")
        return None

    smda_scope = SMDA_SCOPE or f"{SMDA_CLIENT_ID}/.default"
    client_secret = _get_client_secret()

    try:
        import httpx
        data: Dict[str, str] = {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": ENV_REFRESH_TOKEN,
            "scope": smda_scope,
        }
        if client_secret:
            data["client_secret"] = client_secret

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(TOKEN_URL, data=data)
            if r.status_code >= 400:
                log.debug("SMDA env-RT token failed (%d): %s", r.status_code, r.text[:200])
                return None
            body = r.json()

        at = body.get("access_token", "")
        if not at:
            return None

        exp = time.time() + max(int(body.get("expires_in", 3600)) - 60, 60)
        log.info("Got SMDA token via shared env refresh token")
        return {"access_token": at, "exp": exp}
    except Exception as e:
        log.debug("SMDA env-RT token error: %s", e)
        return None


async def _smda_token_from_client_credentials() -> Optional[Dict[str, Any]]:
    """Mint SMDA token using client_credentials grant (app-level permission).

    This requires the app registration (CLIENT_ID) to have an application-level
    permission on the SMDA API resource.  Uses client_id + client_secret to
    obtain a token with scope '{SMDA_CLIENT_ID}/.default'.
    """
    client_secret = _get_client_secret()
    if not client_secret or not CLIENT_ID or not TENANT:
        log.debug("SMDA client_credentials: missing client_secret/CLIENT_ID/TENANT")
        return None

    smda_scope = f"{SMDA_CLIENT_ID}/.default"

    try:
        import httpx
        data: Dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": client_secret,
            "scope": smda_scope,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(TOKEN_URL, data=data)
            if r.status_code >= 400:
                log.debug("SMDA client_credentials failed (%d): %s", r.status_code, r.text[:200])
                return None
            body = r.json()

        at = body.get("access_token", "")
        if not at:
            return None

        exp = time.time() + max(int(body.get("expires_in", 3600)) - 60, 60)
        log.info("Got SMDA token via client_credentials grant")
        return {"access_token": at, "exp": exp}
    except Exception as e:
        log.debug("SMDA client_credentials error: %s", e)
        return None


# ─────────────────────────────────────────────────────────────
# Diagnostics endpoint
# ─────────────────────────────────────────────────────────────
@router.get("/auth")
async def auth_info(request: Request):
    logged_in = bool(request.session.get("oid")) if hasattr(request, "session") else False
    oid = request.session.get("oid", "") if hasattr(request, "session") else ""
    inst = request.session.get("instance_name", "") if hasattr(request, "session") else ""
    has_cached_at = False
    if oid and inst:
        has_cached_at = _ts_get_cached_at(oid, inst) is not None
    return {
        "azure_tenant": TENANT[:8] + "..." if TENANT else "",
        "client_id": CLIENT_ID[:8] + "..." if CLIENT_ID else "",
        "scopes": SCOPES,
        "mode": AUTH_MODE,
        "env_token_available": bool(ENV_REFRESH_TOKEN),
        "smda_api_id": SMDA_CLIENT_ID[:8] + "..." if SMDA_CLIENT_ID else "",
        "session_logged_in": logged_in,
        "session_oid": oid[:8] + "…" if oid else "",
        "session_instance": inst,
        "has_cached_at": has_cached_at,
        "session_keys": sorted(request.session.keys()) if hasattr(request, "session") else [],
    }
