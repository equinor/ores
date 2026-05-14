# ORES Authentication — Internal Developer Reference

> **Not exposed** — this file sits at the repo root, not in `md/`, so it is
> not served via `/howto`. It documents the auth implementation, pitfalls
> discovered during development, and guidance for future maintainers.
>
> For the user/admin auth guide see [md/Readme.md](md/Readme.md#authentication--sessions).

---

## Architecture overview

ORES authenticates against **Azure AD (Entra ID)** using the Microsoft identity
platform v2.0 endpoints. The system supports multiple OSDU instances, each
with its own tenant, client registration, and token strategy.

### Key files

| File | Role |
|------|------|
| `app/auth.py` | All auth routes (`/login`, `/auth/callback`, `/logout`, `/auth`), env-token minting, PKCE flow, SMDA token |
| `app/instances.py` | `OsduInstance` dataclass, multi-instance registry, `_apply_instance()` which pushes config to module globals |
| `app/main.py` | Auth middleware `inject_access_token` — resolves tokens with fallback chain |
| `app/tokenstore.py` | Fernet-encrypted SQLite store for per-user refresh tokens, in-memory AT cache |
| `k8s/secret.yaml.template` | Template for instance secrets with inline documentation |
| `k8s/configmap.yaml` | Non-secret instance config (hostnames, partitions, auth_mode flags) |
| `radixconfig.yaml` | Radix deployment config — env vars inline, secrets in Radix Console |

---

## Auth modes

Four modes, determined per-instance:

| Mode | How it works | When to use |
|------|-------------|-------------|
| `per_user_pkce` | Each user authenticates individually via OAuth2 Authorization Code + PKCE. No shared token. | **Primary mode for ADME.** Per-user audit trail, permissions, and token isolation. |
| `refresh_token` (env_token) | Shared refresh token from env var, auto-minted at startup. All visitors share one identity. | Quick demos, dev environments where individual identity doesn't matter. |
| `client_credentials` | Service principal — `CLIENT_ID` + `CLIENT_SECRET` → app-level token. No user identity. | Service-to-service, test environments (e.g. preship). |
| `az_cli` | `az account get-access-token --resource <audience>`. Uses Microsoft's first-party app. | SMDA only — separate audience, Equinor tenant-wide consent. |

### Auto-detection logic (`instances.py`)

```
explicit AUTH_MODE env var  →  use it directly
REFRESH_TOKEN + CLIENT_SECRET  →  refresh_token+client_credentials
REFRESH_TOKEN only             →  refresh_token
CLIENT_SECRET only             →  client_credentials
neither                        →  none (PKCE fallback)
```

**Important:** `AUTH_MODE=per_user_pkce` can be set **even when `CLIENT_SECRET` is present**.
This is the correct configuration for confidential-client PKCE on ADME — the secret is
needed for the PKCE exchange itself, but no shared instance-level token is minted.

---

## Middleware priority chain (`main.py`)

```
0. Per-user session (PKCE)
     ↓ only if session exists AND session.instance_name == active instance
1. Instance token (get_access_token → refresh_token → client_credentials)
2. Env token (top-level REFRESH_TOKEN, legacy)
3. Redirect to /login-page (browser) or 401 (API)
```

### Instance-switch session guard

After an instance switch (e.g. eqndev → preship), any existing per-user session
was created for the **old** instance's tenant and scope. The middleware checks
`session.instance_name == active_instance_name` and **skips** the session token
if they don't match, falling through to the new instance's own credentials.

Without this guard, the old session token (wrong tenant/scope) would be used,
causing 401s or data from the wrong OSDU backend.

---

## The PKCE flow in detail

### `/login` → Azure AD

1. Generate `code_verifier` (64-byte URL-safe random) and `state` (32-byte).
2. Store both in the session (server-side, signed cookie).
3. Build authorize URL with `code_challenge_method=S256`.
4. **If `CLIENT_SECRET` exists** → include it in the `AsyncOAuth2Client` kwargs.
   This is required for confidential clients — Azure AD validates the secret
   at every step.
5. Ensure `offline_access` and `openid` are in the scope list:
   - `offline_access` → Azure AD returns a refresh token
   - `openid` → Azure AD returns an `id_token` with `oid`/`upn`
6. Redirect user to Azure AD.

### `/auth/callback` ← Azure AD

1. Validate `state` against session (CSRF protection).
2. Exchange authorization `code` for tokens via `TOKEN_URL`.
   - **Must include `client_secret`** for confidential clients (AADSTS7000218).
   - Must include `code_verifier` for PKCE.
3. Extract user identity:
   - **Primary:** Parse `id_token` JWT → extract `oid` (Object ID) and `preferred_username`.
   - **Fallback:** If no `id_token` (some configs don't return one), parse the `access_token`
     JWT — Azure AD access tokens are also JWTs containing `oid`/`upn`.
4. Persist tokens server-side:
   - `tokenstore.set_cached_at(oid, instance, AT, expiry)` — in-memory only
   - `tokenstore.upsert(oid, instance, RT, upn)` — encrypted in SQLite
5. Set session: `oid` + `instance_name` only (no tokens in cookie).
6. Set `ores_user` marker cookie (httponly=False) for nav-bar JS green/grey dot.
7. Redirect to `/`.

### Token recovery (`tokens_from_session`)

On subsequent requests, the middleware calls `tokens_from_session(request)`:

```
1. Read oid + instance_name from session cookie
2. Check in-memory AT cache → return if valid
3. Fetch encrypted RT from SQLite → decrypt
4. Mint new AT from RT via token endpoint
5. Cache new AT, rotate RT if Azure AD issued a new one
6. Return AT
```

If all steps fail → return `None` → middleware falls through to instance token or redirect.

---

## Scopes — the ADME pitfall

### The problem

There are **two different scopes** for OSDU on Azure:

| Scope | Works for | Does NOT work for |
|-------|-----------|-------------------|
| `https://energy.azure.com/.default` | `client_credentials`, shared `refresh_token` | **Per-user PKCE on ADME** |
| `bd0c9d90-89ad-4bb3-97bc-d787b9f69cdc/.default` | Per-user delegated access (PKCE) on ADME | App-level grants without admin consent |

The old `energy.azure.com` scope is an **application-level** scope. When used with
per-user PKCE, Azure AD returns a token that the ADME API rejects because the audience
doesn't match the ADME resource app.

### The solution

For `per_user_pkce` on ADME, use:
```
bd0c9d90-89ad-4bb3-97bc-d787b9f69cdc/.default openid offline_access
```

This targets the **ADME resource application** directly. The `access_as_user` delegated
permission must be granted (admin consent) in the Enterprise Application blade.

### Where it's configured

- `k8s/secret.yaml` → `INSTANCE_EQNDEV_SCOPE`
- `radixconfig.yaml` → Radix Console secret `INSTANCE_EQNDEV_SCOPE`

The old scope is still valid for shared-token instances (eqndeva) that use
`client_credentials` or `refresh_token` with app-level grants.

---

## Confidential client — AADSTS7000218

### The problem

When an app registration has a `CLIENT_SECRET`, Azure AD treats it as a
**confidential client**. Confidential clients must include the secret in
**every** OAuth2 request — not just `client_credentials` grants:

- `/authorize` (via the authlib client constructor)
- `/token` (code exchange)
- `/token` (refresh_token grant)

If the secret is omitted from any of these, Azure AD returns:

```
AADSTS7000218: The request body must contain the following parameter:
'client_assertion' or 'client_secret'.
```

### The solution

`_get_client_secret()` in `auth.py` fetches the active instance's secret.
Every place that creates an `AsyncOAuth2Client` checks for it:

```python
client_secret = _get_client_secret()
oauth_kwargs = dict(client_id=CLIENT_ID, scope=..., ...)
if client_secret:
    oauth_kwargs["client_secret"] = client_secret
```

This pattern appears in:
- `tokens_from_env()` — shared refresh_token mint
- `/login` — PKCE authorize URL construction
- `/auth/callback` — code exchange
- `OsduInstance._refresh_token_flow()` — instance-level RT refresh

### Why this is subtle

Public clients (no secret) work fine without it. When you **add** a secret to an
existing app registration (e.g. to enable `client_credentials` as a backup), all
existing PKCE flows break unless you also wire the secret into every token request.

---

## Token rotation

Azure AD may return a **new refresh token** alongside every access token.
Both the env-token path and the per-user PKCE path handle this:

- **env_token** (`auth.py` ~line 82): Compares new RT to old, updates
  `ENV_REFRESH_TOKEN` and the active instance's `.refresh_token` field.
- **per-user** (`tokenstore.py`): `tokens_from_session()` checks if the
  minted RT differs from the stored one and calls `upsert()` to persist it.
- **instance-level** (`instances.py`): `_refresh_token_flow()` updates
  `self.refresh_token` when Azure AD rotates.

**Caveat:** If a pod restarts, the in-memory rotated token is lost. The original
token from `secret.yaml` / Radix Console is used again. If Azure AD has already
invalidated the old token, the RT flow fails and falls through to PKCE login.
This is by design — re-run `mint_refresh_token.py` to mint a fresh one.

---

## Instance switching internals

`set_active(name)` in `instances.py`:

1. Acquires `_switch_lock` (threading.Lock) to prevent partial updates.
2. Calls `_apply_instance(inst)` which:
   - Updates `osdu.py` globals: `OSDU_BASE_URL`, `DATA_PARTITION_ID`, `SSL_VERIFY`,
     legal tags, owners, viewers, countries.
   - **Closes the shared httpx client** — SSL verify is a client-level setting,
     so switching from `ssl_verify=True` to `False` (e.g. preship) requires a new client.
   - Clears the TTL cache (`cache_clear()`) — stale RDDMS/search results from the
     previous instance must not bleed through.
   - Switches the PG connection pool (`notify_instance_changed()`).
   - Updates `auth.py` globals: `TENANT`, `CLIENT_ID`, `SCOPES`, `TOKEN_URL`,
     `ENV_REFRESH_TOKEN`, `AUTH_MODE`.
   - **Clears the cached env token** — prevents reuse of a token from the previous instance.

---

## App registration requirements

### Azure Portal → App registrations

| Setting | Value | Why |
|---------|-------|-----|
| **Redirect URIs (Web)** | See table below | Must match every environment |
| **Supported account types** | Single tenant (Equinor directory only) | Restricts to org |
| **Allow public client flows** | No | We always supply `CLIENT_SECRET` (confidential) |
| **API permissions (delegated)** | `bd0c9d90-...` → `access_as_user` | ADME resource app |
| **Client secret** | Create one, store in secret.yaml / Radix | Required for confidential PKCE |

### Redirect URIs

| Environment | URI |
|-------------|-----|
| Local dev | `http://localhost:8000/auth/callback` |
| Token minting CLI | `http://localhost:8400/callback` |
| Radix dev | `https://web-ores-dev.c3.radix.equinor.com/auth/callback` |
| Radix prod | `https://web-ores.c3.radix.equinor.com/auth/callback` |

The callback handler builds `redirect_uri` dynamically from `x-forwarded-proto`
and `x-forwarded-host` headers, so it works behind Radix's ingress automatically.
But the URI must still be **registered** in Azure Portal or the authorize request fails.

### Admin consent

For per-user PKCE with the ADME scope, an Azure AD admin must grant consent
for the `access_as_user` permission on the ADME resource app:

**Azure Portal → Enterprise applications → \<app\> → Permissions → Grant admin consent**

Without this, users see a "needs admin approval" error during sign-in.

---

## Radix deployment notes

### Secrets management

Secrets are entered via **Radix Console → ores → \<env\> → Secrets** and injected
as env vars at runtime. They are listed (but not valued) in `radixconfig.yaml`:

```yaml
secrets:
  - SECRET_KEY
  - INSTANCE_EQNDEV_TENANT_ID
  - INSTANCE_EQNDEV_CLIENT_ID
  - INSTANCE_EQNDEV_CLIENT_SECRET
  - INSTANCE_EQNDEV_SCOPE
  - INSTANCE_PRESHIP_TENANT_ID
  - INSTANCE_PRESHIP_CLIENT_ID
  - INSTANCE_PRESHIP_CLIENT_SECRET
  - INSTANCE_PRESHIP_SCOPE
```

Non-secret config (hostnames, partitions, auth_mode) is inline in `radixconfig.yaml`
under `environmentConfig.[].variables`.

### Health probes

Both readiness and liveness probe `/login-page` — a lightweight HTML page that
doesn't require auth and doesn't hit OSDU APIs.

### SECRET_KEY

Must be identical across all replicas and pod restarts. It is used to:
1. Sign Starlette session cookies (HMAC)
2. Derive the Fernet key for encrypting refresh tokens in SQLite

If it changes, all existing sessions and stored refresh tokens become invalid
(users must re-login).

Generate: `python -c "import secrets; print(secrets.token_hex(32))"`

---

## SMDA authentication

SMDA (stratigraphic column service) uses a **separate audience** from OSDU.
The token is obtained via Azure CLI:

```bash
az account get-access-token --resource <SMDA_CLIENT_ID>
```

This uses Microsoft's first-party app registration (`04b07795-...`) which has
broad consent in the Equinor tenant. The user must have run `az login`.

The `smda_access_token()` function in `auth.py` shells out to `az` asynchronously,
caches the result, and returns `None` if `az` is unavailable or not logged in.

Relevant env vars:
- `SMDA_CLIENT_ID` — the SMDA API resource app ID (audience)
- `SMDA_SCOPE` — optional scope override
- `SMDA_API_KEY` — optional API key for SMDA endpoints

---

## Diagnostics

`GET /auth` returns a JSON object with current auth state:

```json
{
  "azure_tenant": "3aa4a235...",
  "client_id": "21b442a9...",
  "scopes": ["bd0c9d90-.../.default", "openid", "offline_access"],
  "mode": "per_user_pkce",
  "env_token_available": false,
  "smda_api_id": "",
  "session_logged_in": true,
  "session_oid": "a1b2c3d4…",
  "session_instance": "eqndev",
  "has_cached_at": true,
  "session_keys": ["instance_name", "oid"]
}
```

This endpoint is useful for debugging auth issues without exposing tokens.

---

## Common pitfalls — summary

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| Wrong scope for PKCE | ADME API rejects token (401/403) | Use `bd0c9d90-.../.default`, not `energy.azure.com/.default` |
| Missing `client_secret` in PKCE | `AADSTS7000218` | Ensure `_get_client_secret()` returns value in all OAuth2 calls |
| Missing `offline_access` in scope | No refresh token returned | Code auto-appends it, but check SCOPE env var |
| Missing `openid` in scope | No `id_token`, no `oid` | Code auto-appends it; fallback: parse AT JWT |
| Session from wrong instance | 401 after instance switch | Middleware checks `session.instance_name == active`; skips if mismatch |
| Rotated RT + pod restart | Old RT in secret.yaml fails | Re-run `mint_refresh_token.py` |
| No admin consent for ADME | "Needs admin approval" dialog | Grant consent in Enterprise Applications blade |
| `SECRET_KEY` changed | All sessions + stored RTs invalidated | Use a stable key, same across replicas |
| Missing redirect URI | Azure AD error during authorize | Register all callback URIs in App Registration |
| SQLite + multi-replica | Lock contention / corruption | Use `replicas: 1` or replace with PG/Redis |
