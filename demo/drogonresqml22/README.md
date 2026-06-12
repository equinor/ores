# Drogon RESQML 2.2 Demo

Upgraded Drogon demo dataset using **RESQML 2.2** (from 2.0.1).  
Uses the OSDU RESQML 2.2 schema with updated type names and EML Common 2.3.

**Dataspace:** `maap/drogon22`  
**RESQML version:** 2.2  
**Manifest:** `manifest_drogon22_interop.json`

---

## Key Differences from RESQML 2.0.1

| Aspect | 2.0.1 (`drogonresqml`) | 2.2 (`drogonresqml22`) |
|--------|------------------------|------------------------|
| Dataspace | `maap/drogon` | `maap/drogon22` |
| Type prefix | `resqml20` | `resqml22` |
| Object prefix | `obj_ClassName` | `ClassName` (no `obj_` prefix) |
| Boundary features | `GeneticBoundaryFeature` + `TectonicBoundaryFeature` | Unified `BoundaryFeature` with `GeologicBoundaryKind` |
| Citation block | EML Common 2.0 | EML Common 2.3 |
| Property kinds | Custom XML reference | `PropertyKindIndex` + standard Energistics property kind dictionary |
| CRS | `LocalCrs` reference | `LocalEngineeringCompoundCrs` |
| UUID format | `obj_Type_uuid.xml` in EPC | `Type_uuid.xml` in EPC |
| Grid geometry | `IjkGridRepresentation` | `IjkGridRepresentation` (unchanged) |
| **Manifest records** | **161 records** | **173 records** (better 1:1 mapping = more explicit records) |

## OSDU Alignment Analysis

### Why RESQML 2.2 has better OSDU alignment

The OSDU data model was designed in parallel with RESQML 2.2 development. The result is
significantly better 1:1 mapping between Energistics types and OSDU schema kinds:

| Mapping Quality | 2.0.1 Count | 2.2 Count | Improvement |
|----------------|-------------|-----------|-------------|
| **Direct 1:1** | 7 types | 12 types | +5 direct mappings |
| **Many-to-one collapse** | 5 collapses | 2 collapses | 3 fewer lossy collapses |
| **Context-dependent** | 1 | 1 | Same (Grid2d → depth/time) |
| **Metadata-only (no record)** | 5 types | 4 types | Fewer objects lost |

### Improvements in detail

**1. BoundaryFeature (1:1, was 2:1 collapse)**

In 2.0.1, two separate types (`GeneticBoundaryFeature` + `TectonicBoundaryFeature`) collapsed
into one OSDU kind with the type distinction stored only as a `BoundaryType` attribute.
In 2.2, `BoundaryFeature` is already unified with `GeologicBoundaryKind` as an attribute -
this maps **directly** to `master-data--LocalBoundaryFeature` with no information loss.

**2. RockVolumeFeature (1:1, was renamed)**

In 2.0.1, `StratigraphicUnitFeature` had a misleading name that didn't match the OSDU kind
`LocalRockVolumeFeature`. In 2.2, the type is renamed to `RockVolumeFeature` - a **direct**
semantic match to the OSDU kind.

**3. Model (1:1, cleaner)**

`OrganizationFeature` (2.0.1) is renamed to `Model` (2.2), which maps 1:1 to
`LocalModelFeature` with clearer semantics.

**4. PropertyKindIndex (standard dictionary)**

In 2.0.1, property kinds used local XML `PropertyKind` objects that required custom
mapping to OSDU `reference-data--PropertyKind`. In 2.2, `PropertyKindIndex` references
the standard Energistics property kind dictionary - same dictionary OSDU uses.

**5. LocalEngineeringCompoundCrs (unified CRS)**

In 2.0.1, separate `LocalDepth3dCrs` and `LocalTime3dCrs` types existed. In 2.2,
`LocalEngineeringCompoundCrs` handles both domains, matching the single OSDU kind
`LocalModelCompoundCrs`.

### Remaining non-1:1 mappings (cannot avoid)

These are inherent architectural differences between RESQML's detailed object model
and OSDU's catalog abstraction:

| RESQML 2.2 | OSDU | Reason |
|---|---|---|
| `ContinuousProperty` + `DiscreteProperty` | `GenericProperty` | OSDU uses single "property" concept |
| `PolylineSetRepresentation` + `PointSetRepresentation` | `GenericRepresentation` | OSDU groups all "generic geometry" |
| `Grid2dRepresentation` | `StructureMap` or `SeismicHorizon` | Decision depends on CRS domain |
| `WellboreFrameRepresentation` + its properties | `WellLog` | Curves grouped under one record |

### RESQML 2.2 Type Mapping

| RESQML 2.0.1 Type | RESQML 2.2 Type | OSDU DDMSDataset URI |
|---|---|---|
| `resqml20.obj_GeneticBoundaryFeature(uuid)` | `resqml22.BoundaryFeature(uuid)` | `eml://reservoir-ddms1/dataspace('maap/drogon22')/resqml22.BoundaryFeature(uuid)` |
| `resqml20.obj_TectonicBoundaryFeature(uuid)` | `resqml22.BoundaryFeature(uuid)` | Same (distinguished by `GeologicBoundaryKind` attribute) |
| `resqml20.obj_HorizonInterpretation(uuid)` | `resqml22.HorizonInterpretation(uuid)` | `eml://reservoir-ddms1/dataspace('maap/drogon22')/resqml22.HorizonInterpretation(uuid)` |
| `resqml20.obj_FaultInterpretation(uuid)` | `resqml22.FaultInterpretation(uuid)` | `eml://reservoir-ddms1/dataspace('maap/drogon22')/resqml22.FaultInterpretation(uuid)` |
| `resqml20.obj_StructuralOrganizationInterpretation(uuid)` | `resqml22.StructuralOrganizationInterpretation(uuid)` | Similar |
| `resqml20.obj_IjkGridRepresentation(uuid)` | `resqml22.IjkGridRepresentation(uuid)` | Similar |
| `resqml20.obj_Grid2dRepresentation(uuid)` | `resqml22.Grid2dRepresentation(uuid)` | Similar |
| `resqml20.obj_ContinuousProperty(uuid)` | `resqml22.ContinuousProperty(uuid)` | Similar |
| `resqml20.obj_DiscreteProperty(uuid)` | `resqml22.DiscreteProperty(uuid)` | Similar |
| `resqml20.obj_WellboreFeature(uuid)` | `resqml22.WellboreFeature(uuid)` | Similar |
| `resqml20.obj_WellboreTrajectoryRepresentation(uuid)` | `resqml22.WellboreTrajectoryRepresentation(uuid)` | Similar |

---

## Dataset Content

Same Drogon structural model as the 2.0.1 demo, re-exported in RESQML 2.2 format:

| Component | Description |
|-----------|-------------|
| Horizons | 6 boundary features (MSL, TopVolantis, BaseVolantis, TopTherys, TopVolon, BaseVelmodel) |
| Faults | 6 boundary features (F1–F6) |
| Structural model | 1 StructuralOrganizationInterpretation |
| Grid | 1 IjkGrid (92×146×69 = 925,668 cells) |
| Grid properties | Continuous + Discrete properties on grid |
| Surfaces | Grid2d depth and TWT surfaces |
| Wells | 12 wellbores with trajectories and logs |
| Stratigraphy | Column + Rank + Units |

---

## Manifest Schema

The manifest uses the same OSDU `Manifest:1.0.0` envelope but with updated DDMSDataset URIs:

```
Old: eml://reservoir-ddms1/dataspace('maap/drogon')/resqml20.obj_GeneticBoundaryFeature(uuid)
New: eml://reservoir-ddms1/dataspace('maap/drogon22')/resqml22.BoundaryFeature(uuid)
```

OSDU catalog kinds remain the same (e.g., `master-data--LocalBoundaryFeature:1.1.0`) since they are version-agnostic wrappers around the DDMS content.
