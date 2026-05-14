# ORES - OSDU RDDMS Explorer & Demo Toolkit

Administrative web UI and pipeline toolkit for OSDU Reservoir Data / Decision Management.
Federated query using GraphQL, Browse dataspaces, compare Business Decisions across decision gates, manage seismic interpretations, stratigraphy columns, and ingest records.

## Quick start

```bash
git clone https://github.com/equinor/ores.git && cd ores
pip install -r requirements.txt

# Configure credentials
cp k8s/secret.yaml.template k8s/secret.yaml
# Fill in tenant ID, client ID, and either a refresh_token or client_secret

# Run
eval "$(python k8s/env_from_k8s.py)" && python -m uvicorn app.main:app --reload --port 8000
```

Open <http://127.0.0.1:8000/>

## What you need

| Requirement | Notes |
|-------------|-------|
| Python 3.11+ | 3.12 recommended |
| An OSDU instance | With Storage/Search API access |
| Azure AD credentials | Tenant ID + Client ID (+ refresh token or client secret) |

## Configuration

All config lives under `k8s/`:

| File | Purpose |
|------|---------|
| `configmap.yaml` | Hostnames, partitions, legal tags (checked in) |
| `secret.yaml` | Credentials - tenant IDs, tokens, keys (gitignored) |
| `secret.yaml.template` | Copy this to `secret.yaml` and fill in values |

Each OSDU instance is defined by `INSTANCE_<NAME>_*` env vars across both files.

### Auth modes

Each instance can use a different token strategy. The middleware tries them in order and uses the first one that succeeds:

| Priority | Strategy | Config needed | Typical use |
|----------|----------|---------------|-------------|
| 0 | **Per-user session** | Nothing — always available | User signed in via Azure AD (session cookie → server-side tokens) |
| 1 | **Instance token** | `_REFRESH_TOKEN` and/or `_CLIENT_SECRET` | Zero-click — shared across all users |
| 2 | **Env token** | Top-level `REFRESH_TOKEN` (legacy) | Single-instance setups |

PKCE login is **always available as a fallback**, even when the instance is configured with `client_credentials`. If the service principal secret expires, users can still sign in with their own Microsoft account.

**Example — two instances with different strategies:**

| Instance | Secret vars | `auth_mode` | Behaviour |
|----------|-------------|-------------|----------|
| `eqndev` | `_CLIENT_SECRET` (no RT) | `per_user_pkce` | Each user signs in individually; `CLIENT_SECRET` needed for confidential PKCE exchange |
| `preship` | `_CLIENT_SECRET` | `client_credentials` | Auto-authenticated via service principal; PKCE fallback if secret expires |

> **Confidential client:** When `CLIENT_SECRET` is set, it must be included in every OAuth2 request.
> The code handles this automatically — just make sure the secret is configured.

> **ADME scope:** Per-user PKCE requires `bd0c9d90-89ad-4bb3-97bc-d787b9f69cdc/.default openid offline_access`.
> Do **not** use `https://energy.azure.com/.default` — that old scope only works for app-level grants.

### Minting a shared refresh token (admin)

The shared refresh token enables zero-click access for every visitor. An admin mints it once and stores it in `k8s/secret.yaml`:

```bash
# Step 1 - generate a PKCE auth URL and open it in a browser
python demo/mint_refresh_token.py

# Step 2 - sign in with your Equinor account; the browser redirects to
# localhost:8400 (page won't load - that's expected). Copy the full URL
# from the address bar and exchange it:
python demo/mint_refresh_token.py --callback "http://localhost:8400/callback?code=...&state=..."
```

The script prints the refresh token. Paste it into:

```yaml
# k8s/secret.yaml
INSTANCE_EQNDEV_REFRESH_TOKEN: "<token>"
```

For Radix deployments, also set the secret in **Radix Console → ores → dev → Secrets**.

> **Prerequisite:** The app registration (`21b442a9-...`) must have
> `http://localhost:8400/callback` as a redirect URI (Authentication blade in Azure Portal).
> For the deployed site, also add `https://<radix-hostname>/auth/callback`.

### Redirect URIs (admin)

The app registration needs redirect URIs for every environment where PKCE login is used:

| Environment | Redirect URI |
|-------------|--------------|
| Local dev | `http://localhost:8000/auth/callback` (auto-detected) |
| Token minting CLI | `http://localhost:8400/callback` |
| Radix (dev) | `https://web-ores-dev.c3.radix.equinor.com/auth/callback` |
| Radix (prod) | `https://web-ores.c3.radix.equinor.com/auth/callback` |

Add these in **Azure Portal → App registrations → Authentication → Web → Redirect URIs**.

See [md/Readme.md](md/Readme.md#authentication--sessions) for the full auth & session guide.

## Pages

| Route | Purpose |
|-------|---------|
| `/` | Manage OSDU Dataspaces |
| `/keys` | Browse record types and objects + GraphQL deep search |
| `/search` | Query OSDU Search API |
| `/analyse` | Compare BDs across decision gates |
| `/add-dg` | Create new BusinessDecision, Activity & Template records |
| `/strat` | Stratigraphic column viewer |
| `/howto` | Documentation articles |
| `/graphql` | GraphiQL IDE for RESQML queries |
| `/api/graphql/query` | GraphQL endpoint (POST) |
| `/api/graphql/info` | GraphQL backend status (GET) |

## Demo pipelines

```bash
python demo/run_pipeline.py                    # default pipeline (drogon_dg2)
python demo/run_pipeline.py demo/drogon        # Drogon DG1
python demo/run_pipeline.py --list             # list available pipelines
python demo/run_pipeline.py --help             # all options
```

## Tests

```bash
python -m pytest test/ -v     # 368 tests
```

## GraphQL Deep Search

The `/keys` page includes a GraphQL panel for deep RESQML queries - object browsing,
relationship graph traversal, and array-level numerical filtering.

To enable direct PostgreSQL access (fastest, bypasses REST):

```bash
export GRAPHQL_PG_CONN_STRING="host=localhost port=5433 dbname=openetp user=tester password=tester"
```

Without this variable, queries fall back to the RDDMS REST API (always works with a valid token).

For local testing with Docker:

```bash
cd demo/epc && docker compose up -d   # PostgreSQL + OpenETPServer
./demo/epc/ingest.sh                   # Import Volve surfaces EPC
python demo/epc/test_graphql.py        # Verify all queries
```

See [md/Query.md](md/Query.md) for the full query guide.
See [md/Activity.md](md/Activity.md) for the Activity & ActivityTemplate guide.

## Docker

```bash
docker build -t ores .
docker run -p 8000:8000 --env-file <(python k8s/env_from_k8s.py | sed 's/^export //') ores
```

To enable GraphQL PostgreSQL access in Docker, add `-e GRAPHQL_PG_CONN_STRING="..."`.

## Documentation

Detailed guides live in [`md/`](md/Readme.md):

| Guide | Topic |
|-------|-------|
| [Readme](md/Readme.md) | Full architecture, auth, k8s deployment, project layout, caching |
| [BdDemo](md/BdDemo.md) | Business Decision data model & pipeline walkthrough |
| [BusinessDecision](md/BusinessDecision.md) | BD schema patterns (Parameters vs Collections) |
| [DevConcept](md/DevConcept.md) | DevelopmentConcept custom WPC schema |
| [SeisInt](md/SeisInt.md) | Seismic interpretation OSDU/RESQML model |
| [StratColumn](md/StratColumn.md) | Stratigraphic column data model |
| [CrsGuide](md/CrsGuide.md) | CRS mapping RESQML to OSDU |
| [FmuOsdu](md/FmuOsdu.md) | FMU-to-OSDU workflow |
| [Risk](md/Risk.md) | Risk register modelling |
| [Uncertainty](md/Uncertainty.md) | Uncertainty & volumes workflow |
| [Volumes](md/Volumes.md) | ReservoirEstimatedVolumes schema |
| [GeoLabelSet](md/GeoLabelSet.md) | GeoLabelSet headline KPIs |
| [Query](md/Query.md) | Querying data: REST, ETP, GraphQL & OSDU Search |
