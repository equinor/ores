# WeCo Demo RESQML Ingestion

Scripts for generating and ingesting WeCo demo well data into RDDMS instances.

## Quick Start

```bash
# 1. Generate RESQML JSON payloads from local demo datasets
python demo/resqml/generate_payloads.py

# 2. Ingest into RDDMS (requires Azure AD token)
python demo/resqml/ingest_wells.py --token-file ~/.azure/token.json

# 3. Ingest into all instances
python demo/resqml/ingest_wells.py --all --token-file ~/.azure/token.json
```

## Target Dataspace

All demo data goes into `maap/weco` on each instance:
- **eqndev** (default) — development
- **preship** — pre-ship testing
- **interop** — interoperability testing

## Datasets

| Dataset | Wells | Logs | Description |
|---------|-------|------|-------------|
| shallow_marine | 10 | GR, RT, RHOB, NPHI, DT | Hugin Fm analogue — prograding shoreface |
| coal | 10 | GR, RT, RHOB | Coal basin seam correlation |
| quaternary | 20 | GR, RT | Glacial/hydrogeology wells |

## Output Structure

```
demo/resqml/payloads/
├── manifest.json
├── shallow_marine/
│   ├── wells.json      (WellboreTrajectoryRepresentation)
│   ├── logs.json       (ContinuousProperty per well/log)
│   └── regions.json    (DiscreteProperty — facies, biozones)
├── coal/
│   ├── wells.json
│   ├── logs.json
│   └── regions.json
└── quaternary/
    ├── wells.json
    ├── logs.json
    └── regions.json
```

## CI/CD Integration

To run ingestion from a pipeline (e.g. ORES demo ingestion pipeline):

```bash
# Set token via environment variable
export RDDMS_TOKEN="$(az account get-access-token --resource https://storage.azure.com --query accessToken -o tsv)"

# Ingest all datasets to all instances
python demo/resqml/ingest_wells.py --all
```

## Overriding Instance URLs

Set environment variables to override default RDDMS URLs:

```bash
export RDDMS_URL_EQNDEV="https://custom-rddms.example.com/api/v2"
export RDDMS_URL_PRESHIP="https://..."
export RDDMS_URL_INTEROP="https://..."
```
