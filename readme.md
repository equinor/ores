# OSDU RDDMS admin UI — web client and demo toolkit

A FastAPI-based administrative UI for an OSDU-style RDDMS (Reservoir Data / Decision Management System) plus a demo pipeline toolkit for generating, ingesting and comparing Business Decisions, Volumes, Risks and Stratigraphy records.

---

## What the client can do

| Page | Purpose |
|------|---------|
| **RddmsAdmin** (`/`) | List and manage OSDU Dataspaces — create, lock, unlock, delete, build manifests |
| **RddmsResources** (`/keys`) | Browse dataspaces, record types, individual objects; inspect table & graph data |
| **OsduSearch** (`/search`) | Query the OSDU Search API and view results with kind-specific cards (BusinessDecision, REV, Risk, GeoLabelSet, etc.) |
| **Analyse** (`/analyse`) | Select a Reservoir, compare Business Decisions across decision gates (DG1→DG4) with volume/risk/economics deltas and charts |
| **Add DG** (`/add-dg`) | Create and ingest a new BusinessDecision for an existing Reservoir, linking REV, GeoLabelSet, Activity and Risk records |
| **Stratigraphy** (`/strat`) | Preview and ingest stratigraphic column records |

Key rendering features:

- **BD cards** — gradient header, headline volume KPIs (three-tier fallback: stat WPC → GeoLabelSet → ext.equinor), development concept, reservoir properties, economics, schedule, production forecast chart, alternatives, risk chips, uncertainties, authors & governance.
- **REV cards** — teal-themed with P10/P50/P90 headlines, metadata highlights, full volume table.
- **Analyse comparison** — gate timeline, side-by-side metric deltas (STOIIP, NPV, CAPEX, etc.), risk diff chips (added/removed/mitigated), property diffs, synthesis insights, Chart.js overlay charts.
- **Mermaid relationship graphs** — interactive record-relationship diagrams with ancestry, data references, type-based styling.
- **Local BD enrichment overlay** — OSDU silently drops custom `ext.equinor` keys during ingestion; the app loads manifests at startup and merges them back at render time.

## Requirements

### Runtime

| Requirement | Version |
|-------------|---------|
| Python | 3.11+ |
| FastAPI | 0.115+ |
| uvicorn | 0.32+ |
| httpx | (latest) |
| numpy | (latest) |

Install all dependencies:

```bash
pip install -r requirements.txt
```

### Environment variables (`.env`)

| Variable | Required | Purpose |
|----------|----------|---------|
| `OSDU_BASE_URL` | Yes | OSDU platform hostname (e.g. `equinorswedev.energy.azure.com`) |
| `DATA_PARTITION_ID` | Yes | OSDU data partition (e.g. `dev`) |
| `AZURE_TENANT_ID` | Yes | Azure AD tenant ID |
| `AZURE_CLIENT_ID` | Yes | Azure AD app registration client ID |
| `AZURE_SCOPE` | Yes | OAuth2 scope |
| `REFRESH_TOKEN` | Yes* | Shared refresh token for env-token auth mode |
| `SECRET_KEY` | No | Session cookie signing key (auto-generated if absent) |
| `APP_KEY` | No | OSDU AppKey header |
| `LOG_LEVEL` | No | Python log level (default `INFO`) |

*When `REFRESH_TOKEN` is absent, the app falls back to per-user PKCE sign-in via Azure AD redirect.

### Frontend (CDN — no npm install)

- **Chart.js 4** — production forecast & comparison charts
- **Mermaid 10** — relationship graph rendering

### Quick start

```bash
# 1. Create .env with your Azure AD credentials
# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the server
python -m uvicorn app.main:app --reload --port 8000 --host 127.0.0.1 --env-file ./.env
```

Open <http://127.0.0.1:8000/> in a browser.

---

## Project layout

```text
app/
  main.py              # FastAPI app: routes, BD enrichment, volume helpers
  auth.py              # PKCE sign-in, token exchange & refresh
  osdu.py              # OSDU API client (Search, Storage, Workflow)
  ingest_router.py     # Manifest ingestion endpoints
  analyse.py           # Analyse page: reservoir comparison across DGs
  addgate.py           # Add DG page: create new BusinessDecision records
  schemahandler.py     # JSON schema & manifest helpers
  strat.py             # Stratigraphy manifest builders
  templates/           # Jinja2 HTML templates
  static/              # JS/CSS assets

demo/
  drogon/              # Drogon DG1 pipeline (self-contained)
  drogon_dg2/          # Drogon DG2 pipeline (references drogon/ for shared data)
  grand/               # GRAND DG2 pipeline
    json/              # Generated manifests and reference data
    py/                # Generator scripts
  md/                  # Documentation and guides
  data/                # Raw CSV data files
  strat/               # Stratigraphy manifests and records
```

---

## Pipeline guide — adding a new field / decision gate dataset

See [demo/md/PipelineGuide.md](demo/md/PipelineGuide.md) for the full guide, including:

- Data input format (CSV structure, supported units, properties)
- Step-by-step pipeline walkthrough
- How to add a new property type or facet
- How to add a new field/reservoir to OSDU
- Reference data schemas and extension points

### Quick pipeline overview

The Drogon pipeline (`demo/drogon/`) generates ~19 OSDU records from a single FMU export CSV:

| Step | Script | Records |
|------|--------|---------|
| 0 | `split_valysar.py` | Split raw CSV → volumes + parameters |
| 0b | `genrefpropertytypes_drogon.py` + `genreffacetrole_drogon.py` | Reference data (PropertyTypes, FacetRoles) |
| 1 | `genmaster_drogon.py` | Reservoir + 7 Segments + WorkProduct |
| 2 | `genrawmanifest_drogon.py` | Raw REV (ColumnBasedTable with per-realisation volumes) |
| 3 | `genstatmanifest_drogon.py` | Stat REV (P10/P50/P90/Mean aggregated volumes) |
| 4 | `genparamsmanifest_drogon.py` | Parameters ColumnBasedTable (OWC, porosity) |
| 5 | `gen_risk_drogon.py` | Risk records |
| 5b | `gen_activity_drogon.py` | Activity + ActivityTemplate + ETPDataspace |
| 6 | `gen_businessdecision_drogon.py` | BusinessDecision (DG1) with full linkage |
| 6b | `gen_documents_drogon.py` | Document WPCs (SRA, CRA, PDO) |
| 7 | `gengeolabelset_drogon.py` | GeoLabelSet (headline KPI values) |
| 8 | `manifest2records_drogon.py` | Split manifests → individual record files |
| 9 | `ingest_records_batch.py` | PUT records to OSDU Storage API |

Run the full pipeline:

```powershell
.\demo\drogon\run_pipeline.ps1                # generate + ingest
.\demo\drogon\run_pipeline.ps1 -SkipIngest    # generate manifests only
.\demo\drogon\run_pipeline.ps1 -VerifyAfter   # verify all records after ingest
```

Or step by step:

```bash
python demo/drogon/split_valysar.py
python demo/drogon/genrefpropertytypes_drogon.py
python demo/drogon/genreffacetrole_drogon.py
python demo/drogon/genmaster_drogon.py
python demo/drogon/genrawmanifest_drogon.py
python demo/drogon/genstatmanifest_drogon.py
python demo/drogon/genparamsmanifest_drogon.py
python demo/drogon/gen_risk_drogon.py
python demo/drogon/gen_activity_drogon.py
python demo/drogon/gen_businessdecision_drogon.py
python demo/drogon/gen_documents_drogon.py
python demo/drogon/gengeolabelset_drogon.py
python demo/drogon/manifest2records_drogon.py
python demo/drogon/ingest_records_batch.py --delay 3
```

---

## Local BD enrichment overlay

OSDU's `BusinessDecision` schema only preserves **7 registered** `ext.equinor` keys. Custom keys (`ProductionProfile`, `Authors`, `DevelopmentConcept`, `ReservoirProperties`, `KeyEconomics`, `ScheduleMilestones`, etc.) are silently dropped during workflow ingestion.

**Workaround** (in `app/main.py`):

1. `_load_bd_enrichments()` scans BD manifests at startup and caches `ext.equinor` data by record ID.
2. `_apply_bd_local_enrichment()` merges cached fields into OSDU-fetched records at render time. OSDU data always wins for keys that exist in both.

---

## Demo datasets

| Dataset | Pipeline | Records | BD |
|---------|----------|---------|-----|
| **Drogon DG1** | `demo/drogon/` | ~19 | Identify & Assess (7 segments, 3 facies) |
| **Drogon DG2** | `demo/drogon_dg2/` | ~25 | Concept Select (porosity ×0.8 scenario) |
| **GRAND DG2** | `demo/grand/` | ~9 | Concept Select (2 segments, no facies) |

---

## Links

| Resource | Path |
|----------|------|
| App entry | `app/main.py` |
| Auth | `app/auth.py` |
| OSDU client | `app/osdu.py` |
| Ingest API | `app/ingest_router.py` |
| Analyse page | `app/analyse.py` |
| Add DG page | `app/addgate.py` |
| Drogon pipeline | `demo/drogon/` |
| Pipeline guide | `demo/md/PipelineGuide.md` |
| BD modelling guide | `demo/md/BusinessDecision.md` |
| Volume schemas | `demo/md/Volumes.md` |
| Risk guide | `demo/md/Risk.md` |
| Digest (overview) | `demo/md/Digest.md` |
