# Stratigraphic Column — Reproducible Build Workflow

> Step-by-step guide to regenerate **OSDU Stratigraphic Column** manifests
> (chrono reference data, strat column, horizons) from scratch.
>
> All commands assume **PowerShell** from the repository root.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | `py --version` |
| `osducli` | Only for deploy steps — `pip install osducli` |
| Source data | Chrono JSON in `demo/strat/` (e.g. `ChronoStratigraphy.1.json`) |
| Mapping file | `demo/strat/ow2osdu.map.json` (OpenWorks → OSDU name mapping) |

---

## Pipeline at a Glance

```text
Source chrono data
      │
      ▼
[7genchronostratics.py]  →  manifest_chronostratics.json  (ref-data)
      │
      ▼
[7genstratcolumn.py]     →  manifest_stratcolumn.json    (column + ranks + units)
      │
      ▼
[10genhorizons.py]       →  manifest_stratcolumn.json    (+ horizons + ages on units)
      │
      ▼
[7manifest2records.py]   →  individual record files       (for osducli)
      │
      ▼
[9deploy_chronostratics.py] → OSDU platform (chrono)
[8deploy_stratcolumn.py]    → OSDU platform (column + units + horizons)
```

---

## Step-by-Step

### Step 0 — Verify / prepare source data

Ensure `demo/strat/ChronoStratigraphy.1.json` (or similar) contains the
raw ICS chrono records for your target scheme(s).

```powershell
# quick sanity check
(Get-Content .\demo\strat\ChronoStratigraphy.1.json | ConvertFrom-Json).Count
```

### Step 1 — Generate chrono reference-data manifest

```powershell
py .\demo\py\7genchronostratics.py --verbose
# Optional: generate only one scheme
py .\demo\py\7genchronostratics.py --filter-scheme ICS2017 --verbose
```

**Output:** `demo/strat/manifest_chronostratics.json`

Verify:
- 0 duplicates
- 0 `{{NAMESPACE}}` placeholders

### Step 2 — Generate strat column manifest (units + ranks)

```powershell
py .\demo\py\7genstratcolumn.py --verbose
```

**Output:** `demo/strat/manifest_stratcolumn.json`

This creates:
- 1 StratigraphicColumn record
- N StratigraphicColumnRankInterpretation records (one per rank)
- M StratigraphicUnitInterpretation records (one per unit)
- 1 StratigraphicRoleType reference-data record

### Step 3 — Generate horizons and backfill ages

```powershell
py .\demo\py\10genhorizons.py --verbose
# Also write a standalone horizon manifest:
py .\demo\py\10genhorizons.py --verbose --out-horizons .\demo\strat\manifest_horizons.json
```

**What this does:**
1. Reads chrono manifest → extracts `AgeBegin` / `AgeEnd` per chrono record
2. Matches each unit to its linked chrono record via `ChronoStratigraphyID`
3. Generates one `HorizonInterpretation` WPC per unique boundary age
4. Updates each unit with:
   - `OlderPossibleAge` / `YoungerPossibleAge`
   - `ColumnStratigraphicHorizonTopID` / `ColumnStratigraphicHorizonBaseID`
5. Appends horizon WPCs to the strat column manifest

**Output:** Updated `demo/strat/manifest_stratcolumn.json` (units + horizons)

### Step 4 — Split manifests to individual record files

```powershell
# Chrono records
py .\demo\py\7manifest2records.py `
    --in .\demo\strat\manifest_chronostratics.json `
    --outdir .\demo\strat\chronostrat_records `
    --namespace dev

# Strat column records (units + horizons + ranks)
py .\demo\py\7manifest2records.py `
    --in .\demo\strat\manifest_stratcolumn.json `
    --outdir .\demo\strat\stratcolumn_records `
    --namespace dev
```

### Step 5 — Consistency check (recommended)

```powershell
py .\demo\py\_consistency_check.py
```

Expected output:
- 0 duplicates on both manifests
- 0 `{{NAMESPACE}}` on both
- All ChronoStratigraphyIDs cross-match
- All Horizon IDs resolve
- Record file counts match manifest counts

### Step 6 — Deploy to OSDU

Deploy chrono reference data **first** (units depend on it):

```powershell
py .\demo\py\9deploy_chronostratics.py --verbose
# Or filter to one scheme:
py .\demo\py\9deploy_chronostratics.py --filter-scheme ICS2017 --verbose
```

Then deploy strat column (column + ranks + units + horizons):

```powershell
py .\demo\py\8deploy_stratcolumn.py --verbose
```

---

## Adapting for a Different Column

To generate a column for a **different scheme** (e.g. GTS2020 lithostratigraphy,
a local well-pick column, etc.):

1. **Prepare source data** — place raw records or mapping JSON in `demo/strat/`
2. **Adjust `7genstratcolumn.py`** — update the column token, scheme name, and
   record-builder if the source structure differs
3. **Re-run Steps 1–6** above
4. For non-chrono columns (litho, bio), horizon generation may need different
   age sources — edit `10genhorizons.py` or skip that step if ages are already
   on the unit records

### Key configuration points

| Parameter | Where | Default |
|---|---|---|
| Partition / namespace | All scripts `--partition` | `dev` |
| Column token | `7genstratcolumn.py`, `10genhorizons.py` `--column-token` | `ChronoStratigraphicScheme-ICS2017` |
| ACL owners/viewers | All scripts `--owners` / `--viewers` | Equinor dev defaults |
| Legal tag | All scripts `--legaltag` | `dev-equinor-osdu-reference-default` |

---

## Script Reference

| # | Script | Purpose |
|---|--------|---------|
| 7 | `7genchronostratics.py` | Generate chrono ref-data manifest from source |
| 7 | `7genstratcolumn.py` | Generate strat column manifest (column + ranks + units) |
| 7 | `7manifest2records.py` | Split any manifest into individual record JSONs |
| 8 | `8deploy_stratcolumn.py` | Deploy strat column records to OSDU via osducli |
| 9 | `9deploy_chronostratics.py` | Deploy chrono records to OSDU via osducli |
| 10 | `10genhorizons.py` | Generate horizons from chrono ages, update units |
| — | `_consistency_check.py` | Cross-manifest validation (duplicates, refs, files) |
