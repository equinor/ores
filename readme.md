# OSDU RDDMS admin UI — web client and demo toolkit

This repository contains a FastAPI web client that acts as a lightweight administrative UI for an OSDU-style RDDMS (Reservoir Data / Decision Management System) and a demo kit with example manifests, JSON schemas, reference data and small helper scripts for Business Decision, Volumes & Uncertainty and Stratigraphy workflows.

The README below documents the project components, web client pages, demo content (scripts, markdown notes and JSON schemas) and how to run the app and demo scripts locally.

## Quick setup

- Store your Azure AD (adme) `refresh_token` as an environment variable or in a `.env` file used by the app.

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000 --host 127.0.0.1 --env-file ./.env
```
Open <http://127.0.0.1:8000/> in a browser.


## Project layout and components

Important files and folders (top-level):

```text
/app
  ├─ main.py            # FastAPI app entry, routing and template mounting
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
  └─ py/                # helper scripts for manifest generation and ingest demos
```

Key implementation files:

- `app/main.py` — app startup, routes and template mounting.
- `app/auth.py` — PKCE sign-in, token exchange and refresh helpers.
- `app/osdu.py` — thin client wrapper for Search, Workflow and other OSDU endpoints.
- `app/ingest_router.py` — server endpoints that build manifests and submit workflow runs.
- `app/schemahandler.py` — manifest composition and JSON-schema helpers.
- `app/strat.py` — stratigraphy-specific manifest builders and utilities.

## Web client pages

The UI is server-rendered with Jinja2 templates under `app/templates`. Main pages:

- `index.html` — homepage with links and quick status.
- `keys.html` — tokens, configured keys and quick auth controls.
- `search.html` — run raw Search queries (POST /api/search/v2/query) and view results.
- `strat.html` — preview stratigraphy manifest generation and trigger create-and-ingest for strat records.
- `_fragments.html` — shared template fragments (header, footer, forms).

Auth and flows summary:

- Browser is redirected to Azure AD `/authorize` for PKCE sign-in. Callback exchanges `code` for `access_token` and `refresh_token`.
- App uses `access_token` to call OSDU Search and Workflow APIs. Manifest create-and-ingest is performed by `app/ingest_router.py`, which can stream a generated `manifest.json` to the browser and submit a background workflow run to the Workflow service.

## Demo content (Business Decision, Volumes & Uncertainty, Stratigraphy)

The `demo` folder contains curated datasets, JSON manifests, reference catalogs and scripts used by the web client or as standalone examples.

Notable demo artifacts (open these files to inspect exact payloads):

- `demo/json/manifest_dg_businessdecision.json` — Business Decision manifest example.
- `demo/json/manifest_dg_complete.json` — a fuller example manifest combining metadata and file pointers.
- `demo/json/manifest_wpcraw.json`, `demo/json/manifest_wpcstat.json`, `demo/json/manifest_wpcgeolabelset.json` — WPC / volumes-related manifests.
- `demo/json/*.json` — multiple `refcat_*.json` and `reftypes_*.json` reference data used by manifests (roles, risk/probability, severity, etc.).
- `demo/strat/` — stratigraphy manifests, `stratcolumn_records/` and `stratref_records/` sample records used to build WPC strat manifests.
- `demo/md/0aReadmeVolumes.md`, `demo/md/0aReadmeUncertainty.md`, `demo/md/BusinessDecision.md` — human-readable notes describing the demo datasets and mapping to OSDU record types.
- `demo/drogon/DrogonDataModel.md` — Drogon pipeline/data-model guide, including the RESQML 3-step sequential activity chain (`Generate Input Parameters` → `RMS Run` → `Aggregate Statistics`).
- `demo/py/1genrawmanifest.py`, `demo/py/4ingest.py`, `demo/py/7manifest2records.py` — scripts to generate manifests, convert manifests to records and to POST ingest/workflow calls (examples accept `--env-file .env`).

How to use the demo scripts locally:

1. Populate a `.env` with required Azure AD credentials, partition id and any endpoint overrides the scripts expect.
2. Run a helper script (example):

```bash
python demo/py/1genrawmanifest.py --env-file .env
python demo/py/4ingest.py --env-file .env
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
- Demo markdown notes: `demo/md/`
- Demo scripts: `demo/py/`

All paths above are relative. Open files to inspect payload shapes and example content.
