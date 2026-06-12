# Drogon OSDU Demo – Data Model & Catalog Reference

OSDU catalog reference for the Drogon structural interpretation dataset.  
Covers the record inventory, FIRP relationships, and domain conventions.

**Target instance:** `interop` (admeinterop.energy.azure.com/opendes)
**Dataspace:** `demo/drogon` (RDDMS)  

---

## 1. Record Inventory

### 1.1 Summary

| Section | Records | Description |
|---|---|---|
| Datasets | 1 | ETPDataspace link to RDDMS |
| MasterData | 24 | Geologic features (12) + Wellbores (12) |
| WorkProductComponents | 120 | Interpretations, representations, properties, shared BinGrid |
| **Total** | **145** | |

### 1.2 Datasets

| Kind | Name | ID |
|---|---|---|
| `dataset--ETPDataspace:1.0.1` | demo/drogon | `{p}:dataset--ETPDataspace:1.0.1:demo-drogon` |

### 1.3 Master Data

| Kind | Count | Records |
|---|---|---|
| `master-data--LocalBoundaryFeature:1.1.0` | 12 | 6 horizons (TopVolantis, BaseVolantis, TopTherys, TopVolon, BaseVelmodel, MSL) + 6 faults (F1–F6) |
| `master-data--Wellbore:1.3.0` | 12 | 55/33-1, -2, -3, A-1 to A-6, OP5_Y1, OP5_Y2, OP6 |

LocalBoundaryFeature carries `BoundaryType`:
- `"horizon"` → GeneticBoundaryFeature (6)
- `"fault"` → TectonicBoundaryFeature (6)

### 1.4 Work Product Components

| Kind | Count | Description | Key Cross-References |
|---|---|---|---|
| `GenericProperty:1.2.0` | 32 | Grid cell properties (porosity, perm, saturation) | → IjkGridRepresentation (SupportingRepresentationID) |
| `GenericRepresentation:1.2.0` | 19 | Fault sticks (PolylineSet ×6) + horizon/fault picks (PointSet ×13) | → FaultInterpretation/HorizonInterpretation (InterpretationID), → CRS |
| `WellboreTrajectory:1.3.0` | 12 | Well paths (XYZ + MD) | → Wellbore (WellboreID), → CRS |
| `WellLog:1.2.0` | 9 | Log frames (222 curves grouped into 9 WPCs) | → Wellbore (WellboreID) |
| `WellboreMarkerSet:1.2.0` | 9 | Stratigraphic markers per well | → Wellbore (WellboreID) |
| `StructureMap:1.0.0` | 7 | Depth surfaces (Grid2d on LocalDepth3dCrs) | → HorizonInterpretation, → BinGrid, → CRS |
| `HorizonInterpretation:1.2.0` | 6 | Geologic meaning of each horizon | → LocalBoundaryFeature; DomainTypeID=Mixed, StratRole=Chronostratigraphic |
| `FaultInterpretation:1.3.0` | 6 | Geologic meaning of each fault | → LocalBoundaryFeature (InterpretedBoundaryFeatureID) |
| `LocalRockVolumeFeature:1.2.0` | 5 | Stratigraphic unit features | |
| `StratigraphicUnitInterpretation:1.3.0` | 5 | Formation interpretations | → LocalRockVolumeFeature (InterpretedFeatureID) |
| `SeismicHorizon:2.1.0` | 2 | TWT surfaces (Grid2d on LocalTime3dCrs) | → HorizonInterpretation, → BinGrid, → CRS |
| `GenericBinGrid:1.0.0` | 1 | Shared 280×440 lattice (25m spacing) for all surfaces | → CRS |
| `LocalModelCompoundCrs:1.2.0` | 2 | Depth CRS + Time CRS | |
| `StructuralModel:1.0.0` | 1 | Structural framework (6 faults + 6 horizons) | → all FaultInterpretation + HorizonInterpretation |
| `IjkGridRepresentation:1.1.0` | 1 | Geogrid 92×146×69 (925,668 cells) | → CRS |
| `StratigraphicColumn:1.2.0` | 1 | Vertical succession | |
| `StratigraphicColumnRankInterpretation:1.3.0` | 1 | 5-unit rank | |
| `LocalModelFeature:1.2.0` | 1 | Earth model feature (OrganizationFeature) | |

---

## 2. FIRP Data Model

The OSDU data model uses a **Feature → Interpretation → Representation → Property** (FIRP) hierarchy.

### 2.1 Structural Framework

```
master-data--LocalBoundaryFeature ◄── HorizonInterpretation ──► StructureMap (depth)
  (BoundaryType: "horizon")              │                   ──► SeismicHorizon (time)
  "TopVolantis"                          │                   ──► GenericRepresentation (picks)
                                         │
                                         └── DomainTypeID: Mixed (has both depth + time reps)

master-data--LocalBoundaryFeature ◄── FaultInterpretation ──► GenericRepresentation (sticks)
  (BoundaryType: "fault")                                   ──► GenericRepresentation (picks)
  "F1"

LocalModelFeature ◄── StructuralModel
  "Earth model"         ├── FaultInterpretationIDs[] (×6)
                        └── HorizonInterpretationIDs[] (×6)
```

### 2.2 DomainType Convention

| Level | Field | Value | Explanation |
|---|---|---|---|
| **Interpretation** | `DomainTypeID` | `osdu:reference-data--DomainType:Mixed:` | Has both depth and time representations |
| **StructureMap** | `VerticalDomain` | `"depth"` | Grid2d on LocalDepth3dCrs |
| **SeismicHorizon** | `VerticalDomain` | `"time"` | Grid2d on LocalTime3dCrs |
| **GenericRepresentation** | (via CRS) | depth or time | Inferred from `CoordinateReferenceSystemID` |

**Why "Mixed" on interpretations?**  
A `HorizonInterpretation` for TopVolantis has representations in *both* domains:
a StructureMap (depth) and a SeismicHorizon (time). The interpretation itself is
domain-agnostic - it describes the geologic meaning. The domain is a property of
each representation, not the interpretation. OSDU uses `DomainTypeID: Mixed` to
indicate that the interpretation spans both depth and time.

If an interpretation only had depth representations (no TWT picks), it would use
`DomainTypeID: Depth`.

### 2.3 Wells

```
master-data--Wellbore ◄── WellboreTrajectory (well path)
  "55/33-A-1"         ◄── WellLog (222 curves in 9 frames)
                      ◄── WellboreMarkerSet (stratigraphic picks)
```

### 2.4 Reservoir Model

```
IjkGridRepresentation (92×146×69) ◄── GenericProperty (×32)
  "Geogrid"                              (porosity, perm, saturation, facies)
       │
       └── StratigraphicOrganization → StratigraphicColumnRankInterpretation
                                            └── StratigraphicUnitInterpretation (×5)
                                                     └── LocalRockVolumeFeature
```

### 2.5 Cross-Reference Summary

| From Kind | Field | To Kind | Count |
|---|---|---|---|
| HorizonInterpretation | `InterpretedBoundaryFeatureID` | LocalBoundaryFeature | 6 |
| FaultInterpretation | `InterpretedBoundaryFeatureID` | LocalBoundaryFeature | 6 |
| StructureMap | `InterpretedHorizonID` | HorizonInterpretation | 7 |
| SeismicHorizon | `InterpretedHorizonID` | HorizonInterpretation | 2 |
| GenericRepresentation | `InterpretationID` | Fault/HorizonInterpretation | 19 |
| StructuralModel | `FaultInterpretationIDs[]` | FaultInterpretation | 6 |
| StructuralModel | `HorizonInterpretationIDs[]` | HorizonInterpretation | 6 |
| StructuralModel | `InterpretedFeatureID` | LocalModelFeature | 1 |
| GenericProperty | `SupportingRepresentationID` | IjkGridRepresentation | 32 |
| WellboreTrajectory | `WellboreID` | Wellbore | 12 |
| WellLog | `WellboreID` | Wellbore | 9 |
| WellboreMarkerSet | `WellboreID` | Wellbore | 9 |
| All representations | `CoordinateReferenceSystemID` | LocalModelCompoundCrs | 41 |
| StructureMap / SeismicHorizon | `BinGridID` | GenericBinGrid | 9 |
| All WPCs | `DatasetIDs[]` | ETPDataspace | 120 |

---

## 3. StructureMap & BinGrid Patterns

Depth surfaces use `StructureMap:1.0.0`. Two grid-definition strategies:

### Pattern A+B – Inline Grid + Shared BinGrid (used in this demo)

All 9 surfaces (7 depth + 2 time) share the same 280×440 lattice at 25m spacing.
Each StructureMap/SeismicHorizon carries both inline geometry AND a `BinGridID`
reference to a single shared `GenericBinGrid:1.0.0` record:

```json
{
  "kind": "osdu:wks:work-product-component--StructureMap:1.0.0",
  "data": {
    "Name": "Depth Surface - Interpreted (TopVolantis)",
    "VerticalDomain": "depth",
    "BinGridID": "→ GenericBinGrid:1.0.0 (shared lattice)",
    "NodeCountOnIAxis": 280,
    "NodeCountOnJAxis": 440,
    "IncrementOnIAxis": 25.0,
    "IncrementOnJAxis": 25.0,
    "OriginX": 461500.0,
    "OriginY": 5926500.0,
    "InterpretedHorizonID": "→ HorizonInterpretation",
    "CoordinateReferenceSystemID": "→ LocalModelCompoundCrs (depth)",
    "DDMSDatasets": ["eml://reservoir-ddms1/dataspace('demo/drogon')/resqml20.obj_Grid2dRepresentation(...)"]
  }
}
```

The shared BinGrid record:
```json
{
  "kind": "osdu:wks:work-product-component--GenericBinGrid:1.0.0",
  "data": {
    "Name": "Drogon Surface Grid (shared lattice)",
    "NodeCountOnIAxis": 280,
    "NodeCountOnJAxis": 440,
    "IncrementOnIAxis": 25.0,
    "IncrementOnJAxis": 25.0,
    "OriginX": 461500.0,
    "OriginY": 5926500.0
  }
}
```

The BinGrid is the authoritative lattice definition; inline fields are duplicated
for convenience (apps that don't resolve cross-refs can still read geometry).
Actual Z-values remain in RDDMS (Grid2dRepresentation arrays).

### Pattern C – External BinGrid Only (no inline)

Alternative for when inline duplication is undesirable:
```json
{
  "kind": "osdu:wks:work-product-component--StructureMap:1.0.0",
  "data": {
    "BinGridID": "→ GenericBinGrid:1.0.0",
    "InterpretedHorizonID": "→ HorizonInterpretation",
    "DDMSDatasets": [...]
  }
}
```

The `GenericBinGrid` record defines the reusable lattice (origin, spacing, node counts, bearing).

### Pattern D – SeismicBinGrid (acquisition surveys)

For TWT horizons on seismic surveys:
```json
{
  "kind": "osdu:wks:work-product-component--SeismicHorizon:2.1.0",
  "data": {
    "VerticalDomain": "time",
    "SeismicBinGridID": "→ SeismicBinGrid:1.3.0",
    "InterpretedHorizonID": "→ HorizonInterpretation",
    "DDMSDatasets": [...]
  }
}
```

The `SeismicBinGrid` uses P6 vector definitions (inline/crossline geometry with arbitrary orientation).

### Grid Kind Selection

| Surface Type | OSDU Kind | Domain | Grid Reference |
|---|---|---|---|
| Depth surface (structural) | `StructureMap:1.0.0` | depth | BinGridID or inline |
| TWT surface (interpretation) | `SeismicHorizon:2.1.0` | time | SeismicBinGridID |
| Any (RDDMS catalog fallback) | `GenericRepresentation:1.2.0` | either | via CRS |

---

## 4. CRS

| Record | Projected CRS | Vertical | Z Direction | Domain |
|---|---|---|---|---|
| LocalModelCompoundCrs (depth) | ED50 / UTM zone 37S | MSL (m) | Z increasing down | depth |
| LocalModelCompoundCrs (time) | ED50 / UTM zone 37S | TWT (ms) | Z increasing down | time |

All representations reference one of these two CRS records via `CoordinateReferenceSystemID`.

---

## 5. Grid Properties (32 on IjkGrid)

| Property | UoM | Category |
|---|---|---|
| Total Porosity | v/v | Geo-model |
| Horizontal Permeability | mD | Geo-model |
| Vertical Permeability | mD | Geo-model |
| Phyllosilicate Volume Fraction | v/v | Geo-model |
| Shale Volume | v/v | Geo-model |
| Net Sand Fraction | v/v | Geo-model |
| Facies (discrete) | Euc | Geo-model |
| Oil Bulk Volume | m3 | Sim derived |
| Water/Oil/Gas Saturation | v/v | Sim init |
| Pore/Bulk Volumes | m3 | Sim derived |
| Temperature | degC | Sim |
| Fault Block Index, Distance | m | Structure |
| Free Water Level, GOC Depth | m | Contacts |
| Net-to-Gross Ratio | v/v | Petro-elastic |
| Region/Saturation Region (SATNUM) | Euc | Sim init |
| Zone Index | Euc | Sim derived |

---

## 6. Well Log Curves (222 across 9 wells)

Each `WellLog:1.2.0` record groups ~24 curves from a `WellboreFrameRepresentation`:

| Curve | UoM | Category |
|---|---|---|
| Total Porosity, Horizontal Permeability | v/v, mD | Reservoir |
| Acoustic/Shear Impedance, Vp/Vs | Pa, Euc | Elastic |
| P-Wave/S-Wave Velocity, Bulk Density | m/s, kg/m3 | Petrophysics |
| Seismic Near Amplitude, Relative AI | Euc | Seismic |
| Facies, Coal/Calcite Indicator | Euc | Discrete |
| Shale Volume, Phyllosilicate Volume | v/v | Clay |
| Water Saturation, Zone Index | v/v, Euc | Sim |

---

## 7. Horizons & Faults

### 7.1 Horizons (6)

| Feature | Interpretation | StructureMap (depth) | SeismicHorizon (time) |
|---|---|---|---|
| TopVolantis | TopVolantis | ✓ Interpreted | ✓ Interpreted |
| BaseVolantis | BaseVolantis | ✓ Interpreted + Velocity Model | ✓ Interpreted |
| TopTherys | TopTherys | ✓ Interpreted + Velocity Model | - |
| TopVolon | TopVolon | ✓ Interpreted | - |
| BaseVelmodel | BaseVelmodel | ✓ Interpreted | - |
| MSL | MSL | ✓ Interpreted | - |

### 7.2 Faults (6)

| Feature | Interpretation | Fault Sticks (PolylineSet) | Fault Picks (PointSet) |
|---|---|---|---|
| F1 | F1 | ✓ TWT sticks | ✓ Depth + Time picks |
| F2 | F2 | ✓ TWT sticks | ✓ Depth + Time picks |
| F3 | F3 | ✓ TWT sticks | ✓ Depth + Time picks |
| F4 | F4 | ✓ TWT sticks | ✓ Depth + Time picks |
| F5 | F5 | ✓ TWT sticks | ✓ Depth + Time picks |
| F6 | F6 | ✓ TWT sticks | ✓ Depth + Time picks |

### 7.3 Structural Model

`StructuralModel:1.0.0` ("Drogon Structural Framework") groups all 6 horizons
and 6 faults into a single structural organization, ordered by geologic age.

---

## 9. Known Limitations

| Issue | Impact | Status |
|---|---|---|
| No `SpatialArea` (bounding box) | Map-based spatial search won't find records | **Open** - needs CRS→WGS84 transform |
| ~~No inline grid geometry on StructureMap~~ | ~~App can't render without RDDMS call~~ | **Fixed** - NodeCount, spacing, origin populated |
| ~~StructureMap names not horizon-specific~~ | ~~Multiple generic names~~ | **Fixed** - "Depth Surface - Interpreted (TopVolantis)" |
| ~~SeismicHorizon names not specific~~ | ~~"Time Surface - Interpreted" ×2~~ | **Fixed** - "Time Surface - Interpreted (BaseVolantis)" |
| ~~No `DomainTypeID` on HorizonInterpretation~~ | ~~Can't filter by domain~~ | **Fixed** - `Mixed` on all 6 |
| ~~No `StratigraphicRoleTypeID`~~ | ~~Missing role~~ | **Fixed** - `Chronostratigraphic` on all 6 |
| ~~WellLog names generic~~ | ~~Not useful~~ | **Fixed** - "Well Log (55/33-A-1)" |
| ~~No shared BinGrid~~ | ~~Grid geometry duplicated/missing~~ | **Fixed** - 1 GenericBinGrid, all surfaces reference via BinGridID |
