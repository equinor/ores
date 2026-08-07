# OSDU Record Generation & Ingestion Scripts

Generic, ORES-independent toolkit for generating and ingesting OSDU records.
Config-driven pipeline: define your dataset in a single JSON file, generate all records, ingest to any OSDU instance.

## Quick Start

```bash
# Full pipeline: generate + ingest
python demo/scripts/cli.py pipeline --config demo/scripts/inputs/examples/drogon_DG2.json --target eqndev

# Generate only (no ingest)
python demo/scripts/cli.py pipeline --config demo/scripts/inputs/examples/drogon_DG2.json --skip-ingest

# Dry run (validate, don't push)
python demo/scripts/cli.py pipeline --config demo/scripts/inputs/examples/omegas_WPC.json --dry-run

# Ingest pre-generated records
python demo/scripts/cli.py ingest --dir ./records --target eqndev --token eyJ...
```

## CLI Commands

| Command | Purpose |
|---------|---------|
| `pipeline` | Full pipeline: load config → generate → ingest |
| `generate` | Generate records from JSON input file |
| `ingest` | Ingest records from a directory to OSDU |
| `template` | Print a blank record template (to fill in) |
| `validate` | Validate record files before ingestion |
| `split` | Split manifest envelopes into individual records |
| `list-types` | Show all supported record types |

## Dataset Config Format

Each project/gate is defined in a single JSON file:

```json
{
  "project": "Drogon",
  "gate": "DG2",
  "description": "...",
  "records": [
    {"type": "reservoir", "slug": "drogon-reservoir", "data": {...}},
    {"type": "risk", "slug": "drogon-dg2-risk-porosity", "data": {...}},
    {"type": "business_decision", "slug": "drogon-dg2-bd", "data": {...}}
  ]
}
```

See `inputs/examples/` for complete examples:
- `drogon_DG2.json` - Field development, Concept Select
- `omegas_WPC.json` - Exploration prospect, Work Program Committee
- `northern_lights_DG3.json` - CCS storage, FEED approval

## Supported Record Types

| Type | OSDU Kind | Use Case |
|------|-----------|----------|
| `business_decision` | `master-data--BusinessDecision` | Decision gate with linked evidence |
| `risk` | `master-data--Risk` | 5×5 risk matrix with mitigations |
| `activity` | `work-product-component--Activity` | Executed workflow instance |
| `activity_template` | `work-product-component--ActivityTemplate` | Workflow definition |
| `document` | `work-product-component--Document` | Reports (SRA, CRA, PDO, etc.) |
| `persisted_collection` | `work-product-component--PersistedCollection` | Evidence bundles |
| `collaboration_project` | `work-product-component--CollaborationProject` | Shared project space |
| `reservoir_volumes` | `work-product-component--ReservoirEstimatedVolumes` | Volumetrics |
| `geolabelset` | `work-product-component--GeoLabelSet` | Segment KPIs |
| `development_concept` | `work-product-component--DevelopmentConcept` | Facility/well plan |
| `column_based_table` | `work-product-component--ColumnBasedTable` | Tabular data |
| `reservoir` | `master-data--Reservoir` | Field master data |
| `activity_state_template` | `work-product-component--ActivityStateTemplate` | Lifecycle milestones |

## Authentication

Token sources (tried in order):
1. `--token` CLI flag
2. `OSDU_TOKEN` environment variable
3. Config file (`~/.osdu/config.json`)
4. `k8s/secret.yaml` (ores repo fallback)

```bash
# Option A: explicit token
python demo/scripts/cli.py pipeline --config ... --token eyJ...

# Option B: environment variable
export OSDU_TOKEN=eyJ...
python demo/scripts/cli.py pipeline --config ...

# Option C: config file (~/.osdu/config.json)
python demo/scripts/cli.py pipeline --config ... --target eqndev
```

## Instance Configuration

Create `~/.osdu/config.json`:
```json
{
  "instances": {
    "eqndev": {
      "host": "https://equinorswedev.energy.azure.com",
      "partition": "dev",
      "legal_tag": "dev-equinor-private-default",
      "owners": ["data.default.owners@dev.dataservices.energy"],
      "viewers": ["data.default.viewers@dev.dataservices.energy"],
      "countries": ["NO"],
      "tenant_id": "...",
      "client_id": "..."
    }
  }
}
```

Or use environment variables:
```bash
export OSDU_HOST=https://equinorswedev.energy.azure.com
export OSDU_PARTITION=dev
export OSDU_LEGAL_TAG=dev-equinor-private-default
export OSDU_OWNERS=data.default.owners@dev.dataservices.energy
export OSDU_VIEWERS=data.default.viewers@dev.dataservices.energy
```

## Architecture

```
demo/scripts/
├── cli.py                 # CLI entry point
├── config.py              # Instance configuration loader
├── osdu_client.py         # OSDU Storage/Search API client
├── record_factory.py      # Record template engine
├── ingest.py              # Ingestion (batch, rewrite, retry)
├── manifest_splitter.py   # Split manifests → individual records
├── templates/             # JSON templates per record type
│   ├── business_decision.json
│   ├── activity.json
│   ├── risk.json
│   └── ...
└── inputs/examples/       # Dataset pipeline configs
    ├── drogon_DG2.json
    ├── omegas_WPC.json
    └── northern_lights_DG3.json
```

## Redundancy Notes (vs existing demo/ scripts)

This suite **consolidates** several patterns that were duplicated:
- `ingest_records_batch.py` (drogon/ + drogon_dg2/) → `ingest.py`
- `manifest2records_drogon.py` + `manifest2records_dg2.py` → `manifest_splitter.py`
- Scattered auth logic → `config.py` + `osdu_client.py`
- Per-dataset generator scripts → config-driven `record_factory.py`

The existing `demo/run_pipeline.py` remains for running the **full gen_*.py script sequences** (DG1→DG2 with CSVs, RESQML, etc.). This new suite is for **config-driven record generation** where you define everything in one JSON file.
