# RDDMS / RESQML Stratigraphic Column Integration

## Overview

WeCo supports importing and exporting stratigraphic columns via the RDDMS
(RESQML Data & Domain Management Services) protocol and local EPC+H5 files.

This enables:

1. **Importing** well logs, markers, horizons, unit interpretations, and
   full stratigraphic columns from OSDU-compliant data stores.
2. **Mapping** stratigraphic hierarchy (Column → Rank → Unit → Horizon)
   onto WeCo region layers for correlation.
3. **Exporting** correlation results back to RDDMS as new markers,
   zonation, and horizon interpretations.
4. **Auto-detecting** the depositional environment from OSDU metadata
   and suggesting optimal engine parameters.

## Modules

| Module | Purpose |
|---|---|
| `weco.strat_column` | `StratColumn` model (Column / Rank / Unit / Horizon) |
| `weco.depenv` | Depositional environment preset library |
| `weco.osdu_auth` | OSDU authentication helper |
| `weco.rddms` | RDDMS read/write, RESQML ↔ WeCo converters |

## StratColumn Model

```python
from weco.strat_column import StratColumn

# From JSON file
col = StratColumn.from_json("strat_column.json")

# From Python dict
col = StratColumn.from_dict({
    "name": "North Sea Chalk",
    "ranks": [
        {
            "name": "System",
            "kind": "chrono",
            "units": [
                {"name": "Cretaceous", "top_age_ma": 66.0, "base_age_ma": 145.0},
                {"name": "Jurassic", "top_age_ma": 145.0, "base_age_ma": 201.3},
            ],
        }
    ],
    "horizons": [
        {"name": "Top Cretaceous", "age_ma": 66.0},
    ],
})

# From OSDU WPC records
col = StratColumn.from_osdu_bundle(records)

# Apply to wells
col.apply_to_well(well, well_picks=[
    {"unit_name": "Cretaceous", "top_md": 1200.0, "base_md": 2100.0},
    {"unit_name": "Jurassic", "top_md": 2100.0, "base_md": 3200.0},
])
```

## Depositional Environment Presets

WeCo ships 11 depositional environment presets that map OSDU vocabulary
to optimised engine parameters:

| Key | OSDU Names | Focus logs |
|---|---|---|
| `shallow_marine` | Shallow Marine, Shoreface, Shelf | GR, RHOB, DT |
| `deep_marine` | Deep Marine, Turbidite, Slope | GR, DEN, DT |
| `deltaic` | Deltaic, Delta, Prodelta | GR, SP, DEN |
| `fluvial` | Fluvial, Alluvial, Continental | GR, SP, RT |
| `lacustrine` | Lacustrine, Lake | GR, DEN, DT |
| `aeolian` | Aeolian, Eolian, Desert | GR, DEN, NPHI |
| `tidal` | Tidal, Tidal Flat, Estuarine | GR, SP, DEN |
| `carbonate` | Carbonate, Carbonate Platform | DEN, DT, GR |
| `reef` | Reef, Reefal | DEN, DT, NPHI |
| `coal` | Coal, Peat, Swamp | DEN, GR, RT |
| `glacial` | Glacial, Quaternary, Till | GR, RT, SPT |

```python
from weco.depenv import suggest_options, detect_environment

# Manual selection
opts = suggest_options("shallow_marine", data_names=["GR", "RHOB", "DT"])

# Auto-detect from strat column
env = detect_environment(strat_column)  # → "shallow_marine"
opts = suggest_options(env, data_names=wl.get_data_names())
```

## OSDU Authentication

```python
from weco.osdu_auth import get_token, osdu_headers

# Environment variables:
#   OSDU_TOKEN           — static bearer token
#   OSDU_TOKEN_URL       — OAuth2 token endpoint
#   OSDU_CLIENT_ID       — OAuth2 client ID
#   OSDU_CLIENT_SECRET   — OAuth2 client secret
#   OSDU_REFRESH_TOKEN   — OAuth2 refresh token
#   OSDU_SCOPE           — OAuth2 scope

token = get_token()
headers = osdu_headers(token, data_partition="my-partition")
```

## API Routes

### POST `/rddms/import`

Import wells from RDDMS or local EPC file.

```json
{
    "url": "https://rddms.example.com",
    "token": "...",
    "dataspace": "demo",
    "epc_file": null
}
```

### POST `/rddms/export`

Export correlation results to RDDMS.

```json
{
    "url": "https://rddms.example.com",
    "project_path": "/path/to/project",
    "export_markers": true,
    "export_zonation": true
}
```

### POST `/rddms/strat-column`

Import or inspect a stratigraphic column.

```json
{
    "column_json": "/path/to/strat_column.json",
    "action": "import"
}
```

### POST `/depenv/suggest`

Get suggested engine options for a depositional environment.

```json
{
    "environment": "Shallow Marine",
    "data_names": ["GR", "RHOB", "DT"]
}
```

## Horizon / Unit / Rank Import

### Horizons → No-crossing region

```python
from weco.rddms import import_horizons_as_region

import_horizons_as_region(well, [
    {"name": "Top_A", "md": 1200.0},
    {"name": "Top_B", "md": 1800.0},
], region_name="Horizons")
```

### Units → Zone region

```python
from weco.rddms import import_units_as_region

import_units_as_region(well, [
    {"name": "Sand_A", "top_md": 1200.0, "base_md": 1500.0},
    {"name": "Shale_B", "top_md": 1500.0, "base_md": 1800.0},
], region_name="UNIT")
```

### Hierarchical ranks → Multiple regions

```python
from weco.rddms import import_ranks_as_regions

import_ranks_as_regions(well, strat_column_dict, well_picks)
# Creates: Rank_System, Rank_Series, etc.
```

## Well Metadata

Wells now carry a `meta` dict for per-channel property metadata:

```python
well.meta["GR"]  # → {"uom": "gAPI", "kind": "continuous", "min": 20.0, "max": 150.0}
well.meta["DEN"] # → {"uom": "g/cm3", "kind": "continuous"}
```

This is populated automatically during RESQML/RDDMS import.
