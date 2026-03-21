# OSDU Production Forecasts & BusinessDecision ext.equinor — Comprehensive Research Report

> **Purpose:** Catalogue the canonical OSDU schemas that overlap with elements currently
> stored inside `BusinessDecision.data.ext.equinor`, and recommend which elements to
> migrate to canonical records vs. which to keep as extensions.
>
> **Methodology:** Fetched and analysed the following OSDU Data Definitions sources
> (jonslo/osdu-data-data-definitions fork, aligned with community schemas):
>
> | Source | Version | Status |
> |--------|---------|--------|
> | ProductionValues WPC | 1.0.0 | PUBLISHED (M23) |
> | BusinessDecision | 1.0.0 | PUBLISHED |
> | AbstractProjectActivity | 1.2.0 | PUBLISHED (M18) |
> | Risk | 1.2.0 | PUBLISHED (M18) |
> | ColumnBasedTable worked example | — | Community example |
> | ReservoirManagement worked example | — | Community example |
> | BusinessDecision.1.0.0.json (authoring) | — | Authoring schema |
> | Risk.1.2.0.json (authoring) | — | Authoring schema |
>
> Plus codebase analysis of the local manifest files and enrichment overlay.

---

## Table of Contents

1. [ProductionValues WPC Schema](#1-productionvalues-wpc-schema)
2. [BusinessDecision Schema](#2-businessdecision-schema)
3. [AbstractProjectActivity — Parameters[] Mechanism](#3-abstractprojectactivity--parameters-mechanism)
4. [Risk Schema](#4-risk-schema)
5. [ColumnBasedTable Pattern for Production Forecasts](#5-columnbasedtable-pattern-for-production-forecasts)
6. [ReservoirManagement Worked Examples](#6-reservoirmanagement-worked-examples)
7. [ext.equinor Inventory & Canonical Mapping](#7-extequinor-inventory--canonical-mapping)
8. [Recommendations](#8-recommendations)

---

## 1. ProductionValues WPC Schema

**Kind:** `osdu:wks:work-product-component--ProductionValues:1.0.0`
**Status:** PUBLISHED in M23.0 (superseded by 1.1.0 in M24)
**Purpose:** Stores observed or forecast production metric values for a reporting entity over a nominal period.

### 1.1 Composition / Inheritance

```
ProductionValues.1.0.0
  ├─ AbstractCommonResources.1.0.0   (ResourceLifecycleStatus, Source, …)
  ├─ AbstractWPCGroupType.1.0.0      (Datasets[], Artefacts[])
  ├─ AbstractWorkProductComponent.1.0.0 (LineageAssertions, grouping)
  └─ IndividualProperties             (production-specific fields)
```

### 1.2 Key Individual Properties

| Property | Type | Req? | Description |
|----------|------|------|-------------|
| `ReportingEntityID` | string | **Yes** | The entity being reported on — references Field, Reservoir, Well, Wellbore, WellboreCompletion, Organisation, or Facility. |
| `StartDateTime` | string (date-time) | **Yes** | Start of reporting window. |
| `EndDateTime` | string (date-time) | No | End of reporting window. |
| `NominalPeriodIDs[]` | string[] | **Yes** | References to `reference-data--ReportingPeriod` (e.g., Monthly, Yearly). |
| `PropertyIDs[]` | string[] | **Yes** | References to `reference-data--ProductionPropertyType` (Volume, Mass, Energy, etc.). |
| `ProductIDs[]` | string[] | **Yes** | References to `reference-data--ProductKind` (Oil, Gas, Water, Condensate, NGL, etc.). |
| `QuantityMethodIDs[]` | string[] | No | Method of quantity measurement. |
| `DispositionIDs[]` | string[] | No | Production disposition (sales, flare, own use). |
| `VolumeFlowMeasurementTypeIDs[]` | string[] | No | Flow measurement type for volumes. |
| `DurationContextIDs[]` | string[] | No | Duration context reference. |
| `ReservoirModelScenarioID` | string | No | Link to `ReservoirModelScenario` — relevant for forecast scenarios. |
| `AmendReasonID` | string | No | Amendment reason reference. |
| `ValueContexts[]` | object[] | No | Array of value context objects, includes `DowntimeEventIDs[]`. |
| `MeasurementConditions` | object | No | P-T conditions via `AbstractPTCondition`. |
| `ObservationInterval` | object | No | Observation interval with start/end datetime. |

### 1.3 ProductionValuesObservationDescription (ColumnBasedTable)

The core data table within ProductionValues uses `AbstractColumnBasedTable`:

| Sub-property | Type | Description |
|-------------|------|-------------|
| `KeyColumns[]` | object[] | Key column definitions (e.g., date, entity identifier). |
| `Columns[]` | object[] | Value column definitions with `ColumnName`, `ValueType`, `ValueCount`, `UnitOfMeasureID`, `PropertyType`, `FacetIDs[]`. |
| `ColumnValues[]` | object[] | Actual data arrays — `NumberColumn[]`, `StringColumn[]`, `DateTimeColumn[]`, `IntegerColumn[]`, `BooleanColumn[]`, `UndefinedValueRows[]`. |
| `ColumnSize` | integer | Number of rows. |

### 1.4 Extension Properties

The schema allows open `ExtensionProperties` — an arbitrary JSON object with `additionalProperties: true`. This is the standard extension point, but **not the same** as the registered `ext.equinor` keys on the parent record.

### 1.5 Relevance to ext.equinor.ProductionProfile

The `ProductionProfile` section currently stored in `ext.equinor` on BusinessDecision records (yearly oil/gas/water rates, EUR, peak rate, recovery factor) is **exactly** the kind of data ProductionValues is designed for. However, ProductionValues is oriented toward observed/reported production with time-series rows, not a compact forecast summary embedded in a decision record. A production forecast could be:

1. A **ProductionValues** WPC with `ReportingEntityID` pointing to the Field, `NominalPeriodIDs` = Yearly, and the forecast time series in `ProductionValuesObservationDescription`.
2. A **ColumnBasedTable** WPC (more flexible, no production-specific metadata constraints).
3. An embedded `ext.equinor.ProductionProfile` (current approach — not canonical, dropped by OSDU ingestion).

---

## 2. BusinessDecision Schema

**Kind:** `osdu:wks:master-data--BusinessDecision:1.0.0`
**Status:** PUBLISHED
**Purpose:** Records a technical or business decision, capturing the context, alternatives, risks, and decision quality.

### 2.1 Composition / Inheritance

```
BusinessDecision.1.0.0
  ├─ AbstractMaster.1.2.0            (NameAliases[], GeoContexts[], SpatialLocation, TechnicalAssurances[])
  ├─ AbstractProject.1.0.0           (Purpose, ProjectBeginDate, ProjectEndDate, FundsAuthorizations[],
  │                                    Contractors[], Personnel[], ProjectSpecifications[])
  ├─ AbstractProjectActivity.1.2.0   (Parameters[], ActivityStates[], LastActivityState,
  │                                    ActivityTemplateID, ParentProjectID)
  └─ IndividualProperties            (decision-specific fields)
```

### 2.2 Individual Properties (Decision-Specific)

| Property | Type | Description |
|----------|------|-------------|
| `Name` | string | Project name for discovery. |
| `RiskAssessmentDocument` | string → Document WPC | Link to risk assessment document. |
| `RiskIDs[]` | string[] → Risk | Links to identified Risk records. |
| `ApprovalStatusID` | string → DecisionApprovalStatus | Current approval status. |
| `DecisionLevelID` | string → DecisionLevel | Decision level (DG1, DG2, DG3, DG4). |
| `DecisionDueDate` | string (date) | Planned decision date. |
| `DecisionDate` | string (date) | Actual decision date. |
| `DecisionSummary` | string | Summary of the decision. |
| `Contributors[]` | AbstractContactUserProfile[] | Individuals involved. |
| `DecisionOwners[]` | AbstractContactUserProfile[] | Individuals responsible for action. |
| `DecisionMakers[]` | AbstractContactUserProfile[] | Individuals who decided. |
| `DecisionQualities` | object | 6-component decision quality framework (AppropriateFrame, DoableAlternatives[], InformationReliability, TradeOffAnalysis, ReasoningCorrectness, CommitmentToAction). Each component has an `AssessmentID` → AssessedDecisionQuality, `Triggers[]`, `Remarks[]`. |
| `Remarks[]` | AbstractRemark[] | Free remarks or annotations. |
| `Triggers[]` | AbstractTrigger[] | Events causing re-evaluation. |
| `SelectedAlternativeSequenceNumber` | integer | Index of selected DoableAlternative. |
| `PriorActivityIDs[]` | string[] | Links to preceding activities/projects. |

### 2.3 Inherited from AbstractProject

| Property | Description |
|----------|-------------|
| `Purpose` | Objectives of the project/decision. |
| `ProjectBeginDate` / `ProjectEndDate` | Decision lifecycle dates. |
| `FundsAuthorizations[]` | Expenditure approval history. |
| `Contractors[]` | Service companies involved. |
| `Personnel[]` | Key individuals with `ProjectRole`. |
| `ProjectSpecifications[]` | General parameters with `ParameterTypeID`, `UnitOfMeasureID`, quantities. |

### 2.4 Registered ext.equinor Keys (Survive Ingestion)

Only **7 keys** under `data.ext.equinor` are registered in the OSDU schema and survive workflow ingestion:

| Key | Purpose |
|-----|---------|
| `Alternatives` | Decision alternatives with rank/action |
| `Assurance` | Assurance metadata |
| `CRA` | Cost Risk Assessment |
| `Ensemble` | Ensemble metadata |
| `InterpretationLineage` | Interpretation provenance |
| `SRA` | Schedule Risk Assessment |
| `UncertaintySummary` | P10/P50/P90 volume summary |

All other keys are **silently dropped** during OSDU workflow ingestion (API returns 201, data is lost).

---

## 3. AbstractProjectActivity — Parameters[] Mechanism

**Fragment:** `AbstractProjectActivity.1.2.0`
**Status:** PUBLISHED (M18)
**Purpose:** Provides the activity abstraction for projects and surveys, including the critical `Parameters[]` array for linking input/output/context artifacts.

### 3.1 Parameters[] Structure

Each element in `Parameters[]` uses `AbstractActivityParameter.1.1.0`:

| Property | Type | Req? | Description |
|----------|------|------|-------------|
| `Title` | string | **Yes** | Name of the parameter — must match ActivityTemplate. |
| `Index` | integer | No | Array index when parameter is multi-valued. |
| `Selection` | string | No | How/why this parameter was selected. |
| `ParameterKindID` | string → ParameterKind | **Yes** | Type: DataObject, DataQuantity, Integer, String, Boolean, TimeIndex. |
| `ParameterRoleID` | string → ParameterRole | No | How used: Input, Output, Control, Constraint, Agent, InputReference, etc. |
| `DataObjectParameter` | string (OSDU ID) | No | Reference to any OSDU record (WPC, master-data, etc.). |
| `DataQuantityParameter` | number | No | Numeric value with UOM. |
| `DataQuantityParameterUOMID` | string → UnitOfMeasure | No | UOM for DataQuantityParameter. |
| `IntegerQuantityParameter` | integer | No | Integer value. |
| `StringParameter` | string | No | String value. |
| `TimeIndexParameter` | string (date-time) | No | Time index value. |
| `BooleanParameter` | boolean | No | Boolean value. |
| `Keys[]` | object[] | No | Identifying keys for multi-valued parameters. |

### 3.2 Keys[] Structure (AbstractParameterKey)

| Property | Type | Description |
|----------|------|-------------|
| `ObjectParameterKey` | string (OSDU ID) | Object reference as key. |
| `TimeIndexParameterKey` | string (time) | Time index as key. |
| `ParameterKey` | string | Internal named key for association. |
| `IntegerParameterKey` | integer | Integer key value. |
| `StringParameterKey` | string | String key value. |

### 3.3 ActivityStates[] and LastActivityState

Track the lifecycle of the decision activity with `EffectiveDateTime`, `TerminationDateTime`, `ActivityStatusID` → ActivityStatus, and `Remark`. `LastActivityState` is a denormalized copy of the most recent state for efficient querying.

### 3.4 Usage Pattern for Linking Artifacts to Decisions

The Drogon DG2 manifest demonstrates the recommended pattern:

```json
"Parameters": [
  {
    "Title": "Raw volumes (per realisation)",
    "ParameterKindID": "dev:reference-data--ParameterKind:DataObject:1",
    "ParameterRoleID": "dev:reference-data--ParameterRole:Input:1",
    "DataObjectParameter": "dev:work-product-component--ReservoirEstimatedVolumes:...:1",
    "Keys": [{ "ParameterKey": "artifact", "StringParameterKey": "REV-raw" }]
  },
  {
    "Title": "Valysar parameters (OWC, porosity)",
    "ParameterRoleID": "dev:reference-data--ParameterRole:Input:1",
    "DataObjectParameter": "dev:work-product-component--ColumnBasedTable:...:1"
  },
  {
    "Title": "Reservoir scope",
    "ParameterRoleID": "dev:reference-data--ParameterRole:InputReference:1",
    "DataObjectParameter": "dev:master-data--Reservoir:...:1"
  }
]
```

This links WPCs (ReservoirEstimatedVolumes, ColumnBasedTable, Documents) and master-data (Reservoir) to the decision with explicit roles.

---

## 4. Risk Schema

**Kind:** `osdu:wks:master-data--Risk:1.2.0`
**Status:** PUBLISHED (M18)
**Purpose:** Records exposure to loss, injury, or adverse circumstances — used in drilling programs, field development, and business decisions.

### 4.1 Composition

```
Risk.1.2.0
  ├─ AbstractMaster.1.2.0    (NameAliases[], GeoContexts[], SpatialLocation, TechnicalAssurances[])
  └─ IndividualProperties     (risk-specific fields)
```

Note: Risk does **not** inherit AbstractProject or AbstractProjectActivity. It is a standalone master-data entity linked _from_ BusinessDecision via `RiskIDs[]`.

### 4.2 Key Individual Properties

| Property | Type | Req? | Description |
|----------|------|------|-------------|
| `Name` | string | No | Common name for the risk. |
| `Description` | string | No | Full description. |
| `Summary` | string | No | Short description. |
| `Cause` | string | No | Root cause description. |
| `Consequence` | string | No | Consequence description. |
| `ConsequenceCategoryID` | string → RiskConsequenceCategory | No | Loss category (Asset, Environment, Personnel, Revenue, etc.). |
| `ConsequenceSubCategoryID` | string → RiskConsequenceSubCategory | No | Sub-category. |
| `RiskCategoryID` | string → RiskCategory | No | General category (Reservoir, Drilling, Completion, Opportunity). |
| `RiskSubCategoryID` | string → RiskSubCategory | No | Detailed category (BOP, Casing, Cementing, etc.). |
| `RiskDisciplineID` | string → RiskDiscipline | No | Discipline affected. |
| `RiskHierarchyLevelID` | string → RiskHierarchyLevel | No | Hierarchy level (Well, Field, Global). |
| `TypeID` | string → RiskType | No | Risk type (WITSML-aligned). |
| **Severity / Probability / Score** | | | |
| `InitialSeverity` | number | No | Pre-mitigation severity (1–5). |
| `InitialProbability` | number | No | Pre-mitigation probability (1–5). |
| `InitialRiskScore` | number | No | = InitialSeverity × InitialProbability (1–25). |
| `ResidualSeverity` | number | No | Post-mitigation severity. |
| `ResidualProbability` | number | No | Post-mitigation probability. |
| `ResidualRiskScore` | number | No | Post-mitigation score. |
| `NetSeverity` / `NetProbability` / `NetRiskScore` | number | No | With prevention + mitigation barriers. |
| **Responses** | | | |
| `Preventions[]` | object[] | No | Steps to prevent the risk. Each has `Name` (req), `Description` (req), `Status` (req → RiskResponseStatus), `Responsibles[]` (req → AbstractContact), `Deadline`, `UpdateDate`. |
| `Mitigations[]` | object[] | No | Steps to mitigate consequences. Same structure as Preventions. |
| `RiskResponsibles[]` | AbstractContact[] | No | People/roles managing the risk. |
| **Other** | | | |
| `RiskAssociatedObjectIDs[]` | string[] | No | Links to related objects (BHA, mud design, activity plans). |
| `AffectedPersonnel` | string → Organisation | No | Affected entity. |
| `WellboreID` | string → Wellbore | **Yes** (required) | Planned wellbore (schema requires it, though for non-well contexts this is problematic). |
| `RiskStartDepth` / `RiskEndDepth` | number (length) | No | Depth interval for the risk. |
| `RelatedRiskSetID` | string → PersistedCollection | No | Collection of related risks. |
| `EffectiveDateTime` / `TerminationDateTime` | string | No | Activity dates. |
| `ExtendedRiskCategory` | string | No | Custom extension string for categorization. |
| `PublicationDate` | string (date-time) | No | External publication date. |

### 4.3 Risk ↔ BusinessDecision Relationship

- `BusinessDecision.RiskIDs[]` → `Risk` (many-to-many via array)
- `BusinessDecision.RiskAssessmentDocument` → `Document` WPC
- Both link to common GeoContexts (Field, Basin, Prospect) via AbstractMaster

### 4.4 Relevance to ext.equinor

The `KeyUncertainties` section in `ext.equinor` overlaps significantly with the Risk schema:

| ext.equinor.KeyUncertainties field | Risk canonical equivalent |
|------------------------------------|----|
| `Factor` (name) | `Risk.Name` |
| `Description` | `Risk.Description` |
| `Impact` (High/Medium/Low) | `InitialSeverity` (1–5 scale) |
| (no mitigation field) | `Mitigations[]`, `Preventions[]` |

However, `KeyUncertainties` as used in the DG2 manifest represents **subsurface uncertainties** (porosity, fault transmissibility, OWC depth) rather than classical project risks. These could be modelled as Risk records with `RiskCategoryID` = Reservoir/Subsurface, or kept as structured notes.

---

## 5. ColumnBasedTable Pattern for Production Forecasts

**Kind:** `osdu:wks:work-product-component--ColumnBasedTable:1.0.0`
**Purpose:** Generic tabular data container using the `AbstractColumnBasedTable` fragment.

### 5.1 Core Structure

```json
{
  "data": {
    "Table": {
      "ColumnSize": <number_of_rows>,
      "KeyColumns": [
        {
          "ColumnName": "Year",
          "ValueType": "integer",
          "ValueCount": 1
        }
      ],
      "Columns": [
        {
          "ColumnName": "OilRate_kSm3d",
          "ValueType": "number",
          "ValueCount": 1,
          "UnitOfMeasureID": "namespace:reference-data--UnitOfMeasure:kSm3.d-1:",
          "UnitQuantityID": "namespace:reference-data--UnitQuantity:volume per time:",
          "PropertyType": {
            "PropertyTypeID": "namespace:reference-data--PropertyType:<uuid>:",
            "Name": "oil production rate"
          },
          "FacetIDs": [
            {
              "FacetTypeID": "namespace:reference-data--FacetType:product:",
              "FacetRoleID": "namespace:reference-data--FacetRole:oil:"
            },
            {
              "FacetTypeID": "namespace:reference-data--FacetType:condition:",
              "FacetRoleID": "namespace:reference-data--FacetRole:forecast:"
            }
          ]
        }
      ],
      "ColumnValues": [
        {
          "IntegerColumn": [2028, 2029, 2030, ...]
        },
        {
          "NumberColumn": [1.7, 4.0, 5.2, ...],
          "UndefinedValueRows": []
        }
      ]
    }
  }
}
```

### 5.2 Advantages for Production Forecast Data

| Feature | Benefit for forecasts |
|---------|----------------------|
| `ColumnName` | Identifies each time series (OilRate, GasRate, WaterRate, CumOil, etc.) |
| `UnitOfMeasureID` | Explicit UOM per column — no ambiguity |
| `PropertyType` | Links to reference-data PropertyType for semantic meaning |
| `FacetIDs[]` | Multi-dimensional classification: product type, statistics, condition, phase |
| `ValueCount` | Supports multi-valued cells (e.g., P10/P50/P90 per row with `ValueCount: 3`) |
| `ColumnSize` | Row count for validation |
| `UndefinedValueRows[]` | Explicit absent-value handling |

### 5.3 Worked Examples from OSDU Community

The ColumnBasedTable worked example demonstrates:

1. **Facies lookup** — integer key + string value column
2. **Saturation function** — water-oil saturation table with UOM, PropertyType, `FacetIDs` for fluid type
3. **Pressure profiles** — depth-indexed 2D arrays with `ValueCount: 5` (multiple values per cell)
4. **ColumnBasedTableTemplate** — governance pattern: define reusable column definitions centrally, reference them via `ColumnName` from data tables

### 5.4 Mapping ext.equinor.ProductionProfile → ColumnBasedTable

The current `ProductionProfile` in `ext.equinor`:

```json
{
  "Years": [2028, 2029, ...],
  "OilRate_kSm3d": [1.7, 4.0, ...],
  "GasRate_kSm3d": [142, 340, ...],
  "WaterRate_kSm3d": [0.3, 1.0, ...],
  "YearlyOil_MSm3": [0.3, 1.46, ...],
  "CumOil_MSm3": [0.3, 1.76, ...],
  "WaterCut_pct": [12.5, 16.7, ...],
  "RecoveryFactor_pct": [0.7, 3.9, ...],
  "WellsOnline": [3, 8, ...],
  "PeakOilRate_kSm3d": 5.2,
  "EUR_MSm3": 14.8,
  "STOIIP_P50_MSm3": 45.4
}
```

Maps naturally to a ColumnBasedTable:

| KeyColumn | Columns (9 value columns) | Scalar metadata → Parameters[] or Remarks |
|-----------|----|----|
| `Year` (integer) | `OilRate_kSm3d`, `GasRate_kSm3d`, `WaterRate_kSm3d`, `YearlyOil_MSm3`, `CumOil_MSm3`, `WaterCut_pct`, `RecoveryFactor_pct`, `WellsOnline` | `PeakOilRate_kSm3d`, `EUR_MSm3`, `STOIIP_P50_MSm3` → BD `Parameters[]` as DataQuantityParameter with UOM |

---

## 6. ReservoirManagement Worked Examples

The ReservoirManagement worked example covers:

### 6.1 Entity Relationships

- `Reservoir` / `ReservoirSegment` → linked from `WellboreOpening`
- `ReservoirEstimatedVolumes` → links to Reservoir/ReservoirSegment, uses ColumnBasedTable for volume tables
- `ReservoirModelScenario` → scenario-based model hypotheses
- `ReservoirSegment` → can reference earth model compartments via `CompartmentInterpretationID`

### 6.2 ReservoirEstimatedVolumes Pattern

Key demonstration of how to use ColumnBasedTable for estimated volumes:

1. **Key column** — references to `ReservoirEstimatedVolumePropertyType` (TotalGas, Oil)
2. **Value columns** — P10/P50/P90 with explicit `FacetIDs` for statistics and condition (surface/reservoir)
3. **Homogeneous UOM** — each column has a single UOM (bscf or mmsbbl), replicated as needed
4. **UndefinedValueRows** — explicit absent values (e.g., Oil row absent in bscf column)

This pattern directly applies to the `VolumesSummary_STOIIP_MSm3` data currently in `ext.equinor`.

### 6.3 ReservoirProperties Pattern

Reservoir/ReservoirSegment records carry via `AbstractGenericReservoirUnit`:
- Life cycle statuses with effective/termination dates
- Size indicators (area)
- Pressure datum depth
- Vertical measurement references
- Segmentation flag

The `ext.equinor.ReservoirProperties` section data (porosity, permeability, temperature, pressure, OWC) could partially be modelled through:
- `Reservoir` / `ReservoirSegment` master-data records (for static properties)
- `ProjectSpecifications[]` on the BD itself (via AbstractProject) with `ParameterTypeID` for each property
- A dedicated `ColumnBasedTable` WPC with one row per segment

---

## 7. ext.equinor Inventory & Canonical Mapping

### 7.1 Complete Inventory of ext.equinor Keys (from Drogon DG2 Manifest)

| # | ext.equinor Key | Content Summary | Size | Survives Ingestion? |
|---|----------------|-----------------|------|---------------------|
| 1 | `Authors` | Array of {Name, Role, Organisation} | 6 entries | **No** (dropped) |
| 2 | `ReviewTeam` | {PreparedBy, Responsible, QARecommender, ProcessControlledBy, ApprovedBy} | 5 slots | **No** (dropped) |
| 3 | `Alternatives` | Array of {Name, Rank, Rationale, RecommendedAction, NPV, CAPEX, IRR} | 3 entries | **Yes** (registered) |
| 4 | `DevelopmentConcept` | {Summary, WellCount, Templates, Host, WaterDepth, FlowlineSpec, WellPlan{…}} | ~20 fields | **No** (dropped) |
| 5 | `ReservoirProperties` | {FormationName, Segments[], Porosity, NTG, OWC, Temp, Pressure, Perm, …} | ~18 fields | **No** (dropped) |
| 6 | `VolumesSummary_STOIIP_MSm3` | P90/P50/P10 per segment + Total | 8 sub-objects | **No** (dropped) |
| 7 | `KeyUncertainties` | Array of {Factor, Impact, Description} | 5 entries | **No** (dropped) |
| 8 | `UncertaintySummary` | {Basis, TotalRealisations, SelectedRealisations, StaticInPlace, Recoverable, RF} | ~8 fields | **Yes** (registered) |
| 9 | `KeyEconomics` | {NPV, IRR, CAPEX, OPEX, Breakeven, Payback, Currency, Note} | ~9 fields | **No** (dropped) |
| 10 | `ScheduleMilestones` | Array of {Milestone, Date, Status} | 7 entries | **No** (dropped) |
| 11 | `ProductionProfile` | {Years[], OilRate[], GasRate[], WaterRate[], YearlyOil[], CumOil[], WaterCut[], RF%, WellsOnline[], PeakOil, EUR, STOIIP} | 20 years × 8 cols | **No** (dropped) |
| 12 | `Recommendations` | Array of recommendation strings | 7 entries | **No** (dropped) |

### 7.2 Canonical Mapping Assessment

| ext.equinor Section | Canonical OSDU Schema(s) | Mapping Quality | Notes |
|---------------------|-------------------------|-----------------|-------|
| **Authors** | `BD.Personnel[]` (from AbstractProject) with `ProjectRole` | **Strong** | Map Author.Role → ProjectRole reference, Author.Organisation → Organisation master-data. |
| **ReviewTeam** | `BD.DecisionOwners[]`, `BD.DecisionMakers[]`, `BD.Contributors[]` (AbstractContactUserProfile) | **Strong** | PreparedBy/QARecommender → Contributors, ApprovedBy → DecisionMakers, Responsible → DecisionOwners. |
| **Alternatives** | `BD.DecisionQualities.DoableAlternatives[]` | **Strong** | Already registered. Each alternative has `SequenceNumber`, linked `Triggers[]`, and `AssessmentID`. NPV/CAPEX/IRR → custom keys or `ProjectSpecifications[]`. |
| **DevelopmentConcept** | No single canonical schema. Split across: `BD.ProjectSpecifications[]` (quantities), `BD.Description`/`Purpose` (narrative), linked WPCs | **Partial** | WellCount, WaterDepth, etc. → `ProjectSpecifications[]` with typed ParameterType + UOM. Complex sub-objects (WellPlan) need a separate WPC or structured Remarks. |
| **ReservoirProperties** | `master-data--Reservoir` + `ReservoirSegment` records | **Strong** | Porosity, permeability, temperature, pressure, OWC are properties of the Reservoir/Segment, not the BD. Link via `Parameters[]` with `ParameterRoleID: InputReference`. |
| **VolumesSummary** | `work-product-component--ReservoirEstimatedVolumes` | **Strong** | Per-segment P10/P50/P90 volumes are exactly what REV WPC is for. Already implemented as linked WPCs in Parameters[]. |
| **KeyUncertainties** | `master-data--Risk` (Reservoir category) | **Moderate** | Uncertainties can be modelled as Risk records with `RiskCategoryID: Reservoir`, but lacks "Impact: High/Medium/Low" as simple text — need to map to severity scale. |
| **UncertaintySummary** | Already registered. Alternatively: REV WPC metadata or `BD.Remarks[]` | **Strong** | Survives ingestion. Contains methodology and P10/P50/P90 summaries. |
| **KeyEconomics** | `BD.ProjectSpecifications[]` or `BD.FundsAuthorizations[]` (partial) | **Moderate** | NPV, IRR, CAPEX → `ProjectSpecifications[]` with `ParameterTypeID` and `UnitOfMeasureID`. No dedicated economics schema in OSDU. Breakeven/Payback less standard. |
| **ScheduleMilestones** | `BD.ActivityStates[]` (from AbstractProjectActivity) | **Moderate** | Each milestone → an ActivityState with `EffectiveDateTime`, `ActivityStatusID`, `Remark`. Incomplete: no "planned date" field — only effective/termination. |
| **ProductionProfile** | `work-product-component--ColumnBasedTable` or `--ProductionValues` | **Strong** | Create a separate ColumnBasedTable WPC with yearly forecast data. Link from BD via `Parameters[]`. Scalar summaries (PeakOil, EUR) → `Parameters[]` as `DataQuantityParameter`. |
| **Recommendations** | `BD.Remarks[]` (AbstractRemark) | **Moderate** | Each recommendation → a Remark item with `Remark` text and `RemarkSource`. Alternatively, `BD.DecisionSummary` for a combined narrative. |

---

## 8. Recommendations

### 8.1 Elements to Migrate to Canonical Records (High Confidence)

These elements have strong canonical counterparts and should be stored as proper OSDU records or in canonical BD fields:

| Element | Target | Action |
|---------|--------|--------|
| **Authors** | `BD.Personnel[]` with ProjectRole references | Map each author to Personnel entry. Create ProjectRole reference-data for "Geoscience Lead", "Reservoir Engineer", etc. |
| **ReviewTeam** | `BD.DecisionOwners[]` / `DecisionMakers[]` / `Contributors[]` | Map governance roles to OSDU contact structures. |
| **ReservoirProperties** | Separate `Reservoir` + `ReservoirSegment` records | Already linked via `Parameters[].DataObjectParameter`. Ensure properties (porosity, perm, pressure) are on the Reservoir/Segment records, not the BD. |
| **VolumesSummary** | `ReservoirEstimatedVolumes` WPC | Already implemented. Stat REV WPC carries per-segment P10/P50/P90. |
| **ProductionProfile** | New `ColumnBasedTable` WPC | Create a ColumnBasedTable with Year as KeyColumn, 8 value columns for rates/cumulative/RF. Link from BD via `Parameters[]` with `ParameterRoleID: Input`. |
| **KeyUncertainties** | `Risk` records with `RiskCategoryID: Reservoir` | Create one Risk per uncertainty, link via `BD.RiskIDs[]`. Map Impact → `InitialSeverity`. |

### 8.2 Elements to Keep as Extensions or Structured Notes (Moderate Confidence)

These elements lack clean canonical counterparts and benefit from extension or alternative approaches:

| Element | Recommended Approach | Rationale |
|---------|---------------------|-----------|
| **DevelopmentConcept** | Split: summary text → `BD.Purpose` or `BD.Description`; numeric quantities → `BD.ProjectSpecifications[]`; complex sub-structures (WellPlan) → `Document` WPC or `ColumnBasedTable` | No single OSDU schema for development concepts. ProjectSpecifications can hold typed quantities but is flat. |
| **KeyEconomics** | `BD.ProjectSpecifications[]` for NPV/IRR/CAPEX with typed ParameterType + UOM. Alternatively, a dedicated `ColumnBasedTable` WPC if economics are complex. | OSDU has no economics-specific schema. ProjectSpecifications is the closest canonical fit. |
| **ScheduleMilestones** | `BD.ActivityStates[]` for completed milestones; planned milestones → `BD.Triggers[]` or `BD.Remarks[]` with structured naming. | ActivityStates captures state transitions but lacks a "planned date" concept — only effective/termination. |
| **Recommendations** | `BD.Remarks[]` or `BD.DecisionSummary` | Pure narrative content; Remarks is the natural home. |
| **Alternatives (economic data)** | Keep `Alternatives` as registered ext.equinor (survives ingestion). NPV/CAPEX/IRR per alternative → `DoableAlternatives[].Triggers[]` metadata or `ProjectSpecifications[]` with keyed indices. | The registered Alternatives key works. Economic fields per alternative have no canonical home — DoableAlternatives only has SequenceNumber + Triggers + AssessmentID. |

### 8.3 Schema Extension Registration Request

For elements that don't fit canonical schemas well, request registration of additional ext.equinor keys:

| Priority | Key | Justification |
|----------|-----|---------------|
| High | `DevelopmentConcept` | Complex structured object with no canonical equivalent; widely used across DG1–DG4. |
| High | `KeyEconomics` | Decision economics are critical metadata; OSDU lacks an economics schema. |
| Medium | `ScheduleMilestones` | Planned milestones don't fit ActivityStates cleanly. |
| Medium | `ProductionProfile` | While a ColumnBasedTable WPC is better, a summary version is useful for quick rendering. |
| Low | `Authors` / `ReviewTeam` | Strong canonical mapping exists via Personnel/Contributors/DecisionOwners. |
| Low | `Recommendations` | Fits in Remarks[]. |

### 8.4 Hybrid Architecture (Recommended)

```
BusinessDecision record
  ├── Canonical fields
  │   ├── Personnel[] ← Authors
  │   ├── DecisionOwners/Makers/Contributors[] ← ReviewTeam
  │   ├── RiskIDs[] ← KeyUncertainties (as Risk records)
  │   ├── ProjectSpecifications[] ← KeyEconomics (NPV, CAPEX, IRR)
  │   ├── ActivityStates[] ← ScheduleMilestones (completed)
  │   ├── Remarks[] ← Recommendations
  │   └── DecisionQualities.DoableAlternatives[] ← Alternatives (narrative)
  │
  ├── Linked WPCs (via Parameters[])
  │   ├── ReservoirEstimatedVolumes ← VolumesSummary (already done)
  │   ├── ColumnBasedTable (new) ← ProductionProfile (forecast time series)
  │   └── Document ← RiskAssessmentDocument (already done)
  │
  ├── Linked master-data (via Parameters[])
  │   ├── Reservoir + ReservoirSegments ← ReservoirProperties (already done)
  │   └── Risk records ← KeyUncertainties (new)
  │
  └── Registered ext.equinor (survive ingestion)
      ├── Alternatives (registered — keep for economic summary per alt)
      ├── UncertaintySummary (registered — keep)
      ├── DevelopmentConcept (request registration — no canonical fit)
      └── KeyEconomics (request registration or use ProjectSpecifications[])
```

### 8.5 Implementation Priority

| Priority | Task | Effort |
|----------|------|--------|
| 1 | Create `ColumnBasedTable` WPC for ProductionProfile, link via Parameters[] | Medium |
| 2 | Map Authors → Personnel[], ReviewTeam → DecisionOwners/Contributors | Low |
| 3 | Map KeyEconomics → ProjectSpecifications[] with typed ParameterType reference-data | Medium |
| 4 | Create Risk records for KeyUncertainties, link via RiskIDs[] | Medium |
| 5 | Map Recommendations → Remarks[] | Low |
| 6 | Map ScheduleMilestones → ActivityStates[] (completed) + Remarks[] (planned) | Medium |
| 7 | Request schema extension registration for DevelopmentConcept, KeyEconomics | External dependency |

---

*Report generated from OSDU Data Definitions analysis. All schema references are from the
published OSDU community schemas as of M23/M24.*
