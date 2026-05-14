# ORES - Developer Guide

> Environment setup, project layout, demo pipelines, deployment, caching, testing, and internals.
> For user/admin documentation see [Readme.md](Readme.md).
> For quick-start instructions see the [root readme](../readme.md).

---

## Environment setup

### Requirements

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | 3.12 recommended |
| FastAPI | 0.115+ | |
| uvicorn | 0.32+ | |
| httpx | latest | |
| strawberry-graphql | 0.220+ | GraphQL schema + FastAPI integration |
| asyncpg | 0.29+ | Direct PostgreSQL (optional, for GraphQL deep-search) |
| Chart.js 4 | CDN | No npm install |
| Mermaid 10 | CDN | No npm install |

### Local development

```bash
git clone https://github.com/equinor/ores.git && cd ores
pip install -r requirements.txt

# Configure credentials
cp k8s/secret.yaml.template k8s/secret.yaml
# Fill in tenant ID, client ID, and client_secret (for per-user PKCE)
# or refresh_token (for shared-token mode)

# Load env vars and run
eval "$(python k8s/env_from_k8s.py)" && python -m uvicorn app.main:app --reload --port 8000
```

Open <http://127.0.0.1:8000/>

### Configuration (k8s YAML)

All config is split across two files under `k8s/`:

| File | In git? | Content |
|------|---------|---------|
| `configmap.yaml` | Yes | Hostnames, partitions, legal tags, app settings |
| `secret.yaml` | **No** (gitignored) | Client IDs, tokens, client secrets, API keys |
| `secret.yaml.template` | Yes | Empty template — copy to `secret.yaml` and fill in |

Each OSDU instance is defined by `INSTANCE_<NAME>_*` env vars split across both files.
Non-secret identifiers (tenant IDs, hostnames) go in `configmap.yaml`;
credentials (client IDs, secrets, tokens) go in `secret.yaml`.

`k8s/env_from_k8s.py` merges both files into `export VAR=value` lines for local development.

### Docker

```bash
docker build -t ores .
docker run -p 8000:8000 --env-file <(python k8s/env_from_k8s.py | sed 's/^export //') ores
```

To enable GraphQL PostgreSQL access in Docker, add `-e GRAPHQL_PG_CONN_STRING="..."`.

---

## Project layout

```text
app/
  main.py              # FastAPI app: routes, middleware, BD enrichment
  auth.py              # PKCE sign-in, token exchange & refresh, SMDA
  tokenstore.py        # SQLite-backed persistent refresh-token store
  common.py            # Shared helpers (access_token, search_reservoirs, error sanitisation)
  osdu.py              # OSDU API client (Search, Storage, Workflow)
  cache.py             # Async TTL cache with thundering-herd protection
  instances.py         # OsduInstance dataclass & multi-instance registry
  ingest_router.py     # Manifest ingestion endpoints
  keys_router.py       # /keys page: browse dataspaces, types, objects
  search_router.py     # /search page: OSDU Search API queries
  resqml_viz.py        # RESQML 3D: PG SQL → XML/array → geometry JSON
  graphql_router.py    # GraphQL deep-search: PG-native + REST fallback
  graphql_refdata.py   # GraphQL reference-data resolver
  analyse.py           # Analyse page: reservoir comparison across DGs
  addgate.py           # Add DG page: create BusinessDecision records
  bd_enrichment.py     # BD ext.equinor overlay (workaround for OSDU schema drops)
  strat.py             # Stratigraphy manifest builders
  howto_router.py      # /howto page: grouped markdown articles
  schemahandler.py     # OSDU schema parsing & link extraction
  pg_backend.py        # asyncpg pool management for GraphQL/viz
  structuremap.py      # StructureMap rendering helpers
  templates/           # Jinja2 HTML templates
  static/              # Extracted JS modules (app.js, keys.js, strat.js, etc.)

demo/
  _auth.py             # Central auth module - token minting for all scripts
  gettoken.py          # CLI: mint token, list instances
  mint_refresh_token.py  # PKCE-based refresh token minting for admins
  run_pipeline.py      # Generic cross-platform pipeline runner
  ingest_demo.py       # Batch record ingestion helper
  drogon/              # Drogon DG1 pipeline
  drogon_dg2/          # Drogon DG2 pipeline
  seisint/             # Volantis seismic interpretation pipeline
  strat/               # Stratigraphic column manifests and tools
  epc/                 # Local OpenETPServer Docker + test data

test/                  # pytest test suite (368 tests)
md/                    # Documentation guides (rendered via /howto)
k8s/                   # Kubernetes / Radix manifests
```

---

## Design overview

### Middleware chain

Requests pass through middleware in this order:

1. **SessionMiddleware** (outermost) — makes `request.session` available
2. **Security headers** — `no-store`, `no-transform`, `nosniff`
3. **Auth middleware** (`inject_access_token`) — resolves an access token and attaches it to `request.state.access_token`

The auth middleware priority chain:

| Priority | Strategy | Source |
|----------|----------|--------|
| 0 | Per-user session | PKCE session cookie → server-side token stores |
| 1 | Instance token | `inst.get_access_token()` (refresh_token → client_credentials) |
| 2 | Env token | Top-level `REFRESH_TOKEN` env var (legacy) |
| 3 | Redirect / 401 | Browser → `/login-page`, API → `401` |

Public paths (`/login`, `/login-page`, `/auth/callback`, `/auth`, `/logout`, `/static/*`) bypass auth.

### Multi-instance architecture

Instances are registered from `INSTANCE_<NAME>_*` env vars at startup (`instances.py`).
The active instance can be switched at runtime via the UI's instance selector.

`_apply_instance()` pushes config to module-level globals in `osdu.py` and `auth.py`,
clears the TTL cache, closes the shared httpx client (SSL verify is client-level),
and switches the PG connection pool.

Auth mode is auto-detected from available credentials unless an explicit
`INSTANCE_<NAME>_AUTH_MODE` is set:

| Credentials available | Auto-detected mode |
|----------------------|-------------------|
| `REFRESH_TOKEN` + `CLIENT_SECRET` | `refresh_token+client_credentials` |
| `REFRESH_TOKEN` only | `refresh_token` |
| `CLIENT_SECRET` only | `client_credentials` |
| Neither | `none` (PKCE fallback) |
| Explicit `AUTH_MODE=per_user_pkce` | `per_user_pkce` (individual login, even with `CLIENT_SECRET` present) |

### Token storage

| Layer | Storage | Lifetime | Content |
|-------|---------|----------|---------|
| Session cookie | Browser | 30 days | `oid` + `instance_name` only |
| AT cache | In-memory dict | ~1 hour | Access tokens (never persisted) |
| RT store | SQLite (encrypted) | Until logout | Refresh tokens, Fernet-encrypted from `SECRET_KEY` |

Composite PK `(oid, instance_name)` prevents cross-instance token collisions.

### Error handling

All upstream OSDU errors pass through `sanitize_upstream_error()` and `safe_error_detail()`
in `common.py` to strip sensitive headers, internal URLs, and token fragments before
returning them to the browser.

---

## Demo pipelines

### Pipeline runner

The generic runner (`demo/run_pipeline.py`) auto-discovers generator scripts by naming
convention (`gen*.py`, `split*.py`, `ingest*.py`) and executes them in order:

```bash
python demo/run_pipeline.py                          # default: drogon_dg2
python demo/run_pipeline.py demo/drogon               # DG1 full pipeline
python demo/run_pipeline.py demo/drogon --skip-ingest  # generate only
python demo/run_pipeline.py demo/drogon --dry-run      # preview commands
python demo/run_pipeline.py --show demo/drogon_dg2     # show steps
python demo/run_pipeline.py --list                     # list profiles
```

### Pipeline steps (Drogon DG1)

The Drogon pipeline (`demo/drogon/`) generates ~19 OSDU records from a single FMU export CSV:

| Step | Script | Output |
|------|--------|--------|
| 0 | `split_valysar.py` | Split CSV — volumes + parameters |
| 0b | `genrefpropertytypes_drogon.py` | Reference data (PropertyTypes, FacetRoles) |
| 1 | `genmaster_drogon.py` | Reservoir + Segments + WorkProduct |
| 2-3 | `genrawmanifest` / `genstatmanifest` | Raw & Stat REV |
| 4 | `genparamsmanifest_drogon.py` | Parameters ColumnBasedTable |
| 5 | `gen_risk_drogon.py` + `gen_activity_drogon.py` | Risk + Activity records |
| 6 | `gen_businessdecision_drogon.py` | BusinessDecision (DG1) with full linkage |
| 7-8 | `gengeolabelset` / `manifest2records` | GeoLabelSet + split to individual files |
| 9 | `ingest_records_batch.py` | PUT to OSDU Storage API |

### Demo datasets

| Dataset | Pipeline | Records | Purpose |
|---------|----------|---------|---------|
| **Drogon DG1** | `demo/drogon/` | ~19 | Identify & Assess (7 segments, 3 facies) |
| **Drogon DG2** | `demo/drogon_dg2/` | ~31 | Concept Select (porosity scenario, PersistedCollection) |
| **Volantis SeisInt** | `demo/seisint/` | 66 | Seismic interpretation (faults, HCP, StructureMaps via RDDMS) |

### Token tools

Token minting is centralised in `demo/_auth.py` — single source of truth for
k8s YAML loading, instance resolution, and OAuth2 token exchange.

| File | Purpose |
|------|---------|
| `demo/_auth.py` | `get_token()`, `load_instance()`, `api_headers()`, `base_url()` |
| `demo/gettoken.py` | CLI: `--from-k8s`, `--list`, `--export`, `--json` |
| `app/get_token.py` | Minimal CLI: `--shell bash\|pwsh`, `--instance` |

```bash
python demo/gettoken.py eqndev --from-k8s      # mint a token
python demo/gettoken.py --list                  # list instances
```

---

## Deployment

### Radix (primary)

The app is deployed to Omnia Radix via `radixconfig.yaml`:

| Environment | Branch | Replicas | Scaling |
|-------------|--------|----------|---------|
| dev | `main` | 1 | Fixed |
| prod | `release` | 2 | Autoscaling 2–4 (CPU 70%) |

**Non-secret config** (hostnames, partitions, legal tags) is inline in `radixconfig.yaml`.
**Secrets** (CLIENT_ID, CLIENT_SECRET, SCOPE, TENANT_ID, SECRET_KEY) are set in
**Radix Console → ores → \<env\> → Secrets** — never committed to git.

Health probes: readiness + liveness on `/login-page`.

### Kubernetes (alternative)

```bash
kubectl apply -k k8s/
```

Required secrets:

| Key | Purpose |
|-----|---------|
| `SECRET_KEY` | Signs session cookies and encrypts refresh tokens — must be identical across replicas |
| `INSTANCE_<NAME>_TENANT_ID` | AD tenant for the OSDU instance |
| `INSTANCE_<NAME>_CLIENT_ID` | App registration client ID |
| `INSTANCE_<NAME>_REFRESH_TOKEN` | Shared refresh token (optional — enables zero-click mode) |
| `INSTANCE_<NAME>_CLIENT_SECRET` | Client secret (required for confidential-client PKCE and/or client_credentials) |

### Persisting the token database

Mount a PVC at `/data` so per-user refresh tokens survive pod restarts:

```yaml
# PVC (add to k8s/)
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ores-data
  namespace: ores
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 100Mi
```

```yaml
# In deployment.yaml
volumeMounts:
  - name: ores-data
    mountPath: /data
volumes:
  - name: ores-data
    persistentVolumeClaim:
      claimName: ores-data
```

> `replicas: 1` because SQLite does not support concurrent writers across pods.
> For multi-replica HA, replace SQLite with PostgreSQL or Redis.
>
> Set `HTTPS_ONLY=true` in production behind TLS to mark cookies as `Secure`.

---

## Performance & caching

| Feature | Module | Detail |
|---------|--------|--------|
| TTL cache | `app/cache.py` | `ttl_cache` decorator with per-key `asyncio.Lock` (thundering-herd safe) |
| Dataspace list | `app/osdu.py` | Cached 120 s |
| Reservoir search | `app/common.py` | Cached 90 s |
| API concurrency | `app/osdu.py` | Semaphore (default 20, `OSDU_MAX_CONCURRENT`) |
| Parallel fetches | analyse, addgate, keys | `asyncio.gather` for independent calls |
| Cache invalidation | `app/cache.py` | `cache_clear()` called on instance switch and dataspace create/delete |

---

## BD enrichment overlay

OSDU's `BusinessDecision` schema drops custom `ext.equinor` keys during workflow ingestion.

**Workaround** (`app/bd_enrichment.py` + `app/main.py`):
1. `_load_bd_enrichments()` scans BD manifests at startup, caches `ext.equinor` data by record ID.
2. `_apply_bd_local_enrichment()` merges cached fields into OSDU-fetched records at render time.
   OSDU data wins for keys that exist in both.

---

## GraphQL deep search

The `/keys` page includes a GraphQL panel for deep RESQML queries — object browsing,
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

See [Query.md](Query.md) for the full query guide.

---

## Testing

```bash
python -m pytest test/ -v                                 # full suite (368 tests)
python -m pytest test/ -x -q --tb=short                   # quick, stop on first failure
python -m pytest test/ --ignore=test/test_pg_vs_rest.py   # skip PG-dependent tests
```

Test coverage includes: auth modes, PKCE flow, token refresh, all page routes,
k8s loading, instance discovery, token minting, caching, tokenstore, multiuser sessions,
error handling, addgate, ingest, keys, search, strat, bd_enrichment, resqml_viz.

All tests use `unittest.mock` to patch OSDU API calls — no live credentials or network needed.

---

## API reference

### Page routes

| Method | Path | Handler | Purpose |
|--------|------|---------|---------|
| GET | `/` | `main.py` | Dataspace management page |
| GET | `/keys` | `keys_router` | Record browser |
| GET | `/viz` | `keys_router` | RESQML 3D viewer |
| GET | `/search` | `search_router` | OSDU Search page |
| GET | `/analyse` | `analyse` | BD comparison page |
| GET | `/add-dg` | `addgate` | Record creation page |
| GET | `/strat` | `strat` | Stratigraphy page |
| GET | `/graphql` | `graphql_router` | GraphiQL IDE |
| GET | `/howto` | `howto_router` | Documentation browser |

### Auth endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/login` | Redirect to Azure AD (PKCE) |
| GET | `/login-page` | Login page HTML |
| GET | `/auth/callback` | PKCE code exchange |
| GET | `/auth` | Auth diagnostics JSON |
| GET | `/logout` | Clear session + tokens |

### Data API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/dataspaces` | List dataspaces |
| POST | `/api/dataspace/create` | Create dataspace |
| POST | `/api/dataspace/lock` | Lock dataspace |
| POST | `/api/dataspace/delete` | Delete dataspace |
| GET | `/keys/types.json` | Record types in a dataspace |
| GET | `/keys/records.json` | Records of a type |
| GET | `/keys/object/detail.json` | Full record detail |
| GET | `/keys/object/geometry3d.json` | Single-object 3D geometry |
| GET | `/keys/object/map.png` | Grid2d depth-map PNG |
| GET | `/keys/viz/objects.json` | 3D-renderable objects by type |
| POST | `/keys/viz/batch.json` | Batch geometry fetch (≤50 objects) |
| POST | `/api/graphql/query` | GraphQL endpoint |
| GET | `/api/graphql/info` | GraphQL backend status |
| POST | `/api/search` | OSDU Search proxy |
| POST | `/api/ingest` | Manifest ingestion |

---

## Links

| Resource | Path |
|----------|------|
| User & Admin guide | [md/Readme.md](Readme.md) |
| Root readme | [readme.md](../readme.md) |
| Activity guide | [Activity.md](Activity.md) |
| BD guide | [BdDemo.md](BdDemo.md) |
| Query guide | [Query.md](Query.md) |
| SeisInt guide | [SeisInt.md](SeisInt.md) |
| Strat guide | [StratColumn.md](StratColumn.md) |
