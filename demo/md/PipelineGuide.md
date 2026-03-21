# Pipeline Guide — Adding a New Field and Decision Gate Dataset to OSDU

This guide explains how to take raw FMU/volumetric data for a new field (or a new decision gate for an existing field), generate all the necessary OSDU records, and ingest them so they appear in the ORES web client.

---

## 1. Data input format

### 1.1 Volume CSV

The pipeline expects a **CSV file** with one row per realisation × zone × segment (× facies, if applicable).

**Minimum required columns:**

| Column | Type | Description |
|--------|------|-------------|
| `Realisation` | int | Realisation/iteration index (0, 1, 2, …) |
| `Zone` | string | Reservoir zone name |
| `SegmentID` | string | Reservoir segment name (must match segment master data) |

**Volume columns** (one or more, all in **m³**):

| Column | PropertyType | Description |
|--------|-------------|-------------|
| `Bulk` | `Bulk` | Gross rock volume |
| `Pore` | `Pore` | Pore volume (Bulk × φ) |
| `HydrocarbonPoreOil` | `HydrocarbonPore` | HCPV for oil zone |
| `Oil` | `Oil` | STOIIP (stock-tank oil in place) |
| `Gas` | `Gas` | GIIP (gas initially in place) |
| `AssociatedGas` | `AssociatedGas` | Solution gas |
| `AssociatedLiquid` | `AssociatedLiquid` | Condensate in gas column |

Additional columns (`BulkOil`, `BulkGas`, `PoreOil`, `PoreGas`, `HydrocarbonPoreGas`, etc.) are supported — see `VOLUME_COLUMNS` in `genrawmanifest_drogon.py`.

**Optional extra key column:**

| Column | Type | Description |
|--------|------|-------------|
| `Facies` | string | Facies type for facies-dependent analysis (e.g. Channel, Crevasse, Floodplain) |

### 1.2 Parameters CSV (optional)

A separate CSV with input parameters per realisation:

| Column | Type | Description |
|--------|------|-------------|
| `Realisation` | int | Must match the volume CSV |
| `Zone` | string | Zone name |
| `SegmentID` | string | Segment name |
| Custom columns | number | e.g. `OilWaterContact_WestLowland`, `Porosity_Channel` |

### 1.3 Units

All volume values must be in **m³** (cubic metres). The web client converts to **MSm³** (million standard cubic metres) for display using `value / 1,000,000`.

Depths are in **m** (metres). Porosities are **fractions** (0–1, Euclidean).

---

## 2. Supported properties and facets

### 2.1 Volume property types

The pipeline uses `reference-data--ReservoirEstimatedVolumePropertyType` records. The standard set includes:

**OSDU open values:** `TotalGas`, `Non-AssociatedGas`, `AssociatedGas`, `Oil`, `Gas`, `Condensate`, `Water`, `Hydrocarbon`, `Petroleum`, etc.

**Equinor extensions:** `BulkOil`, `BulkGas`, `BulkTotal`, `NetOil`, `NetGas`, `NetTotal`, `PorvOil`, `PorvGas`, `PorvTotal`, `HcpvOil`, `HcpvGas`.

To **add a new property type**, add it to the `PROPERTY_SPECS` list in `genrefpropertytypes_drogon.py`:

```python
PROPERTY_SPECS = [
    # ... existing entries ...
    ("MyNewProperty", "Description of the new property type."),
]
```

Then regenerate: `python demo/drogon/genrefpropertytypes_drogon.py`

### 2.2 Statistical facets (FacetRoles)

Statistics computed from raw realisations. Default set:

| Code | Name |
|------|------|
| `P10` | 10th percentile |
| `P50` | 50th percentile (median) |
| `P90` | 90th percentile |
| `ArithmeticMean` | Arithmetic mean |
| `Minimum` | Minimum value |
| `Maximum` | Maximum value |
| `StardardDeviation` | Standard deviation |
| `GeometricMean` | Geometric mean |
| `HarmonicMean` | Harmonic mean |

To **add a new facet** (e.g. `P25`), add it to the `FACET_ROLES` list in `genreffacetrole_drogon.py`:

```python
FACET_ROLES = [
    # ... existing entries ...
    ("P25", "P25"),
]
```

Then also update `genstatmanifest_drogon.py` to compute the new percentile.

---

## 3. Step-by-step: adding a new field

### 3.1 Prepare the data

1. Export FMU results to a CSV matching the format in §1.1
2. Place the CSV in your pipeline directory (e.g. `demo/myfield/`)
3. Copy the Drogon pipeline scripts as a starting template:

```bash
mkdir -p demo/myfield
cp demo/drogon/genrefpropertytypes_drogon.py  demo/myfield/genrefpropertytypes.py
cp demo/drogon/genreffacetrole_drogon.py      demo/myfield/genreffacetrole.py
cp demo/drogon/genmaster_drogon.py            demo/myfield/genmaster.py
cp demo/drogon/genrawmanifest_drogon.py       demo/myfield/genrawmanifest.py
cp demo/drogon/genstatmanifest_drogon.py      demo/myfield/genstatmanifest.py
cp demo/drogon/gen_risk_drogon.py             demo/myfield/gen_risk.py
cp demo/drogon/gen_businessdecision_drogon.py demo/myfield/gen_bd.py
cp demo/drogon/manifest2records_drogon.py     demo/myfield/manifest2records.py
cp demo/drogon/ingest_records_batch.py        demo/myfield/ingest_records.py
cp demo/drogon/_shared.py                     demo/myfield/_shared.py
```

### 3.2 Customise the scripts

**`genmaster.py`** — configure your field's reservoir and segments:

```python
RESERVOIR_NAME = "MyField"
RESERVOIR_DESC = "My Field reservoir description"

# Define your segments
SEGMENTS = [
    {"Name": "NorthBlock",  "Description": "Northern fault block"},
    {"Name": "SouthBlock",  "Description": "Southern compartment"},
    {"Name": "Totals",      "Description": "Field total"},
]
```

**`genrawmanifest.py`** — update `VOLUME_COLUMNS` to match your CSV columns:

```python
VOLUME_COLUMNS = [
    ("Oil",  "Oil",  "m3"),
    ("Gas",  "Gas",  "m3"),
    ("Bulk", "Bulk", "m3"),
    ("Pore", "Pore", "m3"),
    # Add more as needed
]
```

**`genstatmanifest.py`** — adjust grouping keys if you don't use facies:

```python
# For a simple Zone × Segment grouping (no facies):
GROUP_KEYS = ["Zone", "SegmentID"]    # remove "Facies" if not applicable
```

**`gen_bd.py`** — update field name, decision level, descriptions, risks, etc.

### 3.3 Generate and ingest

```bash
cd /path/to/repo
python demo/myfield/genrefpropertytypes.py
python demo/myfield/genreffacetrole.py
python demo/myfield/genmaster.py
python demo/myfield/genrawmanifest.py
python demo/myfield/genstatmanifest.py
python demo/myfield/gen_risk.py
python demo/myfield/gen_bd.py
python demo/myfield/manifest2records.py
python demo/myfield/ingest_records.py --delay 3
```

### 3.4 Verify in the web client

1. Open **OsduSearch** → search for `master-data--BusinessDecision`
2. Your new BD should appear with headline volumes and linked records
3. Open **Analyse** → select your Reservoir → compare across decision gates

---

## 4. Adding a new decision gate (DG) to an existing field

If you already have a Reservoir and DG1 in OSDU, adding DG2/DG3/DG4 is simpler:

### 4.1 Via the "Add DG" web page

The **Add DG** page (`/add-dg`) lets you create a new BusinessDecision interactively:

1. Select a Reservoir from the dropdown
2. Choose the decision level (DG1–DG4)
3. Fill in the metadata (name, dates, summary, approval status)
4. Link existing OSDU records (REV-stats, REV-raw, GeoLabelSet, Activity, Risk)
5. Click **Create & Ingest** to PUT the record to OSDU

### 4.2 Via the pipeline scripts

1. Copy the DG1 BD generator and modify for DG2:

```bash
cp demo/drogon/gen_businessdecision_drogon.py demo/drogon_dg2/gen_businessdecision_dg2.py
```

2. Update the decision level, dates, descriptions, and linked record IDs
3. Generate new volume data (if changed) or reference existing WPCs
4. Run the manifest generator and ingest

### 4.3 Record linkage pattern

A BusinessDecision links to its data using `Parameters[]`:

```json
{
  "Parameters": [
    {
      "Title": "Statistical volumes",
      "DataObjectParameter": "<REV-stats record ID>",
      "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "REV-stats"}]
    },
    {
      "Title": "Raw volumes",
      "DataObjectParameter": "<REV-raw record ID>",
      "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "REV-raw"}]
    },
    {
      "Title": "GeoLabelSet",
      "DataObjectParameter": "<GeoLabelSet record ID>",
      "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "GeoLabelSet"}]
    },
    {
      "Title": "Reservoir scope",
      "DataObjectParameter": "<Reservoir record ID>"
    }
  ]
}
```

The `Keys[].StringParameterKey` values (`REV-stats`, `REV-raw`, `GeoLabelSet`, `ColumnBasedTable-params`, `ETPDataspace`) are used by the web client to identify which Parameter holds which artifact.

---

## 5. OSDU record types used

| Kind | Purpose | Linkage |
|------|---------|---------|
| `master-data--Reservoir:2.0.0` | Field/reservoir anchor | Parent of segments |
| `master-data--ReservoirSegment:2.0.0` | Reservoir compartment | `ancestry.parents` → Reservoir |
| `work-product:1.0.0` | Container for WPCs | Groups related WPCs |
| `work-product-component--ReservoirEstimatedVolumes:1.1.0` | Volume data (raw or stats) | `ParentObjectID` → Reservoir |
| `work-product-component--ColumnBasedTable:1.4.0` | Generic tabular data (parameters) | `ParentObjectID` → Reservoir |
| `work-product-component--GeoLabelSet:1.0.0` | Headline KPI values for dashboard | `ParentObjectID` → Reservoir |
| `work-product-component--Activity:1.0.0` | Workflow provenance | Links inputs → outputs |
| `work-product-component--Document:1.0.0` | Documents (SRA, CRA, PDO) | Referenced from BD |
| `master-data--BusinessDecision:1.0.0` | Decision gate record | `Parameters[]` links everything |
| `master-data--Risk:1.0.0` | Risk records | `RiskIDs` from BD |
| `reference-data--ReservoirEstimatedVolumePropertyType:1.0.0` | Volume property type catalog | Used in REV column metadata |
| `reference-data--FacetRole:1.1.0` | Statistical facet catalog | Used in stat REV column metadata |

---

## 6. Extending the pipeline

### 6.1 Adding new volume properties

1. Add the property code to `PROPERTY_SPECS` in `genrefpropertytypes_drogon.py`
2. Add the CSV column mapping to `VOLUME_COLUMNS` in `genrawmanifest_drogon.py`
3. The stat generator will automatically compute P10/P50/P90 for the new column
4. The GeoLabelSet generator will pick up the new property if it's a headline metric

### 6.2 Adding new facies types

1. Add the facies name to your CSV (in the `Facies` column)
2. Update `SEGMENT_NAMES` in `_shared.py` if needed
3. The pipeline handles facies automatically through grouping

### 6.3 Adding new statistical measures

1. Add the facet to `FACET_ROLES` in `genreffacetrole_drogon.py`
2. Add the computation in `genstatmanifest_drogon.py` (in the percentile/aggregation section)
3. Add display support in `search.html` if it's a new headline metric

### 6.4 Adding new record types to BD

1. Generate the new record type (e.g. a custom WPC)
2. Add a new `Parameters[]` entry in `gen_businessdecision_drogon.py` with appropriate `Keys`
3. Update the web client enrichment in `app/main.py` to handle the new key tag
