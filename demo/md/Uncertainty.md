
# Uncertainty (FMU) in OSDU — Detailed Guide

> **Purpose**: Persist FMU ensemble / Monte Carlo **inputs**, **scenarios**, and **outputs** in OSDU; link **input design and static bundles** to **output volumes** by **Realisation**; use **Activity semantics** and **persisted collections** for robust provenance across DG1…DG4.

---

## 1. OSDU data model building blocks

### 1.1 Master‑data (anchors for scope)
- `master-data--Reservoir` — the reservoir entity of interest.  
- `master-data--ReservoirSegment` — segments or compartments under the reservoir.  
*Why:* `ReservoirEstimatedVolumes` is scoped by `ParentObjectID` to Field/Reservoir/ReservoirSegment.

### 1.2 Reference‑data (governed catalogs)
- **Units**: `reference-data--UnitOfMeasure` (e.g., `m3`, `Mm3`).  
- **Statistics facets**: `reference-data--FacetType:statistics`, `reference-data--FacetRole:{P10,P50,P90,ArithmeticMean,Minimum,Maximum,StandardDeviation}`.  
- **Canonical volume property types**: `reference-data--ReservoirEstimatedVolumePropertyType:{Bulk,Net,Pore,HydrocarbonPore,Oil,AssociatedGas}`.

### 1.3 Work‑product components (WPCs)
- **Design Matrix** — `work-product-component--ColumnBasedTable` (CBT).  
- **Static bundles** — grids, properties, velocity as WPCs (e.g., `GenericRepresentation`, `VelocityModeling`).  
- **Output volumes** — `work-product-component--ReservoirEstimatedVolumes` (REV), raw per‑realisation and aggregated statistics.  
- **Optional KPIs** — `work-product-component--ColumnBasedTable` for generic KPI/time series.

### 1.4 Collections for scenarios/cases
- **WorkProduct** — versioned case package (design + static bundle + chosen outputs).  
- **CollaborationProjectCollection** — curated working set while iterating.

### 1.5 Activity semantics (`AbstractProjectActivity`)
Use `Parameters[]` with `ParameterRole = input|output|context` and `ObjectParameterKey` to enumerate run inputs/outputs and context. Keys (e.g., `realisation-index`, `seed`) keep the mapping explicit.

---

## 2. Inputs — Design & static state

### 2.1 Design Matrix (CBT)
**Recommended schema pattern**:
- **KeyColumns**: `CaseID:string`, `Realisation:integer`, `Seed:integer` (optional).  
- **Columns**: parameter vector per row (e.g., `KxMultiplier:number`, `RelPermFamily:string`, `NTG_Shift:number`, …); use UCUM units in column metadata where relevant.  
- **Linkage**: referenced from Activities (run records) and joined to raw REV on `Realisation`.

**Example (excerpt)**:
```json
{
  "kind": "osdu:wks:work-product-component--ColumnBasedTable:1.3.0",
  "data": {
    "Name": "FMU Design Matrix — Case A",
    "KeyColumns": [
      {"ColumnName": "CaseID", "ColumnRole": "Key", "ValueType": "string"},
      {"ColumnName": "Realisation", "ColumnRole": "Key", "ValueType": "integer"},
      {"ColumnName": "Seed", "ColumnRole": "Key", "ValueType": "integer"}
    ],
    "Columns": [
      {"ColumnName": "KxMultiplier", "ValueType": "number"},
      {"ColumnName": "RelPermFamily", "ValueType": "string"}
    ]
  }
}
```

### 2.2 Static inputs (grids, properties, velocity)
Represent each artifact as a WPC and group the choice for a scenario into **one id**:
- **WorkProduct** = stable case package for DG usage.  
- **CollaborationProjectCollection** = flexible working set during model development.

---

## 3. Run bookkeeping with Activity parameters
For each run/iteration, create an Activity (or reuse `BusinessDecision` parameters if the run feeds a gate):
- **Parameters[] / input**: Design Matrix row (`realisation-index`), static bundle (WorkProduct/Collection), simulator deck/model.  
- **Parameters[] / output**: raw REV (this realisation), aggregate REV (per zone/segment).  
- **Parameters[] / context**: reservoir and segments; case collection.

**Example (schematic)**:
```json
{
  "Parameters": [
    {"Title": "Design row", "ParameterRole": "input",
     "Keys": [{"ParameterKey": "realisation-index", "StringParameterKey": "42"}],
     "ObjectParameterKey": "dev:work-product-component--ColumnBasedTable:design-matrix:1"},
    {"Title": "Static bundle", "ParameterRole": "input",
     "ObjectParameterKey": "dev:work-product--WorkProduct:caseA-static:3"},
    {"Title": "Raw volumes", "ParameterRole": "output",
     "Keys": [{"ParameterKey": "realisation-index", "StringParameterKey": "42"}],
     "ObjectParameterKey": "dev:work-product-component--ReservoirEstimatedVolumes:raw-42:1"},
    {"Title": "Aggregate volumes", "ParameterRole": "output",
     "ObjectParameterKey": "dev:work-product-component--ReservoirEstimatedVolumes:stats:5"}
  ]
}
```

**Naming keys**: use `realisation-index`, `seed`, `case-id` consistently; prefer camelCase or kebab‑case; avoid spaces.

---

## 4. Outputs — Volumes

### 4.1 Raw per‑realisation (REV)
Keys: `Realisation`, `Zone`, `SegmentID` with `KindID = master-data--ReservoirSegment:2.0.0`.  
Columns: `Bulk`, `Net`, `Pore`, `HydrocarbonPore`, `Oil`, `AssociatedGas` with `PropertyTypeID = reference-data--ReservoirEstimatedVolumePropertyType:<Prop>` and `UnitOfMeasureID` (e.g., `m3`).

**Example (excerpt)**:
```json
{
  "kind": "osdu:wks:work-product-component--ReservoirEstimatedVolumes:1.1.0",
  "data": {
    "ParentObjectID": "dev:master-data--Reservoir:...:1",
    "Volumes": {
      "KeyColumns": [
        {"ColumnName": "Realisation", "ColumnRole": "Key", "ValueType": "integer"},
        {"ColumnName": "Zone", "ColumnRole": "Key", "ValueType": "string"},
        {"ColumnName": "SegmentID", "ColumnRole": "Key", "ValueType": "string",
         "KindID": "osdu:wks:master-data--ReservoirSegment:2.0.0"}
      ],
      "Columns": [
        {"ColumnName": "Bulk", "ValueType": "number",
         "PropertyTypeID": "dev:reference-data--ReservoirEstimatedVolumePropertyType:Bulk:",
         "UnitOfMeasureID": "dev:reference-data--UnitOfMeasure:m3"}
      ]
    }
  }
}
```

### 4.2 Aggregated statistics (REV)
Keys: `Zone`, `SegmentID`.  
Columns: dot notation with facet annotation, e.g., `Bulk.P10`, `Oil.P50`, `AssociatedGas.StandardDeviation` with `FacetIDs = [{FacetTypeID: statistics, FacetRoleID: P10|P50|P90|ArithmeticMean|Minimum|Maximum|StandardDeviation}]`.

**Example (excerpt)**:
```json
{
  "kind": "osdu:wks:work-product-component--ReservoirEstimatedVolumes:1.1.0",
  "data": {
    "ParentObjectID": "dev:master-data--Reservoir:...:1",
    "Volumes": {
      "KeyColumns": [
        {"ColumnName": "Zone", "ColumnRole": "Key", "ValueType": "string"},
        {"ColumnName": "SegmentID", "ColumnRole": "Key", "ValueType": "string",
         "KindID": "osdu:wks:master-data--ReservoirSegment:2.0.0"}
      ],
      "Columns": [
        {"ColumnName": "Bulk.P10", "ValueType": "number",
         "PropertyTypeID": "dev:reference-data--ReservoirEstimatedVolumePropertyType:Bulk:",
         "UnitOfMeasureID": "dev:reference-data--UnitOfMeasure:m3",
         "FacetIDs": [{"FacetTypeID": "dev:reference-data--FacetType:statistics",
                         "FacetRoleID": "dev:reference-data--FacetRole:P10"}]}
      ]
    }
  }
}
```

---

## 5. Realisation mapping — keeping provenance tight
- **Join on keys**: raw REV `Realisation` ↔ Design Matrix row `Realisation`.  
- **Activity link**: the run Activity carries both the **design row** and the **raw REV output** with the same `realisation-index` key in `Parameters[]`.  
- **Case binding**: WorkProduct/Collection id referenced as `context` to bind the scenario.

---

## 6. Mermaid diagrams — no parentheses in labels

### 6.1 Data flow
```mermaid
flowchart LR
  DM[Design Matrix - CBT]
  SB[Static Bundle - Collection]
  RES[Reservoir]
  RSEG[ReservoirSegment]
  A[Activity Parameters - input output context]
  REV_RAW[Vol raw, keys Realisation Zone SegmentID]
  REV_AGG[Vol stats, keys Zone SegmentID - Facets]

  DM --> A
  SB --> A
  RES --> A
  RSEG --> A
  A --> REV_RAW
  A --> REV_AGG
  DM --- REV_RAW
```

### 6.2 Case packaging and DG alignment
```mermaid
flowchart LR
  CASE_WP[WorkProduct - FMU Case Package]
  DM[Design Matrix]
  STATIC_SET[Static Bundle]
  REV_RAW[Vol raw]
  REV_AGG[Vol stats]
  BD[BusinessDecision - DG]

  CASE_WP --- DM
  CASE_WP --- STATIC_SET
  CASE_WP --- REV_RAW
  CASE_WP --- REV_AGG
  BD --- CASE_WP
  BD --- REV_AGG
```

### 6.3 Entities and relations
```mermaid
erDiagram
  Reservoir ||--o{ ReservoirSegment : segments
  WorkProduct ||--o{ GenericRepresentation : includes
  WorkProduct ||--o{ VelocityModeling : includes
  WorkProduct ||--o{ ColumnBasedTable : includes
  Activity ||--o{ WorkProduct : context
  Activity ||--o{ ColumnBasedTable : input
  Activity ||--o{ ReservoirEstimatedVolumes : output
  ColumnBasedTable }o--|| ReservoirEstimatedVolumes : realisation-join
```

---

## 7. Conventions and tips
- **Column names**: use dot notation for statistics; avoid spaces and parentheses in labels.  
- **Keys**: always include `Realisation` in raw outputs; keep `SegmentID` aligned to `ReservoirSegment` ids.  
- **Units**: prefer `m3` unless business rules require `Mm3`; carry units in `UnitOfMeasureID`.  
- **Facet roles**: use `ArithmeticMean` and `StandardDeviation` (not Average/StDev) for consistency.  
- **Legal/ACL**: apply Equinor DEV tags on all records; group artefacts under a WorkProduct per DG when promoting.

---

## 8. Where to read more
- ReservoirEstimatedVolumes and Reservoir Management worked examples (schema ER and examples).
- ColumnBasedTable usage for reservoir data; Schema usage guide; Activity semantics; WorkProduct and CollaborationProjectCollection docs.

