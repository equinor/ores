# Activity & ActivityTemplate - Data Model & Implementation Guide

> **Scope:** Detailed guide for OSDU `Activity` and `ActivityTemplate` records - how to capture workflow provenance, link inputs/outputs, and connect activities to `BusinessDecision` gates. Covers reservoir simulation, seismic interpretation, QC, and FMU workflows.
>
> **Related guides**: [BusinessDecision](/howto/business-decision) · [BD Demo](/howto/bd-demo) · [Uncertainty](/howto/uncertainty) · [SeisInt](/howto/seismic-interp) · [Volumes](/howto/volumes) · [Risk](/howto/risk)
>
> **Web UI**: The ORES [Create Record → Activity](/add-dg) tab lets you create both ActivityTemplates and Activity records interactively - including preset scaffolds for common workflow types.

---

## 1. Purpose & Concept

**Activities** are the OSDU mechanism for recording **provenance** - capturing *who ran what workflow, with which inputs, and what was produced*. They answer the question: "How did this data come to exist?"

Two complementary record types work together:

| Record | Kind | Role |
|--------|------|------|
| **ActivityTemplate** | `osdu:wks:work-product-component--ActivityTemplate:1.0.0` | Reusable **blueprint** - defines the parameter slots (inputs/outputs) that any execution of this workflow type should provide |
| **Activity** | `osdu:wks:work-product-component--Activity:1.0.0` | Concrete **execution record** - fills the template slots with actual values from a specific run |

Think of it like a function signature (template) vs a function call (activity):
- Template: `run_simulation(process: str, num_realisations: int, input_params: DataObject) → volumes: DataObject`
- Activity: `run_simulation("RMS DecisionExample", 3, dev:...ColumnBasedTable:...) → dev:...REV:...`

---

## 2. OSDU Schema Overview

### ActivityTemplate Schema

```json
{
  "kind": "osdu:wks:work-product-component--ActivityTemplate:1.0.0",
  "data": {
    "Name": "Reservoir Simulation Workflow",
    "Description": "Template for multi-realisation reservoir simulation",
    "Originator": "user@company.com",
    "ParameterTemplates": [
      {
        "Title": "InputParameters",
        "Description": "Input parameter table",
        "IsInput": true,
        "IsOutput": false,
        "MinOccurs": 1,
        "MaxOccurs": 1,
        "DefaultParameterKind": "DataObject"
      }
    ]
  }
}
```

### Activity Schema

```json
{
  "kind": "osdu:wks:work-product-component--Activity:1.0.0",
  "data": {
    "Name": "Drogon Simulation Run - 2025-Q1",
    "Description": "Executed 3 realisations...",
    "ActivityTemplateID": "dev:work-product-component--ActivityTemplate:...:1",
    "WorkflowStatus": "Completed",
    "CreationDateTime": "2025-03-15T14:30:00Z",
    "ParentObjectID": "dev:master-data--Reservoir:...:1",
    "Parameters": [ ... ]
  }
}
```

### Key Fields

| Field | On | Description |
|-------|----|-------------|
| `Name` | Both | Human-readable workflow / run name |
| `Description` | Both | Detailed description of what the workflow does / what was executed |
| `Originator` | Both | Email or name of the author |
| `ParameterTemplates[]` | Template | Array of parameter slot definitions |
| `ActivityTemplateID` | Activity | Reference to the template this activity implements |
| `WorkflowStatus` | Activity | `Completed`, `InProgress`, `Planned`, `Failed` |
| `CreationDateTime` | Activity | ISO 8601 timestamp of execution |
| `ParentObjectID` | Activity | Parent master-data record (e.g. Reservoir) |
| `ParentWorkProductID` | Activity | Parent WorkProduct record |
| `Parameters[]` | Activity | Array of filled parameter values |

---

## 3. Template vs Activity

```mermaid
graph LR
    subgraph "Reusable Blueprint"
        TPL["ActivityTemplate<br/><i>defines parameter slots</i>"]
    end
    subgraph "Concrete Execution"
        ACT1["Activity - Run 1<br/><i>fills slots with values</i>"]
        ACT2["Activity - Run 2<br/><i>fills slots with values</i>"]
        ACT3["Activity - Run 3<br/><i>fills slots with values</i>"]
    end
    TPL --> ACT1
    TPL --> ACT2
    TPL --> ACT3

    classDef tpl fill:#fff0f3,stroke:#ff1243,color:#333
    classDef act fill:#e8f5f5,stroke:#007079,color:#333
    class TPL tpl
    class ACT1,ACT2,ACT3 act
```

**One template, many activities.** A single "Reservoir Simulation" template can be referenced by every simulation run across multiple fields, gates, and time periods. The template ensures consistency in how workflows are documented.

### When to create a new template

| Scenario | Action |
|----------|--------|
| Same workflow type, different run | Reuse existing template, create new Activity |
| Same workflow type, different field | Reuse template (field context comes from `ParentObjectID`) |
| Fundamentally different workflow | Create new template |
| Added an extra output to the workflow | Create a new template version (or update slots) |

---

## 4. Parameter Model

### Template Parameter Slots (`ParameterTemplates[]`)

Each slot defines what the activity should provide:

| Field | Type | Description |
|-------|------|-------------|
| `Title` | string | Slot name - Activities must match this exactly |
| `Description` | string | What this parameter represents |
| `IsInput` | boolean | Is this an input to the workflow? |
| `IsOutput` | boolean | Is this an output from the workflow? |
| `MinOccurs` | integer | 0 = optional, 1 = required |
| `MaxOccurs` | integer | Maximum number of values (typically 1) |
| `DefaultParameterKind` | string | Expected value type: `string`, `integer`, `DataObject` |

### Activity Parameter Values (`Parameters[]`)

Each filled parameter carries the actual value:

| Field | Type | Description |
|-------|------|-------------|
| `Title` | string | Must match a template slot title |
| `Description` | string | Contextual description of this specific value |
| `ParameterKindID` | string | Ref-data link: `ParameterKind:String`, `:Integer`, or `:DataObject` |
| `ParameterRoleID` | string | Ref-data link: `ParameterRole:Input`, `:Output`, or `:InputReference` |
| `StringParameter` | string | Value when kind = String |
| `IntegerParameter` | integer | Value when kind = Integer |
| `DataObjectParameter` | string | OSDU record ID when kind = DataObject |
| `Keys[]` | array | Optional key-value pairs for tagging (artifact type, realisation index, etc.) |

### Parameter Roles

| Role | `ParameterRoleID` suffix | Use for |
|------|--------------------------|---------|
| **Input** | `:Input:` | Data consumed by the workflow (parameter tables, models, config) |
| **Output** | `:Output:` | Data produced by the workflow (volumes, surfaces, reports) |
| **InputReference** | `:InputReference:` | Context records not directly consumed but relevant (dataspaces, reservoirs) |

---

## 5. Worked Example: Reservoir Simulation (Drogon)

The Drogon demo pipeline (`demo/drogon/gen_activity_drogon.py`) generates a complete Activity + Template pair for a multi-realisation volumetrics workflow.

### 5.1 Workflow Overview

The Drogon DG1 volumetrics workflow has three steps, captured as a single merged activity:

1. **Generate input parameters** - OWC depths + PHIT per realisation for 7 fault blocks
2. **Run RMS model** - DecisionExample workflow producing 3 realisations of volumes
3. **Aggregate statistics** - P10/P50/P90 from per-realisation results

### 5.2 Template Definition

```json
{
  "kind": "osdu:wks:work-product-component--ActivityTemplate:1.0.0",
  "data": {
    "Name": "Drogon Valysar - Volumetrics Workflow Template",
    "Description": "Covers three sequential steps: (1) generate per-realisation input parameters, (2) run RMS reservoir model, (3) aggregate into P10/P50/P90 statistics.",
    "ParameterTemplates": [
      {
        "Title": "InputParameters",
        "Description": "Input parameter table (ColumnBasedTable WPC) containing per-realisation OWC depth and PHIT values",
        "IsInput": true, "IsOutput": false,
        "MinOccurs": 0, "MaxOccurs": 1,
        "DefaultParameterKind": "DataObject"
      },
      {
        "Title": "Process",
        "Description": "Name of the RMS reservoir model / workflow",
        "IsInput": true, "IsOutput": false,
        "MinOccurs": 1, "MaxOccurs": 1,
        "DefaultParameterKind": "string"
      },
      {
        "Title": "NumberOfRealizations",
        "Description": "Total realisations executed",
        "IsInput": true, "IsOutput": false,
        "MinOccurs": 1, "MaxOccurs": 1,
        "DefaultParameterKind": "integer"
      },
      {
        "Title": "Method",
        "Description": "Uncertainty sampling method (User_Defined, Monte_Carlo)",
        "IsInput": true, "IsOutput": false,
        "MinOccurs": 0, "MaxOccurs": 1,
        "DefaultParameterKind": "string"
      },
      {
        "Title": "Variables",
        "Description": "Serialised JSON list of uncertainty variable definitions (Low/Base/High ranges)",
        "IsInput": true, "IsOutput": false,
        "MinOccurs": 0, "MaxOccurs": 1,
        "DefaultParameterKind": "string"
      },
      {
        "Title": "DesignMatrix",
        "Description": "Serialised JSON design matrix assigning scenarios per realisation",
        "IsInput": true, "IsOutput": false,
        "MinOccurs": 0, "MaxOccurs": 1,
        "DefaultParameterKind": "string"
      },
      {
        "Title": "OutputParameters",
        "Description": "Generated per-realisation input parameter table (ColumnBasedTable WPC)",
        "IsInput": false, "IsOutput": true,
        "MinOccurs": 0, "MaxOccurs": 1,
        "DefaultParameterKind": "DataObject"
      },
      {
        "Title": "OutputVolumes",
        "Description": "Per-realisation reservoir estimated volumes (RAW REV WPC)",
        "IsInput": false, "IsOutput": true,
        "MinOccurs": 1, "MaxOccurs": 1,
        "DefaultParameterKind": "DataObject"
      },
      {
        "Title": "ReportTable",
        "Description": "Statistical aggregation (STAT REV WPC: P10/P50/P90)",
        "IsInput": false, "IsOutput": true,
        "MinOccurs": 1, "MaxOccurs": 1,
        "DefaultParameterKind": "DataObject"
      }
    ]
  }
}
```

### 5.3 Activity Record

```json
{
  "kind": "osdu:wks:work-product-component--Activity:1.0.0",
  "data": {
    "Name": "Drogon Valysar - DG1 Volumetrics Workflow Run",
    "Description": "Full three-step DG1 volumetrics workflow for Valysar formation...",
    "ActivityTemplateID": "dev:work-product-component--ActivityTemplate:aa2791c8-...:1",
    "WorkflowStatus": "Completed",
    "CreationDateTime": "2026-02-13T10:21:57.365Z",
    "ParentObjectID": "dev:master-data--Reservoir:Drogon:1",
    "Parameters": [
      {
        "Title": "InputParameters",
        "ParameterKindID": "dev:reference-data--ParameterKind:DataObject:",
        "ParameterRoleID": "dev:reference-data--ParameterRole:Input:",
        "DataObjectParameter": "dev:work-product-component--ColumnBasedTable:drogon-params:1",
        "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ColumnBasedTable-params"}]
      },
      {
        "Title": "Process",
        "ParameterKindID": "dev:reference-data--ParameterKind:String:",
        "ParameterRoleID": "dev:reference-data--ParameterRole:Input:",
        "StringParameter": "RMS DecisionExample - Drogon Valysar"
      },
      {
        "Title": "NumberOfRealizations",
        "ParameterKindID": "dev:reference-data--ParameterKind:Integer:",
        "ParameterRoleID": "dev:reference-data--ParameterRole:Input:",
        "IntegerParameter": 3
      },
      {
        "Title": "OutputVolumes",
        "ParameterKindID": "dev:reference-data--ParameterKind:DataObject:",
        "ParameterRoleID": "dev:reference-data--ParameterRole:Output:",
        "DataObjectParameter": "dev:work-product-component--ReservoirEstimatedVolumes:drogon-raw:1"
      },
      {
        "Title": "ReportTable",
        "ParameterKindID": "dev:reference-data--ParameterKind:DataObject:",
        "ParameterRoleID": "dev:reference-data--ParameterRole:Output:",
        "DataObjectParameter": "dev:work-product-component--ReservoirEstimatedVolumes:drogon-stats:1"
      },
      {
        "Title": "GeoModelDataspace",
        "ParameterKindID": "dev:reference-data--ParameterKind:DataObject:",
        "ParameterRoleID": "dev:reference-data--ParameterRole:InputReference:",
        "DataObjectParameter": "dev:dataset--ETPDataspace:maap-drogon_dg:1"
      }
    ]
  }
}
```

### 5.4 Data Flow

```mermaid
flowchart TD
    subgraph Inputs
        DM["Design Matrix<br/><i>OWC + PHIT variables</i>"]
        PARAMS["ColumnBasedTable<br/><i>Per-realisation parameters</i>"]
        RMS["RMS Model<br/><i>DecisionExample workflow</i>"]
    end

    subgraph Activity["Activity: Drogon Volumetrics Run"]
        STEP1["Step 1: Generate Parameters"]
        STEP2["Step 2: Run RMS Model<br/><i>3 realisations</i>"]
        STEP3["Step 3: Aggregate Statistics"]
    end

    subgraph Outputs
        RAW["REV - Raw<br/><i>Per-realisation volumes</i>"]
        STAT["REV - Statistics<br/><i>P10/P50/P90</i>"]
    end

    DM --> STEP1
    STEP1 --> PARAMS
    PARAMS --> STEP2
    RMS --> STEP2
    STEP2 --> RAW
    RAW --> STEP3
    STEP3 --> STAT

    classDef input fill:#fff3cd,stroke:#d39e00,color:#333
    classDef output fill:#d4edda,stroke:#155724,color:#333
    classDef activity fill:#e8f5f5,stroke:#007079,color:#333
    class DM,PARAMS,RMS input
    class RAW,STAT output
    class STEP1,STEP2,STEP3 activity
```

---

## 6. Worked Example: Seismic Interpretation

> For a complete seismic interpretation Activity template and worked example (horizon picking, fault interpretation, depth conversion, structure maps), see [SeisInt § Activity Provenance](/howto/seismic-interp).

The key pattern: seismic interpretation Activities use `Input` parameters for the seismic survey and velocity model, and `Output` parameters for each horizon, fault surface, and structure map produced. Use `Keys[]` to tag multiple outputs of the same type (e.g., `{"ParameterKey": "horizon", "StringParameterKey": "TopVolantis"}`).

---

## 7. Worked Example: QC / Validation

Quality check workflows verify data integrity before it enters a decision gate.

### 7.1 Template Definition

```json
{
  "kind": "osdu:wks:work-product-component--ActivityTemplate:1.0.0",
  "data": {
    "Name": "QC / Validation Workflow",
    "Description": "Quality check and validation of subsurface data before gate submission",
    "ParameterTemplates": [
      {
        "Title": "InputData",
        "Description": "Record(s) being validated",
        "IsInput": true, "IsOutput": false,
        "MinOccurs": 1, "MaxOccurs": 10,
        "DefaultParameterKind": "DataObject"
      },
      {
        "Title": "QCMethod",
        "Description": "Validation method or script name",
        "IsInput": true, "IsOutput": false,
        "MinOccurs": 1, "MaxOccurs": 1,
        "DefaultParameterKind": "string"
      },
      {
        "Title": "AcceptanceCriteria",
        "Description": "Pass/fail criteria description",
        "IsInput": true, "IsOutput": false,
        "MinOccurs": 0, "MaxOccurs": 1,
        "DefaultParameterKind": "string"
      },
      {
        "Title": "QCResult",
        "Description": "Pass/Fail/Warning result",
        "IsInput": false, "IsOutput": true,
        "MinOccurs": 1, "MaxOccurs": 1,
        "DefaultParameterKind": "string"
      },
      {
        "Title": "QCReport",
        "Description": "Validation report document",
        "IsInput": false, "IsOutput": true,
        "MinOccurs": 0, "MaxOccurs": 1,
        "DefaultParameterKind": "DataObject"
      }
    ]
  }
}
```

### 7.2 Activity Example

```json
{
  "kind": "osdu:wks:work-product-component--Activity:1.0.0",
  "data": {
    "Name": "Drogon DG2 Volume QC",
    "Description": "Cross-check P50 STOIIP against analogue fields; verify material balance closure within 5%; check segment contributions sum to total.",
    "ActivityTemplateID": "dev:work-product-component--ActivityTemplate:qc-template:1",
    "WorkflowStatus": "Completed",
    "Parameters": [
      {
        "Title": "InputData",
        "ParameterKindID": "dev:reference-data--ParameterKind:DataObject:",
        "ParameterRoleID": "dev:reference-data--ParameterRole:Input:",
        "DataObjectParameter": "dev:work-product-component--ReservoirEstimatedVolumes:drogon-stats:1"
      },
      {
        "Title": "QCMethod",
        "ParameterKindID": "dev:reference-data--ParameterKind:String:",
        "ParameterRoleID": "dev:reference-data--ParameterRole:Input:",
        "StringParameter": "Analogue comparison + material balance + segment QC"
      },
      {
        "Title": "QCResult",
        "ParameterKindID": "dev:reference-data--ParameterKind:String:",
        "ParameterRoleID": "dev:reference-data--ParameterRole:Output:",
        "StringParameter": "Pass"
      }
    ]
  }
}
```

---

## 8. Worked Example: FMU / ERT Ensemble Workflow

> For the complete FMU → OSDU Activity mapping, template definition, and data flow, see [FMU → OSDU § Activity](/howto/fmu-osdu) and [Uncertainty § Run Bookkeeping](/howto/uncertainty).

The key FMU Activity pattern:
- **Inputs**: Design matrix (`ColumnBasedTable`), forward model chain (string), ensemble name, number of realisations, case collection
- **Outputs**: Raw `ReservoirEstimatedVolumes` (per-realisation), statistical REV (P10/P50/P90), output surfaces
- **Provenance**: The Activity makes the implicit `fmu.realization.id` chain **explicit** - linking design matrix rows to specific output volumes via `Keys[realisation-index]`

---

## 9. Linking Activities to BusinessDecision

Activities connect to `BusinessDecision` records through two mechanisms:

### 9.1 `PriorActivityIDs`

The `BusinessDecision` schema has a built-in `PriorActivityIDs` array that directly references Activity records:

```json
{
  "kind": "osdu:wks:master-data--BusinessDecision:1.0.0",
  "data": {
    "Name": "Drogon DG2 - Concept Select",
    "PriorActivityIDs": [
      "dev:work-product-component--Activity:drogon-dg1-volumetrics:1",
      "dev:work-product-component--Activity:drogon-seisint-2025:1"
    ]
  }
}
```

### 9.2 `Parameters[]` with Activity Reference

Alternatively, reference the Activity as a `DataObject` parameter in the BD's own `Parameters[]`:

```json
{
  "Title": "Volumetrics Workflow",
  "ParameterKindID": "dev:reference-data--ParameterKind:DataObject:1",
  "ParameterRoleID": "dev:reference-data--ParameterRole:Input:1",
  "DataObjectParameter": "dev:work-product-component--Activity:drogon-volumetrics:1",
  "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "Activity-volumetrics"}]
}
```

### 9.3 Complete Gate → Activity Chain

```mermaid
graph TD
    subgraph "Decision Gate"
        BD["BusinessDecision<br/><i>DG2 - Concept Select</i>"]
    end

    subgraph "Activities (Provenance)"
        ACT_VOL["Activity<br/><i>Volumetrics Run</i>"]
        ACT_SEIS["Activity<br/><i>Seismic Interpretation</i>"]
        ACT_QC["Activity<br/><i>Volume QC</i>"]
    end

    subgraph "Evidence (Outputs)"
        REV["REV - Statistics"]
        SM["StructureMaps"]
        GLS["GeoLabelSet"]
        RISK["Risk Records"]
        DOCS["Documents<br/><i>SRA, CRA</i>"]
    end

    BD -->|PriorActivityIDs| ACT_VOL
    BD -->|PriorActivityIDs| ACT_SEIS
    BD -->|PriorActivityIDs| ACT_QC
    BD -->|Parameters-Input| REV
    BD -->|RiskIDs| RISK
    BD -->|RiskAssessmentDocument| DOCS

    ACT_VOL -->|Output| REV
    ACT_VOL -->|Output| GLS
    ACT_SEIS -->|Output| SM
    ACT_QC -->|Input| REV

    classDef bd fill:#e2d9f3,stroke:#5a3e85,color:#333
    classDef act fill:#e8f5f5,stroke:#007079,color:#333
    classDef evidence fill:#d4edda,stroke:#155724,color:#333
    classDef risk fill:#fff0f3,stroke:#ff1243,color:#333
    class BD bd
    class ACT_VOL,ACT_SEIS,ACT_QC act
    class REV,SM,GLS evidence
    class RISK,DOCS risk
```

---

## 10. Entity Relationship Diagrams

### 10.1 Full Activity Data Model

```mermaid
classDiagram
    direction TB

    class ActivityTemplate {
        +Name: string
        +Description: string
        +Originator: string
        +ParameterTemplates[]: ParameterSlot
    }

    class Activity {
        +Name: string
        +Description: string
        +ActivityTemplateID: ref
        +WorkflowStatus: enum
        +CreationDateTime: datetime
        +ParentObjectID: ref
        +Parameters[]: ParameterValue
    }

    class ParameterSlot {
        +Title: string
        +Description: string
        +IsInput: boolean
        +IsOutput: boolean
        +MinOccurs: integer
        +MaxOccurs: integer
        +DefaultParameterKind: enum
    }

    class ParameterValue {
        +Title: string
        +ParameterKindID: ref
        +ParameterRoleID: ref
        +StringParameter: string
        +IntegerParameter: integer
        +DataObjectParameter: ref
        +Keys[]: KeyEntry
    }

    class BusinessDecision {
        +Name: string
        +PriorActivityIDs[]: ref
        +Parameters[]: ParameterValue
        +RiskIDs[]: ref
    }

    ActivityTemplate "1" --> "*" ParameterSlot : defines
    Activity "1" --> "*" ParameterValue : contains
    Activity "*" --> "1" ActivityTemplate : implements
    BusinessDecision "*" --> "*" Activity : PriorActivityIDs
```

---

## 11. Creating Activities via the ORES Web UI

The ORES web app provides an interactive **Activity tab** at [/add-dg](/add-dg) with two sub-tabs:

### 11.1 Create Template Sub-tab

1. **Choose a preset** or start from scratch:
   - **Custom** - empty template (build from scratch)
   - **Reservoir Simulation** - pre-populates slots for multi-realisation simulation (InputParameters, Process, NumberOfRealizations, Variables, DesignMatrix → OutputVolumes, ReportTable)
   - **FMU Ensemble** - full ERT + forward model chain (CaseCollection, DesignMatrix, ForwardModel, Simulator, InputSurfaces → OutputVolumes, OutputStatistics, OutputSurfaces, OutputProfiles)
   - **Drilling & Completion** - well drilling activity (WellDesign, TrajectoryPlan, RigContract, SpudDate, TDDate → ActualTrajectory, CompletionReport, EOWR)
   - **Production Test** - DST / PLT / well test (Well, TestType, TestDuration → FlowRate, Pressure, TestReport)
   - **Interpretation** - seismic / geo interpretation session
   - **QC / Validation** - quality check workflow

2. **Fill template basics**: name, description, originator

3. **Define parameter slots**: add input/output slots with title, description, expected kind, and cardinality

4. **Preview & ingest**: review the JSON payload and submit to OSDU Storage API

### 11.2 Create Activity Sub-tab

1. **Fill activity basics**: name, description, originator, workflow status, execution date

2. **Link a template**: paste the ActivityTemplate record ID and click **Load Slots** to auto-populate parameter rows from the template definition

3. **Fill parameter values**: provide actual values for each slot - strings, integers, or OSDU record IDs for DataObject parameters

4. **Add extra parameters**: add parameters beyond what the template defines if needed

5. **Preview & ingest**: review and submit

### 11.3 Create Schedule Template Sub-tab (ActivityStateTemplate)

The **Schedule Template** sub-tab (under the Activity section) lets you define reusable milestone sequences for project lifecycle tracking:

1. **Name & description**: Give the template a meaningful name (e.g. "CCS Project Lifecycle")
2. **Project Type**: Select or paste a `ProjectTypeID` reference
3. **Define milestones**: Add rows with Sequence, MilestoneID (short code), Name (display), and TypicalDurationMonths
4. **Preview & ingest**: Creates a `work-product-component--ActivityStateTemplate` WPC record

Created templates are immediately available in the Decision Gate tab's "Schedule / Milestones" picker.

### 11.4 Quick Guide Popup

Click the **? Guide** button next to the Activity tab header to open the inline quick-reference popup. It shows:
- Template → Activity relationship diagram
- Parameter slot field reference
- Parameter value field reference
- Tips for using presets and the Load Slots feature

For this full guide, visit [/howto/activity](/howto/activity) or navigate via the HowTo documentation index.

---

## 12. Creating Activities via Pipeline Scripts

### 12.1 Generator Script Pattern

The `demo/drogon/gen_activity_drogon.py` script demonstrates the pipeline approach:

```bash
# Generate the activity manifest (no OSDU interaction needed)
python demo/drogon/gen_activity_drogon.py

# Output: demo/drogon/manifest_activity_drogon.json
# Contains: ETPDataspace + ActivityTemplate + Activity records
```

Key patterns in the script:
- **Stable UUIDs** via `uuid5` for reproducible record IDs
- **Cross-manifest references**: reads Reservoir, WPC IDs from other manifests
- **ACL/legal inheritance**: copies from the parent Reservoir record
- **Serialised scenario data**: design matrix and variables stored as JSON strings in parameters

### 12.2 Pipeline Integration

Activities are typically step 5 in a full pipeline (after volumes, before the BusinessDecision):

```text
Step 0: Reference data (PropertyTypes, FacetRoles)
Step 1: Master data (Reservoir, Segments, WorkProduct)
Step 2: Raw REV (per-realisation volumes)
Step 3: Stat REV (aggregated P10/P50/P90)
Step 4: Input parameters (ColumnBasedTable)
Step 5: Activity + ActivityTemplate     ← here
Step 6: BusinessDecision (links to Activity via PriorActivityIDs)
Step 7: GeoLabelSet (headline KPIs)
Step 8: Ingest all records to OSDU
```

```bash
# Full pipeline with activity generation
python demo/run_pipeline.py demo/drogon

# Preview pipeline steps
python demo/run_pipeline.py --show demo/drogon
```

---

## 13. Best Practices

### Naming Conventions

| Convention | Example |
|------------|---------|
| Template name | `"<Field> - <Workflow Type> Template"` |
| Activity name | `"<Field> - <Workflow> Run <date/quarter>"` |
| Parameter titles | PascalCase, matching template slots exactly |
| Keys.ParameterKey | Lowercase with hyphens: `"artifact"`, `"horizon"`, `"fault"` |

### Design Principles

1. **One template per workflow type** - reuse across fields and gates
2. **One activity per execution** - even if the workflow has multiple steps, capture them as a single activity with multiple parameters
3. **Use `ParentObjectID`** to scope the activity to a Reservoir, Field, or Well
4. **Link DataObject parameters** to actual OSDU record IDs whenever possible
5. **Serialise complex data** (design matrices, variable configurations) as JSON strings in `StringParameter` fields
6. **Tag outputs with `Keys[]`** to distinguish multiple outputs of the same type (e.g. multiple horizons, multiple fault surfaces)

### Common Pitfalls

| Pitfall | Solution |
|---------|----------|
| Parameter `Title` mismatch between template and activity | Use exact same string; Load Slots auto-populates correctly |
| Missing `ParameterKindID` / `ParameterRoleID` | Always include ref-data references; the UI generates these automatically |
| Activities without template reference | Always set `ActivityTemplateID` for queryability |
| Orphaned activities (no BD link) | Set `PriorActivityIDs` on the BusinessDecision after creating the activity |
| Ingesting Activity before its DataObject outputs exist | Ingest outputs first, then the Activity, then the BD |

---

## 14. References

| Resource | Link |
|----------|------|
| OSDU Activity schema | [ActivityTemplate.1.0.0](https://community.opengroup.org/osdu/data/data-definitions/-/blob/master/E-R/work-product-component/ActivityTemplate.1.0.0.md) |
| OSDU Activity schema | [Activity.1.0.0](https://community.opengroup.org/osdu/data/data-definitions/-/blob/master/E-R/work-product-component/Activity.1.0.0.md) |
| AbstractProjectActivity | [AbstractProjectActivity.1.2.0](https://community.opengroup.org/osdu/data/data-definitions/-/blob/master/E-R/abstract/AbstractProjectActivity.1.2.0.md) |
| Drogon Activity generator | `demo/drogon/gen_activity_drogon.py` |
| Drogon Activity manifest | `demo/drogon/manifest_activity_drogon.json` |
| ORES Activity tab | `/add-dg` → Activity tab |
| BD guide | [BusinessDecision](/howto/business-decision) |
| BD Demo guide | [Drogon Demo](/howto/bd-demo) |
| Uncertainty guide | [Uncertainty](/howto/uncertainty) |
| SeisInt guide | [SeisInt](/howto/seismic-interp) |

---

## 15. ActivityStateTemplate - Schedule Milestone Blueprints

> **Not to be confused with `ActivityTemplate`** (workflow provenance blueprints). `ActivityStateTemplate` defines the **milestone sequence** for a project lifecycle, while `ActivityTemplate` defines parameter slots for workflow inputs/outputs.

### 15.1 Problem

The `ActivityStates[]` field on `BusinessDecision` and `CollaborationProject` (inherited from `AbstractProjectActivity`) uses free-text `Remark` fields for milestone names. This leads to:
- Inconsistent naming across instances
- Copy-paste of the same milestone sequence into every record
- No way to auto-scaffold milestones when creating a new BD/CP
- No controlled vocabulary for milestone identity

### 15.2 Solution: `ActivityStateTemplate` (WPC)

A `work-product-component--ActivityStateTemplate` record defines the ordered milestone sequence for a given project type. Instances reference the template and only supply dates + status overrides.

```json
{
  "kind": "osdu:wks:work-product-component--ActivityStateTemplate:1.0.0",
  "id": "dev:work-product-component--ActivityStateTemplate:FieldDevelopment:1",
  "data": {
    "Name": "Field Development Lifecycle",
    "Description": "Standard DG0–DG4 + execution milestones for NCS field development",
    "ProjectTypeID": "dev:reference-data--ProjectType:FieldDevelopment:",
    "Milestones": [
      {"Sequence": 1, "MilestoneID": "SSVP",      "Name": "SSVP / PVP Assessment",    "TypicalDurationMonths": null},
      {"Sequence": 2, "MilestoneID": "DG0",       "Name": "WPC Decision (DG0)",        "TypicalDurationMonths": 6},
      {"Sequence": 3, "MilestoneID": "DG1",       "Name": "DG1 Identify & Assess",     "TypicalDurationMonths": 6},
      {"Sequence": 4, "MilestoneID": "DG2",       "Name": "DG2 Concept Select",        "TypicalDurationMonths": 9},
      {"Sequence": 5, "MilestoneID": "DG3",       "Name": "DG3 FEED",                  "TypicalDurationMonths": 12},
      {"Sequence": 6, "MilestoneID": "DG4",       "Name": "FID / DG4 Sanction",        "TypicalDurationMonths": 6},
      {"Sequence": 7, "MilestoneID": "INSTALL",   "Name": "Subsea / Topsides Install", "TypicalDurationMonths": 12},
      {"Sequence": 8, "MilestoneID": "FIRST_OIL", "Name": "First Oil",                 "TypicalDurationMonths": 6},
      {"Sequence": 9, "MilestoneID": "PLATEAU",   "Name": "Plateau Production",        "TypicalDurationMonths": 12}
    ]
  }
}
```

### 15.3 Available Templates

| Template | ProjectType | Milestones | Use for |
|----------|-------------|------------|---------|
| **Field Development Lifecycle** | FieldDevelopment | SSVP→DG0→DG1→DG2→DG3→DG4→Install→First Oil→Plateau | Full-field greenfield projects |
| **Field Development Wells** | FieldDevWells | Well Concept→DG2→DG3→Rig→Spud→TD→Complete→Handover | Well delivery within approved dev |
| **Exploration Well** | ExplorationWell | Prospect ID→Play Mature→Drill Decision→Design→Spud→TD→Evaluate→Report | Exploration drilling |
| **CCS / Carbon Storage** | CCS | Site Screen→Permit→DG3→Appraisal→FID→Inject→Steady State→Monitor | Carbon storage projects |
| **IOR / Infill Campaign** | IOR | Screen→Feasibility→Concept→DG3→Execute→First Response→Evaluate | IOR within producing fields |
| **Decommissioning** | Decommissioning | COP→Decom Plan→Well P&A→Topsides→Subsea→Site Verify | Field removal projects |

### 15.4 Usage on BusinessDecision

When creating a BD, select a project type → the template auto-populates milestone rows. Only fill in dates and status for known milestones:

```json
{
  "kind": "osdu:wks:master-data--BusinessDecision:1.0.0",
  "data": {
    "Name": "Drogon - DG2 Concept Select",
    "DecisionLevelID": "dev:reference-data--DecisionLevel:DG2:",
    "ActivityStates": [
      {"MilestoneID": "DG1",       "ActivityStatusID": "dev:reference-data--ActivityStatus:Completed:", "EffectiveDateTime": "2025-12-15", "Remark": "DG1 Identify & Assess"},
      {"MilestoneID": "DG2",       "ActivityStatusID": "dev:reference-data--ActivityStatus:Completed:", "EffectiveDateTime": "2026-02-28", "Remark": "DG2 Concept Select"},
      {"MilestoneID": "DG3",       "ActivityStatusID": "dev:reference-data--ActivityStatus:Planned:",   "EffectiveDateTime": "2027-01-01", "Remark": "DG3 FEED"},
      {"MilestoneID": "DG4",       "ActivityStatusID": "dev:reference-data--ActivityStatus:Planned:",   "EffectiveDateTime": "2027-07-01", "Remark": "FID / DG4 Sanction"}
    ],
    "ext": {
      "equinor": {
        "ActivityStateTemplateID": "dev:work-product-component--ActivityStateTemplate:FieldDevelopment:1",
        "ProjectTypeID": "dev:reference-data--ProjectType:FieldDevelopment:"
      }
    }
  }
}
```

### 15.5 Comparison: ActivityTemplate vs ActivityStateTemplate

| | ActivityTemplate | ActivityStateTemplate |
|---|---|---|
| **Purpose** | Workflow provenance (what inputs/outputs a workflow produces) | Lifecycle milestones (what gates a project passes through) |
| **Schema** | `work-product-component--ActivityTemplate:1.0.0` | `work-product-component--ActivityStateTemplate:1.0.0` |
| **Defines** | Parameter slots (`ParameterTemplates[]`) | Milestone sequence (`Milestones[]`) |
| **Used by** | `Activity` (via `ActivityTemplateID`) | `BusinessDecision`, `CollaborationProject` (via `ext.equinor.ActivityStateTemplateID`) |
| **Reuse** | Same template for every simulation run | Same template for every field dev BD |

### 15.6 Creating via Web UI

The ORES [/add-dg](/add-dg) page supports full self-service creation of demo records without scripts:

| Tab | Section | Capability |
|-----|---------|------------|
| **Decision Gate** | 0. Project Preset | Pick a preset (Field Dev DG1, DG2, Exploration, CCS, etc.) → auto-fills milestones, alternatives, economics |
| **Decision Gate** | 3. Schedule / Milestones | Load a template → edit milestone dates and statuses → included in BD `ActivityStates[]` |
| **Decision Gate** | 6. Alternatives | Add ranked development alternatives (Name, Rank, RecommendedAction, Rationale) |
| **Decision Gate** | 7. Economics | Add KPIs (NPV, IRR, CAPEX, OPEX, etc.) with value and unit |
| **Activity** | Template presets | 7 presets: Custom, Reservoir Sim, FMU Ensemble, Drilling, Production Test, Interpretation, QC |
| **Activity** | Schedule Template | Create new `ActivityStateTemplate` WPC records with custom milestone sequences |

This enables **complete demo record creation entirely from the browser** — no `demo/` scripts needed.

### 15.7 Files

| File | Description |
|------|-------------|
| `demo/activity_state_templates.json` | All 6 ActivityStateTemplate WPC records |
| `demo/reference_data_project_types.json` | ProjectType reference data |
| `demo/ingest_schedule_templates.py` | Script to bulk-ingest templates + project types |
| `/add-dg` → Decision Gate tab | UI with project type selector and milestone scaffolding |
| `/add-dg` → Activity tab → Schedule Template | UI for creating new templates interactively |
