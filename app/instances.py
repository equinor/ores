"""
app/instances.py - Multi-instance OSDU configuration.

Every instance is defined by env vars with the pattern INSTANCE_<NAME>_<KEY>.
There is no special "default" instance - eqndev (or whatever DEFAULT_INSTANCE
points to) is loaded with the same INSTANCE_<NAME>_* scanner as every other.

Token strategies (tried in order of preference):
  1. refresh_token  → uses stored REFRESH_TOKEN (user-level, preferred)
  2. client_credentials → uses CLIENT_ID + CLIENT_SECRET (service-level fallback)

Store *at least one of* REFRESH_TOKEN or CLIENT_SECRET per instance.
"""
from __future__ import annotations

import os
import threading
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict

import httpx

log = logging.getLogger("rddms-admin.instances")

# Lock for instance switching - serialises _apply_instance to prevent
# partially-updated module globals during concurrent requests (#8).
_switch_lock = threading.Lock()


@dataclass
class OsduInstance:
    """Configuration for a single OSDU instance."""
    name: str
    hostname: str = ""                      # e.g. equinorswedev.energy.azure.com
    data_partition_id: str = ""             # e.g. dev, opendes
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""                 # only for client_credentials flow
    scope: str = ""                         # e.g. "<client_id>/.default openid ..."
    authority: str = "osdu"                 # schema authority prefix
    schema_source: str = "wks"
    default_legal_tag: str = ""
    default_owners: str = ""
    default_viewers: str = ""
    default_countries: str = "NO"
    refresh_token: str = ""                 # shared refresh token (if any)
    auth_mode: str = "refresh_token"        # refresh_token | client_credentials | per_user_pkce | az_cli
    graphql_pg_conn_string: str = ""        # per-instance RDDMS PG conn (blank → REST fallback)
    ssl_verify: bool = True                 # False for test/pre-ship envs with untrusted certs

    # --- runtime token cache ---
    _cached_token: str = field(default="", repr=False)
    _cached_exp: float = field(default=0.0, repr=False)

    @property
    def base_url(self) -> str:
        return self.hostname

    @property
    def token_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"

    def _partition_suffix(self) -> str:
        return f"{self.data_partition_id}.dataservices.energy" if self.data_partition_id else ""

    async def get_access_token(self) -> Optional[str]:
        """Mint or return cached access_token for this instance.

        Tries refresh_token first, then client_credentials.
        Returns None for per_user_pkce instances - those rely on
        individual user sessions, not a shared instance-level token.
        """
        # per_user_pkce instances never mint an instance-level token;
        # users authenticate individually via the PKCE login flow.
        if self.auth_mode == "per_user_pkce":
            return None

        if self._cached_token and time.time() < self._cached_exp:
            return self._cached_token

        token = None

        # 1. Prefer refresh_token (user-level access)
        if self.refresh_token:
            token = await self._refresh_token_flow()

        # 2. Fallback to client_credentials (service-principal)
        if not token and self.client_secret:
            token = await self._client_credentials()

        if token:
            self._cached_token = token["access_token"]
            self._cached_exp = time.time() + max(int(token.get("expires_in", 3600)) - 120, 60)
            return self._cached_token
        return None

    async def _client_credentials(self) -> Optional[Dict]:
        """OAuth2 client_credentials grant."""
        scope = self.scope or f"{self.client_id}/.default"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": scope,
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(self.token_url, data=data)
                if r.status_code >= 400:
                    log.warning("client_credentials failed for %s: %s %s",
                                self.name, r.status_code, r.text[:200])
                    return None
                body = r.json()
                log.info("Got client_credentials token for instance '%s' (expires_in=%s)",
                         self.name, body.get("expires_in"))
                return body
        except Exception as e:
            log.warning("client_credentials error for %s: %s", self.name, e)
            return None

    async def _refresh_token_flow(self) -> Optional[Dict]:
        """OAuth2 refresh_token grant."""
        scope_str = self.scope or f"{self.client_id}/.default openid offline_access"
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": self.refresh_token,
            "scope": scope_str,
        }
        # Confidential clients require client_secret in every token request
        if self.client_secret:
            data["client_secret"] = self.client_secret
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(self.token_url, data=data)
                if r.status_code >= 400:
                    log.warning("refresh_token failed for %s: %s %s",
                                self.name, r.status_code, r.text[:200])
                    return None
                body = r.json()
                # Update refresh token if rotated
                if body.get("refresh_token"):
                    self.refresh_token = body["refresh_token"]
                return body
        except Exception as e:
            log.warning("refresh_token error for %s: %s", self.name, e)
            return None


# ── Registry ──────────────────────────────────────────────────────────────

_instances: Dict[str, OsduInstance] = {}
_active_instance_name: str = ""


def _load_instances():
    """Build instance registry from environment variables.

    Convention:
      INSTANCE_<NAME>_HOSTNAME, INSTANCE_<NAME>_DATA_PARTITION_ID, etc.
    All instances (including eqndev) follow the same pattern.
    The active instance defaults to DEFAULT_INSTANCE env var, or 'eqndev',
    or the first instance found alphabetically.
    """
    global _active_instance_name

    # Scan for INSTANCE_<NAME>_HOSTNAME patterns
    seen: set[str] = set()
    for key in os.environ:
        if key.startswith("INSTANCE_") and key.count("_") >= 2:
            parts = key.split("_", 2)  # INSTANCE, NAME, FIELD
            seen.add(parts[1].lower())

    for inst_name in sorted(seen):
        prefix = f"INSTANCE_{inst_name.upper()}_"
        _get = lambda field, default="": os.getenv(f"{prefix}{field}", default).strip()

        hostname = _get("HOSTNAME")
        if not hostname:
            continue  # skip incomplete entries

        # Describe auth mode based on available credentials.
        # An explicit AUTH_MODE env var overrides auto-detection,
        # e.g. INSTANCE_EQNDEVP_AUTH_MODE=per_user_pkce lets the
        # instance carry a client_secret (for the PKCE exchange)
        # while still forcing individual user login.
        client_secret = _get("CLIENT_SECRET")
        refresh = _get("REFRESH_TOKEN")
        explicit_mode = _get("AUTH_MODE")
        if explicit_mode:
            mode = explicit_mode
        elif refresh and client_secret:
            mode = "refresh_token+client_credentials"
        elif refresh:
            mode = "refresh_token"
        elif client_secret:
            mode = "client_credentials"
        else:
            mode = "none"

        inst = OsduInstance(
            name=inst_name,
            hostname=hostname,
            data_partition_id=_get("DATA_PARTITION_ID", "opendes"),
            tenant_id=_get("TENANT_ID"),
            client_id=_get("CLIENT_ID"),
            client_secret=client_secret,
            scope=_get("SCOPE"),
            authority=_get("AUTHORITY", "osdu"),
            schema_source=_get("SCHEMA_SOURCE", "wks"),
            default_legal_tag=_get("DEFAULT_LEGAL_TAG"),
            default_owners=_get("DEFAULT_OWNERS"),
            default_viewers=_get("DEFAULT_VIEWERS"),
            default_countries=_get("DEFAULT_COUNTRIES", "NO"),
            refresh_token=refresh,
            auth_mode=mode,
            graphql_pg_conn_string=_get("GRAPHQL_PG_CONN_STRING"),
            ssl_verify=_get("SSL_VERIFY", "true").lower() not in ("false", "0", "no"),
        )
        _instances[inst_name] = inst
        log.info("Registered OSDU instance '%s' → %s (partition=%s, auth=%s)",
                 inst_name, hostname, inst.data_partition_id, mode)

    # ── Backward compat: create a "legacy" instance from old top-level vars
    #    if no INSTANCE_* vars were found at all (migration aid) ──
    if not _instances:
        _rt = os.getenv("REFRESH_TOKEN", "") or os.getenv("refresh_token", "")
        hostname = os.getenv("OSDU_BASE_URL", "")
        if hostname:
            log.warning("No INSTANCE_* env vars found - falling back to legacy "
                        "top-level env vars (OSDU_BASE_URL, AZURE_TENANT_ID, …). "
                        "Please migrate to INSTANCE_<NAME>_* format.")
            legacy = OsduInstance(
                name="legacy",
                hostname=hostname,
                data_partition_id=os.getenv("DATA_PARTITION_ID", "dev"),
                tenant_id=os.getenv("AZURE_TENANT_ID", ""),
                client_id=os.getenv("AZURE_CLIENT_ID", ""),
                scope=os.getenv("AZURE_SCOPE", ""),
                refresh_token=_rt,
                default_legal_tag=os.getenv("DEFAULT_LEGAL_TAG", ""),
                default_owners=os.getenv("DEFAULT_OWNERS", ""),
                default_viewers=os.getenv("DEFAULT_VIEWERS", ""),
                default_countries=os.getenv("DEFAULT_COUNTRIES", "NO"),
                auth_mode="refresh_token" if _rt else "none",
            )
            _instances["legacy"] = legacy

    # ── Choose active instance ──
    preferred = os.getenv("DEFAULT_INSTANCE", "eqndev").lower()
    if preferred in _instances:
        _active_instance_name = preferred
    elif _instances:
        _active_instance_name = sorted(_instances.keys())[0]
    else:
        log.error("No OSDU instances configured! "
                  "Set INSTANCE_<NAME>_HOSTNAME env vars (see k8s/configmap.yaml).")
        # Create a dummy so callers don't crash
        _instances["none"] = OsduInstance(name="none")
        _active_instance_name = "none"

    # Apply active instance to osdu.py + auth.py module globals
    _apply_instance(_instances[_active_instance_name])


def get_instances() -> Dict[str, OsduInstance]:
    if not _instances:
        _load_instances()
    return _instances


def get_active() -> OsduInstance:
    if not _instances:
        _load_instances()
    return _instances[_active_instance_name]


def set_active(name: str) -> OsduInstance:
    """Switch the active instance. Returns the new active instance."""
    global _active_instance_name
    with _switch_lock:
        if not _instances:
            _load_instances()
        if name not in _instances:
            raise ValueError(f"Unknown instance: {name!r}. Available: {list(_instances.keys())}")

        _active_instance_name = name
        inst = _instances[name]
        _apply_instance(inst)

    log.info("Switched active instance → '%s' (%s, partition=%s)",
             name, inst.hostname, inst.data_partition_id)
    return inst


def _apply_instance(inst: OsduInstance):
    """Push instance config into osdu.py and auth.py module-level globals."""
    # ── osdu.py ──
    import app.osdu as osdu_mod
    osdu_mod.OSDU_BASE_URL = inst.hostname
    osdu_mod.DATA_PARTITION_ID = inst.data_partition_id
    osdu_mod.SSL_VERIFY = inst.ssl_verify
    # Force-close the shared httpx client: SSL verify is a client-level
    # setting, so we need a fresh client when switching instances.
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(osdu_mod.close_shared_client())
        else:
            loop.run_until_complete(osdu_mod.close_shared_client())
    except Exception:
        pass  # Best-effort; next request will create a new client anyway
    osdu_mod.DEFAULT_LEGAL_TAG = inst.default_legal_tag or (
        f"{inst.data_partition_id}-equinor-private-default" if inst.data_partition_id else ""
    )
    pfx = inst._partition_suffix()
    osdu_mod.DEFAULT_OWNERS = [x.strip() for x in (inst.default_owners or f"data.default.owners@{pfx}").split(",") if x.strip()]
    osdu_mod.DEFAULT_VIEWERS = [x.strip() for x in (inst.default_viewers or f"data.default.viewers@{pfx}").split(",") if x.strip()]
    osdu_mod.DEFAULT_COUNTRIES = [x.strip() for x in (inst.default_countries or "NO").split(",") if x.strip()]

    # ── cache: flush stale RDDMS / search results from previous instance ──
    from .cache import cache_clear
    cache_clear()

    # ── pg_backend: switch PG pool to this instance's conn string ──
    from .pg_backend import notify_instance_changed
    notify_instance_changed(inst.graphql_pg_conn_string)

    # ── rddms_gql: re-probe native GraphQL endpoint for new instance ──
    from .rddms_gql import reset_availability_cache
    reset_availability_cache()

    # ── auth.py ──
    import app.auth as auth_mod
    # Clear stale cached env token from previous instance so it isn't
    # reused after a round-trip switch (eqndev → preship → eqndev).
    auth_mod._cached_env_token = {}
    auth_mod._cached_env_token_exp = 0.0
    auth_mod.TENANT = inst.tenant_id
    auth_mod.CLIENT_ID = inst.client_id
    scopes_str = inst.scope or "openid offline_access"
    auth_mod.SCOPES = scopes_str.split()
    auth_mod.AUTH_BASE = f"https://login.microsoftonline.com/{inst.tenant_id}/oauth2/v2.0"
    auth_mod.AUTHORIZE_URL = f"{auth_mod.AUTH_BASE}/authorize"
    auth_mod.TOKEN_URL = f"{auth_mod.AUTH_BASE}/token"
    auth_mod.ENV_REFRESH_TOKEN = inst.refresh_token or None
    # Respect explicit per_user_pkce mode even when client_secret is
    # present (needed for confidential-client PKCE exchange).
    if inst.auth_mode == "per_user_pkce":
        auth_mod.AUTH_MODE = "per_user_pkce"
    elif inst.refresh_token:
        auth_mod.AUTH_MODE = "env_token"
    elif inst.client_secret:
        auth_mod.AUTH_MODE = "client_credentials"
    else:
        auth_mod.AUTH_MODE = "per_user_pkce"


def get_active_name() -> str:
    if not _instances:
        _load_instances()
    return _active_instance_name
