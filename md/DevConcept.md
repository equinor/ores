# DevelopmentConcept - Schema & Data Model

> **Schema version**: `dev:wks:work-product-component--DevelopmentConcept:4.0.0`
> **Schema source**: [`demo/drogon_dg1/schema_devconcept.json`](../demo/drogon_dg1/schema_devconcept.json)

---

## 1. Purpose

A **DevelopmentConcept** WPC captures what a subsurface team proposes to build for a given decision gate: facility layout, well plan, drainage strategy, reservoir target, and production technology choices.

It is a **pure leaf** - it does not carry economics, schedule, production forecast, risks, documents or activity history. Those belong on the **BusinessDecision** (the hub record). The DevConcept is linked from the BD via `Parameters[]` with key `DevelopmentConcept`.

## 2. Architecture - BD Hub + DevConcept Leaf

```
BusinessDecision (master-data, the hub)
  |
  +-- Parameters[]:
  |     [0] REV-raw          -> ReservoirEstimatedVolumes WPC
  |     [1] REV-stats        -> ReservoirEstimatedVolumes WPC (P10/P50/P90)
  |     [2] GeoLabelSet      -> GeoLabelSet WPC
  |     [3] ProductionForecast -> ColumnBasedTable WPC
  |     [4] DevelopmentConcept -> DevelopmentConcept WPC  <-- this record
  |     [5] PersistedCollection -> Evidence Package WPC
  |
  +-- RiskIDs[]              -> Risk master-data
  +-- ext.* extensions       -> Economics, Schedule, Authors, Alternatives
```

## 3. Schema Structure (v4.0.0)

Five structured sub-objects plus top-level scalars. All fields are optional except `Name`.

### Top-level fields

| Field | Type | Description |
|---|---|---|
| `Name` | string (required) | Short name |
| `Description` | string | Full description |
| `Summary` | string | Executive summary |
| `DecisionGate` | enum | `DG0`–`DG4` |
| `DecisionLevelID` | ref-data ID | -> `reference-data--DecisionLevel` |
| `ConceptID` | string | Prior gate DevConcept (lineage) |
| `ParentObjectID` | string | Reservoir master-data ID |

### 3.1 FacilityConcept

| Field | Type | Notes |
|---|---|---|
| `FacilityType` | enum | `SubseaTieback`, `StandaloneFPSO`, `FixedPlatform`, etc. |
| `FacilityTypeID` | ref-data ID | -> `reference-data--FacilityType` |
| `HostFacility` | string | Host facility name |
| `HostFacilityID` | master-data ID | -> `master-data--GenericFacility` |
| `TemplateCount` | integer | Number of subsea templates |
| `SlotsPerTemplate` | integer | Well slots per template |
| `Flowlines[]` | array | Type, Diameter_in, Length_km, Count, Material |
| `SubseaBoostingPump` | boolean | |
| `ArtificialLift` | enum | `GasLift`, `ESP`, `SRP`, `PCP`, `JetPump`, `None` |
| `ArtificialLiftTypeID` | ref-data ID | -> `reference-data--ArtificialLiftType` |
| `WaterDepth_m` | number | |
| `DistanceToHost_km` | number | |

### 3.2 WellPlan

| Field | Type | Notes |
|---|---|---|
| `Producers` | integer | |
| `Injectors` | integer | |
| `ContingentWells` | integer | Provisioned but uncommitted |
| `WellTypes[]` | array | Type, Count, TargetZone, AvgLength_mMD |
| `AvgWellDepth_mMD` | number | |
| `CompletionType` | string | |
| `SandControl` | string | |
| `InflowControl` | string | ICD / AICD / autonomous |

### 3.3 DrainageStrategy

| Field | Type | Notes |
|---|---|---|
| `PrimaryRecoveryMechanism` | enum | `WaterInjection`, `GasInjection`, `WAG`, `NaturalDepletion`, etc. |
| `ReservoirDriveMechanismTypeID` | ref-data ID | -> `reference-data--ReservoirDriveMechanismType` |
| `InjectionType` | enum | `Water`, `Gas`, `WAG`, `Polymer`, `CO2`, `Steam`, `None` |
| `DevelopmentPhases[]` | array | Phase, Description, Wells, StartDate |

### 3.4 ReservoirTarget

| Field | Type | Notes |
|---|---|---|
| `FormationName` | string | Lithostratigraphic formation (display label) |
| `FormationID` | WPC ID | -> StratigraphicUnitInterpretation (`UnitType=formation`) |
| `GroupName` | string | Lithostratigraphic group (display label) |
| `GroupID` | WPC ID | -> StratigraphicUnitInterpretation (`UnitType=group`) |
| `Age` | string | Chronostratigraphic age (display label) |
| `AgeID` | ref-data ID | -> `reference-data--ChronoStratigraphy` |
| `FieldID` | master-data ID | -> `master-data--Field` |
| `DepthRange_mTVDMSL` | object | `{ Min, Max }` |
| `Zones[]` | string[] | Targeted zone names |
| `ZoneIDs[]` | WPC IDs | -> StratigraphicUnitInterpretation records |
| `ReservoirSegmentIDs[]` | master-data IDs | -> `master-data--ReservoirSegment` |

### 3.5 ProductionTechnology

| Field | Type | Notes |
|---|---|---|
| `SandManagement` | string | |
| `ScaleRisk` | string | |
| `CorrosionStrategy` | string | |
| `MeteringStrategy` | string | |

## 4. OSDU Reference-Data Integration

The schema provides `*ID` fields alongside human-readable labels. This dual approach ensures records are both human-readable and machine-linkable.

### 4.1 Reference-data types used

| Field | OSDU Entity |
|---|---|
| `FacilityTypeID` | `reference-data--FacilityType` |
| `ArtificialLiftTypeID` | `reference-data--ArtificialLiftType` |
| `ReservoirDriveMechanismTypeID` | `reference-data--ReservoirDriveMechanismType` |
| `DecisionLevelID` | `reference-data--DecisionLevel` |
| `AgeID` | `reference-data--ChronoStratigraphy` |

### 4.2 Lithostratigraphic references

Zone, formation and group are **lithostratigraphic** concepts. In OSDU:
- **`master-data--StratigraphicUnitFeature`** (the rock body itself)
- **`work-product-component--StratigraphicUnitInterpretation`** (SUI - a specific interpretation of that feature)

Each SUI carries `UnitType` = `group`, `formation`, or `member`. The `*ID` fields link directly to SUI records. Age is **chronostratigraphic** and links to `reference-data--ChronoStratigraphy`.

### 4.3 Master-data references

| Field | OSDU Entity | Purpose |
|---|---|---|
| `HostFacilityID` | `master-data--GenericFacility` | Host platform/FPSO |
| `FieldID` | `master-data--Field` | OSDU field record |
| `ReservoirSegmentIDs[]` | `master-data--ReservoirSegment` | Segments with OWC/GOC/seal properties |
| `ParentObjectID` | `master-data--Reservoir` | Parent reservoir |

## 5. Design Decisions

### 5.1 Leaf WPC, not embedded in BD

DevConcept is a standalone WPC, linked FROM the BD via `Parameters[]`.

**Benefits**: Schema-validated, independently versionable, survives OSDU ingestion, discoverable via search, evolves without touching the BD.

### 5.2 Structured sub-objects vs flat keys

Five nested sub-objects rather than flat top-level keys provide: clear domain ownership, natural grouping for UI rendering, easier partial population across gates.

### 5.3 ReservoirSegmentIDs instead of inline faults/contacts

Reference `master-data--ReservoirSegment` IDs. Segment properties (OWC, GOC, fault seal factor) are shared across multiple records - keeping them on master-data avoids duplication.

### 5.4 ConceptID for gate lineage

`ConceptID` links to a prior gate's DevConcept, enabling delta comparison across gates.

## 6. Possible OSDU Improvements

- **Community-standard schema**: No canonical `DevelopmentConcept` WPC exists in OSDU. A proposal for `osdu:wks:work-product-component--DevelopmentConcept:1.0.0` would benefit the community.
- **New reference-data types**: `CompletionType`, `InjectionFluidType`, `SandControlType`, `InflowControlType` would reduce free-text fields.
- **Parameters[] key standardisation**: `Parameters[].Title` key strings are ad-hoc. A standard set would improve interoperability.
- **Alternatives as first-class records**: Rejected alternatives could be full DevConcept WPCs with a status field.

## 7. Schema Evolution

| Version | Changes |
|---|---|
| 1.0.0 | Flat top-level keys |
| 2.0.0 | Restructured into 5 sub-objects, added OSDU ref-data IDs |
| 3.0.0 | Renamed `PriorConceptID` to `ConceptID` (breaking) |
| 4.0.0 | Added `DecisionLevelID`, `AgeID`, `FormationID`, `GroupID`, `ZoneIDs[]` with `x-osdu-relationship` |
