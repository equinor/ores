# Ontology Demo Examples

Enriched versions of Drogon DG1 records demonstrating ontology patterns
using **existing M27 OSDU schema fields** — no new kinds required.

## Patterns Demonstrated

| File | Pattern | M27 Field Used |
|------|---------|----------------|
| `cp_lifecycle_events.json` | Audit trail / change history | `LifecycleEvents[]` on CollaborationProject |
| `bd_relationship_keys.json` | Named relationship types | `Parameters[].Keys[ParameterKey]` |
| `cp_gate_checklist.json` | Gate completeness checklist | `ActivityStates[]` with custom MilestoneID |
| `activity_collaboration_action.json` | Actions as first-class verbs | Activity + ActivityTemplate |
| `bd_remarks_typed.json` | Typed annotations / comments | `Remarks[]` with RemarkSource categories |

## Key Convention: Relationship Keys

Instead of a new `RelationshipType` ref-data kind, use `Parameters[].Keys[]`:

```json
{
  "ParameterKey": "relationship",
  "StringParameterKey": "evidences"
}
```

Values: `evidences`, `informs`, `supersedes`, `constrains`, `mitigates`, `alternativeTo`

## Key Convention: LifecycleEvents EventID

Standard EventID values for audit trail:

- `CreationEvent` — record created
- `EvidenceAdded` — new artifact linked to gate package
- `RiskEscalation` — risk severity increased
- `RiskMitigation` — risk severity reduced or closed
- `VolumeUpdate` — volumes re-estimated
- `ApprovalGranted` — gate approved
- `StateTransition` — project lifecycle state change
- `AlternativeAdded` — new decision alternative registered

## Key Convention: Gate Checklist MilestoneID

Use `ActivityStates[]` with descriptive MilestoneID for required deliverables:

- `DG2-Volumes` — P10/P50/P90 reserve estimates
- `DG2-DevConcept` — development concept document
- `DG2-ProductionForecast` — production profile
- `DG2-Economics` — NPV/IRR/CAPEX analysis
- `DG2-RiskAssessment` — risk register with mitigations
- `DG2-GeoModel` — structural + property model via RDDMS
- `DG2-WellPlan` — producer/injector count + placement
- `DG2-FacilityDesign` — subsea architecture / FPSO selection
- `DG2-Approval` — gate decision vote

Status: `Completed`, `InProgress`, `Outstanding`, `Waived`
