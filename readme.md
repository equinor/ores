# OSDU RDDMS admin UI — web client and demo toolkit

This repository contains a FastAPI web client that acts as a lightweight administrative UI for an OSDU-style RDDMS (Reservoir Data / Decision Management System) and a demo kit with example manifests, JSON schemas, reference data and small helper scripts for Business Decision, Volumes & Uncertainty and Stratigraphy workflows.

Key capabilities:

- **Search & record viewer** — query OSDU Search API and render results with kind-specific cards (BusinessDecision, ReservoirEstimatedVolumes, Risk, etc.).
- **Business Decision cards** — rich rendering of BD records including headline volume KPIs, development concept, reservoir properties, key economics, schedule milestones, production forecast chart, alternatives, risk chips, uncertainties, and governance/authorship.
- **REV cards** — teal-themed cards for ReservoirEstimatedVolumes with headline P10/P50/P90 KPIs and metadata highlights.
- **Local BD enrichment overlay** — OSDU schema only preserves 7 registered `ext.equinor` keys; custom fields (ProductionProfile, Authors, DevelopmentConcept, etc.) are silently dropped during ingestion. The app loads manifest files at startup and merges the missing fields back into fetched records so the UI can render the full decision package.
- **Production forecast chart** — Chart.js stacked bar + line chart rendering yearly oil, gas, and water production with peak/EUR/RF summary.
- **Mermaid relationship graphs** — interactive record-relationship diagrams (ancestry, data references) with node deduplication and type-based styling.
- **Stratigraphy manifest builder** — UI-driven creation and ingestion of stratigraphic column records.
- **Drogon pipeline** — complete FMU-to-OSDU pipeline (15 records) with manifest generators, RESQML activity chain, and batch ingestion.

## Quick setup

- Store your Azure AD (adme) `refresh_token` as an environment variable or in a `.env` file used by the app.

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000 --host 127.0.0.1 --env-file ./.env
```
Open <http://127.0.0.1:8000/> in a browser.

### Frontend dependencies (CDN)

- **Chart.js 4** — production forecast stacked bar + line charts
- **Mermaid 10** — relationship graph rendering
- Both are loaded from CDN in the templates; no npm install required.


## Project layout and components

Important files and folders (top-level):

```text
/app
  ├─ main.py            # FastAPI app: routes, BD enrichment overlay, volume helpers
  ├─ auth.py            # Authentication helpers (AAD PKCE + token refresh)
  ├─ osdu.py            # OSDU API client helpers and wrappers
  ├─ ingest_router.py   # Endpoints to create manifests and submit ingest/workflow
  ├─ schemahandler.py   # Utilities for JSON schema & manifest generation
  ├─ strat.py           # Stratigraphy helpers & manifest builders
  ├─ templates/         # Jinja2 HTML templates (web client pages)
  └─ static/            # Static JS/CSS assets

/demo
  ├─ json/              # example manifests, reference-data and schema JSON files
  ├─ md/                # explanatory markdown notes and demo READMEs
  ├─ py/                # helper scripts for manifest generation and ingest demos
  └─ drogon/            # Drogon FMU-to-OSDU pipeline (generators, manifests, records)
```

Key implementation files:

- `app/main.py` — app startup, routes, template mounting, local BD enrichment overlay (`_load_bd_enrichments`, `_apply_bd_local_enrichment`), volume helpers (`_enrich_bd_volumes`, `_normalize_volumes`).
- `app/auth.py` — PKCE sign-in, token exchange and refresh helpers.
- `app/osdu.py` — thin client wrapper for Search, Workflow and other OSDU endpoints.
- `app/ingest_router.py` — server endpoints that build manifests and submit workflow runs.
- `app/schemahandler.py` — manifest composition and JSON-schema helpers.
- `app/strat.py` — stratigraphy-specific manifest builders and utilities.

## Web client pages

The UI is server-rendered with Jinja2 templates under `app/templates`. Main pages:

- `index.html` — homepage with links and quick status.
- `keys.html` — tokens, configured keys and quick auth controls.
- `search.html` — run raw Search queries (POST /api/search/v2/query) and view results with kind-specific rendering:
  - **BD card** (`.bd-card`) — gradient header, meta grid, headline volume KPIs with three-tier fallback (`stat WPC ColumnValues` → `ext UncertaintySummary` → `ext VolumesSummary_STOIIP_MSm3`), development concept grid, reservoir properties grid, key economics row, schedule milestones, production forecast (Chart.js canvas + collapsible table), alternatives with rank/action badges, risk chips, key uncertainties with impact colouring, input parameters with tags, authors & governance, recommendations, and uncertainty methodology.
  - **REV card** (`.rev-card`) — teal-to-blue gradient header with P10/P50/P90 volume KPIs, metadata highlights, and full volume table.
  - **Default card** — generic metadata card for any other record type.
- `strat.html` — preview stratigraphy manifest generation and trigger create-and-ingest for strat records.
- `_fragments.html` — shared template fragments (header, footer, forms).

Width constraints (`max-width: 72 rem` on cards, `56 rem` on KPI grids) and horizontal-scroll wrappers keep large volume tables readable.

Auth and flows summary:

- Browser is redirected to Azure AD `/authorize` for PKCE sign-in. Callback exchanges `code` for `access_token` and `refresh_token`.
- App uses `access_token` to call OSDU Search and Workflow APIs. Manifest create-and-ingest is performed by `app/ingest_router.py`, which can stream a generated `manifest.json` to the browser and submit a background workflow run to the Workflow service.

## Local BD enrichment overlay

OSDU's `BusinessDecision` schema only preserves **7 registered** `ext.equinor` keys during workflow ingestion:

> `Alternatives`, `Assurance`, `CRA`, `Ensemble`, `InterpretationLineage`, `SRA`, `UncertaintySummary`

Custom keys like `ProductionProfile`, `Authors`, `DevelopmentConcept`, `ReservoirProperties`, `VolumesSummary_STOIIP_MSm3`, `KeyUncertainties`, `KeyEconomics`, and `ScheduleMilestones` are **silently dropped**.

**Workaround** (implemented in `app/main.py`):

1. `_load_bd_enrichments()` — runs at startup, scans `demo/json/manifest_dg_businessdecision.json` and `demo/drogon/manifest_bd_drogon.json`, caches each record's `ext.equinor` data keyed by record ID.
2. `_apply_bd_local_enrichment(data_block, record_id)` — called at search-result time, merges cached fields into the OSDU-fetched record. Only fills keys absent in live data, so OSDU always wins.

This allows the UI to render the full decision package (production forecast, economics, schedule, etc.) even though OSDU storage doesn't persist those fields.

## Demo content (Business Decision, Volumes & Uncertainty, Stratigraphy, Drogon)

The `demo` folder contains curated datasets, JSON manifests, reference catalogs and scripts used by the web client or as standalone examples.

### Business Decision manifests

- `demo/json/manifest_dg_businessdecision.json` — **GRAND DG2** BusinessDecision manifest. Enriched `ext.equinor` with: `Authors`, `ReviewTeam`, `Alternatives`, `DevelopmentConcept`, `ReservoirProperties`, `VolumesSummary_STOIIP_MSm3`, `KeyUncertainties`, `UncertaintySummary`, `DG3Recommendations`, `ProductionProfile` (23-year forecast, peak oil 13.8 kSm³/d, EUR 43.4 MSm³, RF 36.6%), `KeyEconomics` (NPV $820M, IRR 22%, CAPEX 22 400 MNOK, breakeven $35/bbl), `ScheduleMilestones` (7 milestones DG2 → Plateau Production).
- `demo/drogon/manifest_bd_drogon.json` — **Drogon DG1** BusinessDecision manifest. Enriched with: `Authors`, `ReviewTeam`, `Alternatives`, `DevelopmentConcept`, `ReservoirProperties`, `KeyUncertainties`, `UncertaintySummary`, `DG2Recommendations`, `KeyEconomics` (placeholder — DG1 economics not yet finalised).
- `demo/json/manifest_dg_complete.json` — combined GRAND manifest (risks + BD), kept in sync with the standalone BD file.
- `demo/json/manifest_dg_risks.json` — GRAND risk records linked from the BD via `RiskIDs`.

### Drogon pipeline

`demo/drogon/` contains a complete FMU-to-OSDU pipeline that generates **15 records** from a single FMU export CSV. See `demo/drogon/DrogonDataModel.md` for full documentation. Key scripts:

| Step | Script | Output |
|------|--------|--------|
| 0 | `split_valysar.py` | volumes + parameters CSVs |
| 1 | `genmaster_drogon.py` | Reservoir, 7 Segments, WorkProduct |
| 2–4 | `genrawmanifest` / `genstatmanifest` / `genparamsmanifest` | RAW REV, STAT REV, ColumnBasedTable |
| 5 | `gen_risk_drogon.py` | Risk record |
| 6 | `gen_businessdecision_drogon.py` | BusinessDecision (DG1) |
| 7 | `manifest2records_drogon.py` | 15 individual JSON files in `records/` |
| 8 | `ingest_records_batch.py` | PUT to OSDU Storage API |

### Other demo artifacts

- `demo/json/manifest_wpcraw.json`, `manifest_wpcstat.json`, `manifest_wpcgeolabelset.json` — WPC / volumes-related manifests.
- `demo/json/refcat_*.json`, `reftypes_*.json` — reference catalogs (roles, risk/probability, severity, geolabel types, property types).
- `demo/strat/` — stratigraphy manifests, `stratcolumn_records/` and `stratref_records/` sample records.
- `demo/md/BusinessDecision.md` — OSDU modeling guide for BD records (linking patterns, Parameters[], examples), plus implementation appendices on ext.equinor schema limitations and the local enrichment overlay.
- `demo/md/Volumes.md`, `Uncertainty.md`, `Risk.md`, `GeoLabelSet.md`, `Digest.md`, `CrsGuide.md`, `StratigraphicColumnHandler.md` — reference notes on OSDU schema patterns.
- `demo/drogon/DrogonDataModel.md` — Drogon pipeline architecture, record inventory, RESQML activity chain, and Explorer UI guide.

How to use the demo scripts locally:

1. Populate a `.env` with required Azure AD credentials, partition id and any endpoint overrides the scripts expect.
2. Run a helper script (example):

```bash
python demo/py/1genrawmanifest.py --env-file .env
python demo/py/4ingest.py --env-file .env
```

Drogon pipeline (full run from CSV to OSDU):

```powershell
.\demo\drogon\run_pipeline.ps1          # generate + ingest
.\demo\drogon\run_pipeline.ps1 -SkipIngest  # generate only
```

Notes:

- The demo folder lives at the repository root: `./demo/` (moved from `app/demo/`).
- Scripts accept `--env-file` and will read values such as partition id and AAD client/secret/refresh token from that file. Use the example `.env` or build one from `app/templates` if available.
- You can run the scripts offline to just generate manifest JSON for inspection, or point them to an operational OSDU endpoint to exercise ingest/workflow.

## Reference data and schemas

- `demo/json/reftypes_*.json` and `demo/json/refcat_*.json` — reference catalogs for facet roles, geolabel types, severity/probability catalogs and similar small lookup payloads.
- `demo/strat/manifest_*.json` and `demo/strat/stratcolumn_records/` — stratigraphy-specific manifests and example records.

Re-use `app/schemahandler.py` and `app/strat.py` when extending demos or composing new manifest types to ensure schema-conformant output.

## Sequence diagrams (auth & ingest)

- Auth flow: PKCE redirect -> callback -> token exchange -> app uses `access_token` to call OSDU APIs.
- Manifest ingestion: UI builds metadata-first manifest -> stream manifest to user optionally -> submit workflow run to Workflow service -> ingest proceeds in background.

## Links and useful entry points (files in this repo)

- App entry: `app/main.py`
- Auth helpers: `app/auth.py`
- OSDU client: `app/osdu.py`
- Ingest endpoints: `app/ingest_router.py`
- Manifest/schema helpers: `app/schemahandler.py`
- Strat helpers: `app/strat.py`
- Demo manifests & reference data: `demo/json/`
- GRAND DG2 BD manifest: `demo/json/manifest_dg_businessdecision.json`
- Drogon DG1 BD manifest: `demo/drogon/manifest_bd_drogon.json`
- Drogon pipeline guide: `demo/drogon/DrogonDataModel.md`
- Demo markdown notes: `demo/md/`
- Demo scripts: `demo/py/`

All paths above are relative. Open files to inspect payload shapes and example content.
