# Ingest Guide

> Generating OSDU manifests from RDDMS dataspaces and ingesting to OSDU catalog instances.

---

## Overview

The ingest pipeline has two main steps:

1. **Manifest generation** — Convert RESQML objects in an RDDMS dataspace into an OSDU manifest (WPCs, reference data, master data)
2. **Catalog ingest** — PUT the manifest records into OSDU Storage API with correct partition, ACL, and legal tags

---

## Authentication

All scripts use `demo/_auth.py` for token management:

```python
import sys; sys.path.insert(0, 'demo')
from _auth import get_token

token = get_token('interop')   # or 'eqndev', 'preship', etc.
```

Instance config is resolved from `k8s/configmap.yaml` + `k8s/secret.yaml` (pattern: `INSTANCE_<NAME>_*`).

---

## Step 1: Generate Manifest

### Option A: Remote RDDMS (instance's deployed ETP client)

```bash
TOKEN=$(python3 -c "import sys; sys.path.insert(0,'demo'); from _auth import get_token; print(get_token('interop', verbose=False))")

curl -s -X POST \
  https://admeinterop.energy.azure.com/api/reservoir-ddms/v2/manifests/build \
  -H "Authorization: Bearer $TOKEN" \
  -H "data-partition-id: opendes" \
  -H "Content-Type: application/json" \
  -d '{"uris":["eml:///dataspace('\''maap/drogon'\'')"],"createMissingReferences":true}' \
  -o /tmp/manifest.json
```

### Option B: Local RDDMS ETP client (recommended for development)

The local `~/rddms/open-etp-client` has the latest fixes (circular ref handling, name enrichment, spatial computation). Start it pointed at any instance's ETP:

```bash
cd ~/rddms && \
RDMS_ETP_HOST=admeinterop.energy.azure.com \
RDMS_ETP_PORT=443 \
RDMS_ETP_PROTOCOL=wss \
RDMS_ETP_PATH=/api/reservoir-ddms-etp/v2 \
RDMS_REST_PORT=3002 \
RDMS_REST_ROOT_PATH=/api/reservoir-ddms/v2/ \
RDMS_DATA_PARTITION_MODE=single \
RDMS_OSDU_URL=https://admeinterop.energy.azure.com \
RDMS_SSL_VERIFY=false \
node open-etp-client/dist/src/lib/restApi/RestServer.js > /tmp/rddms.log 2>&1 &
```

Then build manifest locally:

```bash
curl -s -m 120 -X POST \
  http://localhost:3002/api/reservoir-ddms/v2/manifests/build \
  -H "Authorization: Bearer $TOKEN" \
  -H "data-partition-id: opendes" \
  -H "Content-Type: application/json" \
  -d '{
    "uris": ["eml:///dataspace('\''maap/drogon'\'')"],
    "createMissingReferences": true,
    "typePatterns": ["*Feature","*Interpretation*","*Representation","*StratigraphicColumn"]
  }' \
  -o /tmp/manifest.json
```

**TypePatterns** controls which RESQML types become WPCs. Omit for all types. Common patterns:
- `*Representation` — Grid2d, PointSet, IjkGrid, WellboreFrame, PolylineSet
- `*Interpretation*` — Horizon, Fault, Wellbore, StratigraphicUnit, StratigraphicColumnRank
- `*Feature` — BoundaryFeature, RockVolumeFeature, ModelFeature, WellboreFeature
- `*StratigraphicColumn` — StratigraphicColumn objects

**`createMissingReferences: true`** auto-generates ReferenceData (CRS, ExistenceKind) and MasterData (Wellbores) needed for OSDU search/validation.

---

## Step 2: Ingest to Catalog

### Instance configuration

| Instance | Hostname | Partition | Legal Tag | Dataspace |
|----------|----------|-----------|-----------|-----------|
| **interop** | `admeinterop.energy.azure.com` | `opendes` | `opendes-ReservoirDDMS-Legal-Tag` | `maap/drogon` |
| **eqndev** | `equinorswedev.energy.azure.com` | `dev` | `dev-equinor-private-default` | `maap/drogon_dg` |
| **preship** | (see configmap) | (see configmap) | (see configmap) | varies |

### Python ingest script

```python
import json, requests, sys
sys.path.insert(0, 'demo')
from _auth import get_token

INSTANCE = 'interop'  # or 'eqndev'

# Instance-specific config
CONFIG = {
    'interop': {
        'base': 'https://admeinterop.energy.azure.com',
        'partition': 'opendes',
        'legal': {'legaltags': ['opendes-ReservoirDDMS-Legal-Tag'],
                  'otherRelevantDataCountries': ['US'], 'status': 'compliant'},
        'acl': {'owners': ['data.default.owners@opendes.dataservices.energy'],
                'viewers': ['data.default.viewers@opendes.dataservices.energy']},
    },
    'eqndev': {
        'base': 'https://equinorswedev.energy.azure.com',
        'partition': 'dev',
        'legal': {'legaltags': ['dev-equinor-private-default'],
                  'otherRelevantDataCountries': ['NO'], 'status': 'compliant'},
        'acl': {'owners': ['data.default.owners@dev.dataservices.energy'],
                'viewers': ['data.default.viewers@dev.dataservices.energy']},
    },
}

cfg = CONFIG[INSTANCE]
token = get_token(INSTANCE, verbose=False)
headers = {
    "Authorization": f"Bearer {token}",
    "data-partition-id": cfg['partition'],
    "Content-Type": "application/json"
}

# Load manifest
m = json.load(open('/tmp/manifest.json'))

# Collect all records
records = []
for section in ['ReferenceData', 'MasterData']:
    records.extend(m.get(section, []))
records.extend(m.get('Data', {}).get('WorkProductComponents', []))
records.extend(m.get('Data', {}).get('Datasets', []))

# Force correct legal/ACL for target instance
for r in records:
    r['legal'] = cfg['legal']
    r['acl'] = cfg['acl']

# Ingest in batches of 100
BATCH = 100
for i in range(0, len(records), BATCH):
    batch = records[i:i+BATCH]
    resp = requests.put(f"{cfg['base']}/api/storage/v2/records",
                        headers=headers, json=batch, timeout=60)
    if resp.status_code in (200, 201):
        print(f"Batch {i//BATCH+1}: {resp.json().get('recordCount', len(batch))} OK")
    else:
        print(f"Batch {i//BATCH+1}: FAILED {resp.status_code} - {resp.text[:200]}")
```

> **Note:** System reference data (ExistenceKind, CRS) may return 403 if already owned by another service principal. This is expected — those records already exist.

---

## Alternative: ORES Ingest API

The ORES app exposes a `/manifest/ingest` endpoint that handles ACL/legal rewriting server-side:

```python
import requests

resp = requests.post(
    "https://<ores-host>/manifest/ingest",
    headers={"Authorization": f"Bearer {token}"},
    json={
        "manifest": json.load(open('/tmp/manifest.json')),
        "method": "storage",         # or "workflow" for Osdu_ingest DAG
        "legalTag": "opendes-ReservoirDDMS-Legal-Tag",
        "owners": ["data.default.owners@opendes.dataservices.energy"],
        "viewers": ["data.default.viewers@opendes.dataservices.energy"],
        "countries": ["US"]
    }
)
print(resp.json())  # {"status": "submitted", "manifestId": "..."}
```

---

## Demo Pipeline Scripts

Scripts in `demo/drogon_dg2/` generate domain-specific manifests:

| Script | What it generates |
|--------|-------------------|
| `gen_maps_dg2.py` | StructureMap WPCs from horizon surfaces |
| `gen_grid_dg2.py` | IjkGrid + ContinuousProperty WPCs |
| `gen_polygons_dg2.py` | Polygon outlines (GenericRepresentation) |
| `gen_simtables_dg2.py` | Simulator volume tables |
| `gen_businessdecision_dg2.py` | BusinessDecision + PersistedCollection |
| `gen_collection_dg2.py` | PersistedCollection grouping all DG2 WPCs |
| `gen_risk_dg2.py` | Risk assessment records |
| `gen_activity_dg2.py` | Activity lineage |
| `gen_documents_dg2.py` | Document references |
| `manifest2records_dg2.py` | Split manifests → individual record files |
| `ingest_records_batch.py` | Batch PUT to Storage API |

### Running the full DG2 pipeline

```bash
cd demo/drogon_dg2

# Generate all manifests
python3 gen_maps_dg2.py
python3 gen_grid_dg2.py
python3 gen_polygons_dg2.py
python3 gen_simtables_dg2.py
python3 gen_businessdecision_dg2.py
python3 gen_collection_dg2.py

# Split into records and ingest
python3 manifest2records_dg2.py
python3 ingest_records_batch.py --instance interop
```

### Other useful demo scripts

| Script | Purpose |
|--------|---------|
| `demo/_auth.py` | Token management (`get_token(name)`) |
| `demo/ingest_demo.py` | Full demo ingest (DG1+DG2+Strat) to any instance |
| `demo/ingest_preship.py` | Ingest to pre-ship/external instances |
| `demo/ingest_weco_demos.py` | Ingest WeCo demo data to RDDMS |
| `demo/run_pipeline.py` | Generic `gen_*.py` script orchestrator |
| `demo/rotate_token.py` | Refresh token rotation |
| `demo/osdu_search.py` | Quick OSDU search queries |

---

## Local RDDMS ETP Client

The local `~/rddms/open-etp-client` contains fixes not yet in the deployed service:

1. **Circular reference handling** (`ResqmlClient.ts`) — `inProgress` Set prevents stack overflow on Interpretation↔Feature cycles
2. **Name enrichment** (`StructureMap.ts`, `GenericRepresentation.ts`) — Prefixes InterpretationName to Citation.Title when different
3. **Spatial + BinWidth** — Already computed from Grid2d lattice geometry

### Rebuild after changes

```bash
cd ~/rddms
npx tsc --project open-etp-client/tsconfig.json
# Then restart the server
```

### Environment variables

| Variable | Description | Example |
|----------|-------------|---------|
| `RDMS_ETP_HOST` | ETP WebSocket host | `admeinterop.energy.azure.com` |
| `RDMS_ETP_PORT` | ETP port | `443` |
| `RDMS_ETP_PROTOCOL` | `wss` or `ws` | `wss` |
| `RDMS_ETP_PATH` | ETP path | `/api/reservoir-ddms-etp/v2` |
| `RDMS_REST_PORT` | Local REST server port | `3002` |
| `RDMS_REST_ROOT_PATH` | API root | `/api/reservoir-ddms/v2/` |
| `RDMS_DATA_PARTITION_MODE` | `single` or `multi` | `single` |
| `RDMS_OSDU_URL` | OSDU base URL (for schema lookups) | `https://admeinterop.energy.azure.com` |
| `RDMS_SSL_VERIFY` | TLS verification | `false` |

---

## Known Issues

- **3 Grid2d volume tables** fail conversion (RESQML 2.0.1 uses Grid2d for tables; no lattice → converter skips them). In RESQML 2.2 these would be ColumnBasedTable.
- **PolylineSetRepresentation** converter assumes SeismicCoordinates exist — fails on fault sticks without seismic context.
- **System reference data** (ExistenceKind, CRS) may return 403 on ingest if already owned by another SP. Safe to ignore.
- **Search indexing** is async — records may take 30-60s to appear in search after Storage API PUT.
