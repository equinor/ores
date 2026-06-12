# RDDMS Manifest Builder – Deficiency Report

**Component:** `open-etp-client` REST API – `POST /api/reservoir-ddms/v2/manifests/build`  
**Version tested:** `open-etp-client-main:latest` (community.opengroup.org:5555)  
**Test dataset:** Drogon demo EPC – 404 RESQML 2.0.1 objects (12 wells, IjkGrid, structural framework, stratigraphy, 254 properties)  
**Date:** 2026-05-20  

---

## Summary

The manifest builder produces **101 WPC records + 1 ETPDataspace dataset** from a 404-object EPC.  
A complete manifest should produce **~144 records** (1 dataset + 24 master-data + 119 WPCs).  

**Missing entirely:** 78 well objects + 222 well-log properties (= 300 objects → 0 records)  
**Type misclassification:** Grid2d depth surfaces → `GenericRepresentation` instead of `StructureMap`  
**No master-data section:** Features and wellbores should be master-data, not WPCs  

---

## Issues

### 1. Well objects produce zero records – by design (DDMS ownership)

**Severity:** **By design** 
**Impact:** Well data is absent from the RDDMS-built manifest - acceptable if Well DDMS owns it  

The builder produces no records for any well-related RESQML type:

| RESQML Type | Count in EPC | Records produced | Expected OSDU kind |
|---|---|---|---|
| WellboreFeature | 12 | 0 | `master-data--Wellbore:1.3.0` |
| WellboreInterpretation | 12 | 0 | (grouped into Wellbore) |
| WellboreTrajectoryRepresentation | 12 | 0 | `work-product-component--WellboreTrajectory:1.3.0` |
| DeviationSurveyRepresentation | 12 | 0 | (grouped into WellboreTrajectory) |
| MdDatum | 12 | 0 | (referenced by WellboreTrajectory) |
| WellboreFrameRepresentation | 9 | 0 | `work-product-component--WellLog:1.2.0` |
| WellboreMarkerFrameRepresentation | 9 | 0 | `work-product-component--WellboreMarkerSet:1.2.0` |

**Why this is acceptable:**  
Wells are typically *not* managed by RDDMS. The canonical owner of `Wellbore`
master-data and well WPCs (trajectories, logs, markers) is **Well DDMS**. RDDMS
may host *copies* of well arrays (e.g. for cross-referencing from structural
models), but should not be the system of record.

This means:
- `master-data--Wellbore` records should already exist (created by Well DDMS or well ingestion pipeline)
- RDDMS WPCs that reference wells (grid properties computed along wellbores, etc.) should use `WellboreID` to cross-reference existing Wellbore records, not create new ones
- The manifest builder is correct to *not* emit Wellbore master-data if RDDMS is not the owner

**See also:** §10 (OSDU multi-DDMS copy model) below.  

---

### 2. Well-log properties (on WellboreFrame) produce zero records

**Severity:** Critical  
**Impact:** 222 log curves are invisible in the catalog  

| RESQML Type | Total in EPC | Produced | On IjkGrid (produced) | On WellboreFrame (missing) |
|---|---|---|---|---|
| ContinuousProperty | 189 | 27 | 27 | 162 |
| DiscreteProperty | 65 | 5 | 5 | 60 |

The builder correctly maps properties attached to `IjkGridRepresentation` as `GenericProperty` WPCs, but completely ignores properties attached to `WellboreFrameRepresentation`.

**Expected behaviour:**  
Properties on a `WellboreFrameRepresentation` should be grouped into the parent `WellLog` WPC as curve metadata (name, UoM, property kind, min/max).

---

### 3. Grid2dRepresentation mapped as GenericRepresentation instead of StructureMap / SeismicHorizon

**Severity:** Medium  
**Impact:** Depth surfaces and time surfaces cannot be found by kind-specific searches; apps querying for `StructureMap` or `SeismicHorizon` won't find them  

The builder maps all 9 `Grid2dRepresentation` objects to `work-product-component--GenericRepresentation:1.2.0` with metadata:
```json
"Type": "osdu:reference-data--RepresentationType:Regular2DGrid:",
"Role": "osdu:reference-data--RepresentationRole:Map:"
```

**Expected behaviour:**  
- Grid2d with `LocalDepth3dCrs` → `work-product-component--StructureMap:1.0.0`  
- Grid2d with `LocalTime3dCrs` → `work-product-component--SeismicHorizon:2.1.0`  

The CRS reference is already available on the record (`LocalModelCompoundCrsID`), so the builder has the information needed to differentiate.

---

### 4. No master-data section – LocalBoundaryFeature and Wellbore belong in MasterData

**Severity:** Medium  
**Impact:** OSDU search by master-data kind fails; features are in the wrong section of the manifest  

The builder places `LocalBoundaryFeature` (12 records for horizons + faults) in the `WorkProductComponents` array. In the OSDU data model, geologic features and wellbores are master-data entities.

**Current output:**
```json
{
  "Data": {
    "Datasets": [...],
    "WorkProductComponents": [
      { "kind": "osdu:wks:work-product-component--LocalBoundaryFeature:1.2.0", ... }
    ]
  }
}
```

**Expected:**
```json
{
  "Data": {
    "Datasets": [...],
    "MasterData": [
      { "kind": "osdu:wks:master-data--LocalBoundaryFeature:1.1.0", ... },
      { "kind": "osdu:wks:master-data--Wellbore:1.3.0", ... }
    ],
    "WorkProductComponents": [...]
  }
}
```

Also, `LocalBoundaryFeature` should include a `BoundaryType` field distinguishing `"horizon"` (from `GeneticBoundaryFeature`) vs `"fault"` (from `TectonicBoundaryFeature`).

---

### 5. StructuralOrganizationInterpretation not mapped

**Severity:** Medium  
**Impact:** Structural models / earth models are not represented in the catalog  

| RESQML Type | Count | Records | Expected OSDU kind |
|---|---|---|---|
| StructuralOrganizationInterpretation | 1 | 0 | `work-product-component--StructuralModel:1.0.0` |

**Expected behaviour:**  
Map to `StructuralModel` WPC with cross-references:
- `InterpretedFeatureID` → OrganizationFeature (LocalModelFeature)
- `FaultInterpretationIDs[]` → all FaultInterpretation WPCs
- `HorizonInterpretationIDs[]` → all HorizonInterpretation WPCs

---

### 6. PropertyUoM not populated despite PropertyUnitID being present

**Severity:** Low  
**Impact:** Users cannot filter/search by unit-of-measure string without resolving the reference-data ID  

The builder populates `PropertyUnitID` (e.g. `osdu:reference-data--UnitOfMeasure:m3:`) but leaves `PropertyUoM` empty.

```json
{
  "PropertyUnitID": "osdu:reference-data--UnitOfMeasure:m3:",
  "PropertyUoM": ""   // ← should be "m3"
}
```

The UoM string is directly available in the RESQML XML (`<resqml2:UOM>m3</resqml2:UOM>`) and should be copied to `PropertyUoM` for convenience searching.

---

### 7. No SpatialArea / bounding box on any record

**Severity:** Low  
**Impact:** Spatial search (map-based discovery) is impossible  

No WPC or master-data record includes a `SpatialArea` or bounding box. For representations that have explicit geometry (Grid2d, IjkGrid, PolylineSet, PointSet, WellboreTrajectory), the builder should compute and populate:

```json
"SpatialArea": {
  "Wgs84Coordinates": {
    "type": "Polygon",
    "coordinates": [[[lon1,lat1],[lon2,lat2],...]]
  }
}
```

This requires CRS → WGS84 transformation, which may be non-trivial, but at minimum the builder could populate a local XY extent.

---

### 8. Record ID format uses `osdu:` prefix instead of partition ID

**Severity:** Low (cosmetic but causes issues in multi-partition environments)  
**Impact:** IDs don't match the pattern used by Storage/Workflow service (`{partition}:kind:uuid`)  

**Current:**
```
osdu:work-product-component--FaultInterpretation:67eb8600-bc7b-4f34-87ce-ed4c2cb287e8
osdu:dataset--ETPDataspace:demo-drogon
```

**Expected:**
```
opendes:work-product-component--FaultInterpretation:67eb8600-bc7b-4f34-87ce-ed4c2cb287e8
opendes:dataset--ETPDataspace:1.0.1:demo-drogon
```

The partition should come from the `data-partition-id` header. The current `osdu:` prefix is a placeholder that doesn't work with actual Storage service ingest.

Cross-reference IDs also have a trailing colon (`osdu:...:uuid:`) which is non-standard.

---

### 9. Dataset ID format inconsistent

**Severity:** Low  
**Impact:** Cannot correlate dataset across manifest sections  

The ETPDataspace dataset record has:
```json
"id": "osdu:dataset--ETPDataspace:demo-drogon"
```

But the schema version is missing (`ETPDataspace:1.0.1`) and the dataspace path uses a hyphen (`demo-drogon`) instead of preserving the original path or UUID.

---

### 10. ActivityTemplate not mapped

**Severity:** Low  
**Impact:** Provenance chain is incomplete  

`ActivityTemplate` (1 object) is not included in the manifest. The builder maps `Activity` to `Activity:1.4.0` but not the template that defines it.

---

## OSDU Multi-DDMS Ownership & Copy Model

### The Problem

An EPC file bundles *everything* - wells, structural surfaces, grids, properties -
into a single archive. But in OSDU, different Domain Data Management Services (DDMSes)
own different data types:

| DDMS | Owns (system of record) |
|---|---|
| Well DDMS | `master-data--Wellbore`, `WellboreTrajectory`, `WellLog`, `WellboreMarkerSet` |
| Reservoir DDMS | `IjkGridRepresentation`, `GenericProperty`, `StructureMap`, `SeismicHorizon`, structural interpretations |
| Seismic DDMS | `SeismicBinGrid`, seismic traces/volumes |

When RDDMS ingests an EPC containing wells, it stores the *array data* locally
(trajectories, logs in RDDMS backing store), but the catalog records should defer
to Well DDMS for ownership of the metadata.

### OSDU Design Principles for Multi-DDMS

1. **Single record ID, multiple `DatasetIDs`**  
   A WPC record (e.g. `WellboreTrajectory`) has exactly one ID in Storage. The
   `DatasetIDs[]` array can list multiple backing stores:
   ```json
   {
     "id": "opendes:work-product-component--WellboreTrajectory:1.3.0:uuid",
     "data": {
       "DatasetIDs": [
         "opendes:dataset--WellDDMS:...",
         "opendes:dataset--ETPDataspace:1.0.1:demo-drogon"
       ]
     }
   }
   ```
   This means the same record is accessible from *both* Well DDMS and RDDMS.

2. **Master-data is partition-global**  
   `master-data--Wellbore` records are not DDMS-specific. They exist once in the
   platform and all DDMSes reference them by ID. RDDMS should never create a
   *duplicate* Wellbore record with a different UUID.

3. **UUID stability**  
   If RDDMS and Well DDMS both describe the same physical wellbore trajectory,
   they must use the **same UUID** (derived from the RESQML object UUID). Creating
   a second record with a new UUID for the same physical entity violates the
   OSDU single-source-of-truth principle.

4. **Ownership vs Reference**  
   - A manifest that *creates* records is asserting ownership.
   - A manifest that *references* existing IDs (e.g. `WellboreID: "opendes:master-data--Wellbore:..."`)
     is deferring ownership to whoever created that record.
   - RDDMS should reference well master-data, not re-create it.

### Practical Strategies

| Scenario | Strategy | Manifest Action |
|---|---|---|
| Well DDMS exists, has wellbores | Reference only | Use existing Wellbore IDs in `WellboreID` fields; don't emit MasterData for wells |
| No Well DDMS (standalone demo) | Create all | Emit Wellbore master-data + well WPCs in RDDMS manifest |
| RDDMS hosts well array copies | Append DatasetID | PATCH existing WPC records to add RDDMS dataset URI to `DatasetIDs[]` |
| UUID conflict (same object, different UUIDs) | Reconcile | Use RESQML UUID as canonical; if Well DDMS used a different UUID, create an alias/mapping |

### What `build_full_manifest.py` Does

Our comprehensive manifest builder creates well records *intentionally* for the
demo scenario (no Well DDMS present). If targeting an instance that already has
well data from Well DDMS, the pipeline should:

1. Query existing `master-data--Wellbore` records by name
2. If found: use their IDs in `WellboreID` cross-references, skip master-data creation
3. If not found: create them (demo mode)

This is handled by the `--skip-wells` flag (not yet implemented - see TODO).

### Implications for RDDMS Manifest Builder (open-etp-client)

The builder's current behaviour of *not* emitting well records is defensible given
DDMS ownership boundaries. However, it should:

- Still emit `WellboreTrajectory` / `WellLog` / `WellboreMarkerSet` WPCs with
  `WellboreID` pointing to expected master-data IDs (using RESQML UUIDs)
- Provide a mode switch: `--include-wells` for standalone scenarios
- Document the assumption that Well DDMS owns Wellbore master-data

---

## Comparison: Builder Output vs Expected

| Metric | Builder | `build_full_manifest.py` | Gap (builder vs full) |
|---|---|---|---|
| Total records | 102 | 145 | -43 |
| Datasets | 1 | 1 | - |
| MasterData | 0 | 24 | -24 |
| WPCs | 101 | 120 | -19 |
| RESQML types covered | 18/28 | 26/28 | -8 types |
| DomainTypeID on interp | ✓ (Depth only) | ✓ (Mixed - correct) | wrong value |
| StratigraphicRoleTypeID | ✓ | ✓ | - |
| Shared BinGrid | ✗ | ✓ (1 GenericBinGrid, 9 refs) | -1 record |
| Grid geometry inline | ✗ | ✓ (NodeCount, spacing, origin) | missing fields |
| Horizon-specific names | ✗ | ✓ ("Surface (TopVolantis)") | generic names |
| Well-specific names | ✗ (no well records) | ✓ ("Well Log (55/33-A-1)") | no records |
| BinGridID on surfaces | ✗ | ✓ | missing cross-ref |
| Objects with catalog presence | 101/404 | 402/404 | -301 objects |
| Cross-ref fields populated | 4 types | 8 types | -4 |
| Spatial extent | 0% | 0% (open) | - |

*Note: 222 well-log ContinuousProperty objects are expected to be grouped into 9 WellLog WPCs (not 222 separate records), which is why "objects with catalog presence" differs from "total records".*

---

## What the builder does well

- Correct FIRP cross-refs on representations: `InterpretationID`, `LocalModelCompoundCrsID`
- Correct FIRP cross-refs on interpretations: `FeatureID`, `FeatureName`
- `PropertyTopologyID` linking grid properties to their supporting IjkGrid
- `PropertyUnitID` as reference-data link (even if PropertyUoM string is empty)
- `IndexableElementCount` with correct element types (`cells`, `nodes`)
- `RepresentationType` and `RepresentationRole` metadata on GenericRepresentation
- `DomainTypeID` (Depth/Time) on interpretations
- `StratigraphicRoleTypeID` on HorizonInterpretation
- Good `Description` generation from RESQML Citation + field context
- `Min/MaxValue` on properties
- `CreationDateTime` from Citation.Creation

---

## Proposed issue titles (for git tracker)

1. **[manifest-builder] Well objects (Feature, Trajectory, Frame, Markers) produce no catalog records**
2. **[manifest-builder] Well-log properties on WellboreFrame not mapped to WellLog WPCs**
3. **[manifest-builder] Grid2dRepresentation should map to StructureMap / SeismicHorizon based on CRS domain**
4. **[manifest-builder] LocalBoundaryFeature and Wellbore should be in MasterData section (not WPCs)**
5. **[manifest-builder] StructuralOrganizationInterpretation not mapped to StructuralModel**
6. **[manifest-builder] PropertyUoM field empty despite UOM available in RESQML XML**
7. **[manifest-builder] No SpatialArea / bounding box computed for spatial search**
8. **[manifest-builder] Record IDs use `osdu:` prefix instead of partition from request header**
9. **[manifest-builder] ActivityTemplate not included in manifest output**

---

## RDDMS Service / Platform Issues

Issues observed on the RDDMS REST/ETP service itself (not the manifest builder logic).

### 11. Underscore in dataspace name causes manifest/build HTTP 500

**Severity:** Medium  
**Observed:** 2026-05-10  
**Workaround:** Avoid underscores in dataspace names (use `/` path separators)  

`POST /manifests/build` with a dataspace containing `_` (e.g. `maap/drogon_osdu`) returns 500.
Dataspaces without underscores work fine.

---

### 12. POST /dataspaces returns 400 with HTML body (M26 regression)

**Severity:** High  
**Observed:** 2026-05-10 on swedev (was working before M26 upgrade)  

`POST /api/reservoir-ddms/v2/dataspaces` returns HTTP 400 with an HTML page body
("OsduUi - Home" with Equinor design tokens) instead of a JSON error.

Likely cause: OSDU API gateway routing change in M26 intercepts the POST before
it reaches the RDDMS service.

Payload sent (known-good format):
```json
[{"DataspaceId":"maap/olympus","Path":"maap/olympus",
  "CustomData":{"legaltags":[...],"owners":[...],...}}]
```

---

### 13. ETP Authorize timeout (M26 regression)

**Severity:** High  
**Observed:** 2026-05-10  

`wss://equinorswedev.energy.azure.com/api/reservoir-ddms-etp/v2/`  
ETP `Core(0).Authorize(6)` times out. The WebSocket connection opens but the
Authorize handshake never completes. App registration `ebd2bfee` had working
access before M26.

---

### 14. REST listing lacks top-level UUID/ContentType keys

**Severity:** Low  
**Impact:** Clients must parse EML URIs to extract UUID and type  

`GET /resources` returns `{"uri": "eml:///dataspace('ds')/type(uuid)"}` without
explicit `uuid` or `contentType` fields. Every client must implement a regex parser.

**Requested:** Add `uuid`, `contentType`, `title` as top-level keys in list responses.

---

### 15. No bulk query / filtered listing API

**Severity:** Medium  
**Impact:** N+1 roundtrips in deep_search (list → get each)  

No server-side filtering, type filtering, or bulk-get endpoint. Clients must
list all objects then GET each one individually.

**Requested:** `typeSearch` or `bulkGet` endpoint with optional content-type filter.

---

### 16. No dataspace metadata / description field

**Severity:** Low  
**Impact:** Dataspaces are opaque identifiers with no discoverable metadata  

**Requested:** Add optional `description`, `owner`, `createdDate` fields to dataspace records.

---

### 17. CORS / WebSocket headers for browser-based ETP

**Severity:** Low (deferred)  
**Impact:** Browser-based ETP clients cannot connect without a proxy  

The ETP WebSocket endpoint doesn't include CORS headers. Low priority since
ETP clients are typically server-side.
