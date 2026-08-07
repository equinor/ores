# Ontology Patterns in OSDU M27

**ECIM 2026 - Conference Presentation**

---

## Slide 1: Title

**"OSDU as an Ontology Platform: Relationship Semantics with M27 Schemas"**

- Equinor / ORES Team
- ECIM 2026

---

## Slide 2: Motivation - Why Ontology?

Subsurface decisions are complex webs of evidence, alternatives, risks, and stakeholders:

- A DG2 concept-select links to **volumes, risks, geomodels, forecasts, prior gates, and alternative concepts**
- Teams need to trace **why** a decision was made - not just what was decided
- Cross-gate tracking (DG1→DG2→DG3→FID) requires **relationship continuity** across years
- Regulatory and partner reviews demand **auditable evidence chains**

Today this knowledge lives in slide decks, spreadsheets, and people's heads.

**Ontology** = formalised knowledge with typed relationships, lifecycle, provenance, and constraints.

Traditional solutions (Palantir Foundry, Neo4j) require separate graph infrastructure. Can we achieve the same within OSDU?

---

## Slide 3: Use Cases

| Use Case | What Teams Need | Ontology Pattern |
|---|---|---|
| **Decision traceability** | Link every DG decision to its evidence chain | Named relationships (evidences, supersedes) |
| **Cross-gate tracking** | See how volumes/risks/economics evolve DG1→FID | Lifecycle events + audit trail |
| **Gate readiness** | "What's missing?" before a gate review | Gate checklist with completion status |
| **Risk lifecycle** | Track escalation, mitigation, addition per gate | Relationship edges (constrains, mitigates) |
| **Alternative comparison** | Compare 3 development concepts side-by-side | alternativeTo edges between records |
| **Provenance** | Who changed what, when, with what impact | Activity records as first-class verbs |
| **Evidence packages** | Frozen artifact bundles for regulatory review | PersistedCollections linked to decisions |

---

## Slide 4: Strategy - Reusing M27 Fields as Ontology Primitives

**M27 already contains underutilised fields that implement ontology patterns.**

No new `kind` definitions needed. Conventions on existing fields.

| Ontology Pattern | M27 Field | Used How |
|---|---|---|
| **Named relationships** | `Parameters[].Keys[ParameterKey="relationship"]` | Edge type: `evidences`, `supersedes`, `constrains`, `mitigates`, `alternativeTo`, `informs` |
| **Audit trail** | `CollaborationProject.LifecycleEvents[]` | Timestamped events: approvals, escalations, revisions |
| **Gate checklist** | `ActivityStates[]` with prefixed `MilestoneID` | Required deliverables per gate with completion status |
| **Actions as verbs** | `Activity` + `ActivityTemplate` | Each user action = one Activity record with typed Parameters |
| **Typed annotations** | `Remarks[]` with `RemarkSource` | Categorised notes: Recommendation, Condition, Risk, Audit |
| **Evidence packages** | `PersistedCollection` → `Parameters[]` | Frozen artifact sets linked to decisions |

The key insight: `Keys[ParameterKey="relationship"]` turns every `Parameters[]` entry into a **typed, directed edge** - giving OSDU the expressiveness of a graph database.

---

## Slide 5: Drogon Example - DG1 → DG2 Decision Lifecycle

### The Story

Drogon field, Valysar formation. DG1 (Identify & Assess) approved Feb 2026.
Between gates: porosity downgrade (0.18→0.14), new risks added, 4D seismic confirms fault communication.
DG2 (Concept Select) approved May 2026 - full 7-segment subsea tieback.

### Ontology Structure

```
BusinessDecision: Drogon DG2 - Concept Select
│
├── supersedes → BD: Drogon DG1 (prior gate)
│
├── evidences  → REV-Statistics (P50 STOIIP 287 MSm³)
├── evidences  → ETPDataspace (updated geomodel, structural uncertainty)
├── evidences  → PersistedCollection (99-artifact evidence package)
│
├── informs    → ProductionForecast (20-year OPM Flow, 7P/3I)
├── informs    → DevelopmentConcept: Full 7-segment (APPROVED)
│
├── alternativeTo → DevelopmentConcept: Reduced scope (REJECTED)
│
├── constrains → Risk: Porosity & Cementation (ESCALATED Med→High)
├── constrains → Risk: Water Breakthrough (NEW)
├── constrains → Risk: Subsea Tieback Distance (NEW)
├── mitigates  → Risk: Fault Compartment (4D confirms: High→Low)
│
├── supersedes → ETPDataspace DG1 (prior geomodel)
└── supersedes → REV DG1 (prior volumes)

CollaborationProject: Drogon Geomodelling
├── LifecycleEvents[]: 12 events (approvals, volume revisions, risk changes)
├── ActivityStates[]:  9 gate items (8 completed, 1 outstanding: core data)
└── Parameters[]:      6 linked artifacts (dataspaces, volumes, evidence, forecast)

Activity: Volume Update - Porosity Revision
├── informs    → BusinessDecision DG2
├── supersedes → REV DG1 (old volumes)
├── evidences  → REV DG2 (new volumes)
└── StringParameter: "Porosity revised 0.18→0.14 (core data)"
```

### Key Numbers (Drogon Demo Data)

| Metric | DG1 | DG2 | Delta |
|---|---|---|---|
| P50 STOIIP (MSm³) | 312 | 287 | −8% |
| Recoverable Oil P50 (MSm³) | 14.8 | 14.8 | - |
| Recovery Factor | 32.5% | 32.5% | - |
| Risks | 2 | 4 | +2 new |
| NPV (MUSD) | - | 520 | - |
| Alternatives evaluated | - | 3 | - |
| Relationship edges | 5 | 13 | +8 |
| Lifecycle events (CP) | 3 | 12 | +9 |
| Gate checklist items | - | 9 (8✓ + 1 outstanding) | - |
| Typed remarks (BD) | 3 | 16 | +13 |

---

## Slide 6: Live Demo - ORES Rendering of Drogon DG2

### What ORES Shows (deployed at ores.radix.equinor.com)

1. **Search** → kind `BusinessDecision` → select "Drogon DG2 - Concept Select"
2. **Detail view** shows:
   - **Gate Readiness Panel**: Progress bar (8/9 = 89%) + checklist grid
   - **Relationship Graph**: Mermaid flowchart of all 13 typed edges
   - **Activity Timeline**: Vertical timeline from LifecycleEvents[]
   - **Typed Remarks**: Color-coded by source (Recommendation, Condition, Dissent, Audit)
   - **Economics**: NPV 520 MUSD, IRR 17%, breakeven 42 USD/bbl
   - **Alternatives**: 3 concepts ranked with rationale
   - **Uncertainty Summary**: 250 realisations, P10/P50/P90 distributions

3. **Analyse** → Reservoir "Drogon" → side-by-side DG1 vs DG2:
   - Volume deltas across gates
   - Risk evolution (added, escalated, mitigated)
   - Property comparison

### Implementation Stack

```
┌─────────────────────────────────────────────────────┐
│  OSDU M27 Storage (Azure ADME)                       │
│    BusinessDecision, CollaborationProject,           │
│    Activity, Risk, REV, PersistedCollection          │
├─────────────────────────────────────────────────────┤
│  ORES Backend (Python FastAPI)                       │
│    bd_enrichment.py → follows relationship edges     │
│    search_router.py → 7-task parallel enrichment     │
├─────────────────────────────────────────────────────┤
│  ORES Frontend (Jinja2 + Chart.js + Mermaid)         │
│    bd_ontology_panels.html → Gate + Graph + Timeline │
└─────────────────────────────────────────────────────┘
```

### Deployed Records

| Instance | Dataset | Records |
|---|---|---|
| **interop** (ADME Interop) | Drogon DG1 + DG2 | 2 BD + 1 CP + 1 AT + 1 Activity |
| **eqndev** (Equinor SWE Dev) | Drogon DG1 + DG2 | 2 BD + 1 CP + 1 AT + 1 Activity |

---

## Slide 7: What Is the Gain?

### For Subsurface Teams
- **Decision traceability**: Every decision links to its full evidence chain
- **Cross-gate tracking**: See how volumes, risks, and economics evolve DG1→FID
- **Gate readiness at a glance**: Progress bar shows what's complete and what's missing
- **Risk lifecycle**: Track escalation, mitigation, and addition across gates
- **Alternative analysis**: Compare development concepts with traceability

### For Data Management
- **No new schemas** - uses existing M27 fields with consistent conventions
- **Portable**: Works on any M27-compliant OSDU instance (verified on interop + eqndev)
- **Discoverable**: Relationships queryable via standard OSDU search API
- **Versionable**: Parameters[] versioned with the record; LifecycleEvents[] append-only

### For Platform Teams
- **Zero infrastructure cost**: No graph database, no additional services
- **Schema-validated**: All edges pass OSDU schema validation
- **Indexable**: Keys[] values indexed for search; relationship queries work today

---

## Slide 8: Requirements & Challenges

### What's Needed
1. **Conventions** - Agreement on `ParameterKey` values (6 edge types)
2. **Reference data** - MilestoneID entries per gate type (trivial to create)
3. **Application logic** - Enrichment code to follow links and render graphs
4. **Culture** - Teams populate Parameters[] and LifecycleEvents[] consistently

### Current Challenges

| Challenge | Severity | Mitigation |
|---|---|---|
| No OSDU-standard edge-type vocabulary | Medium | Propose ref-data: `evidences`, `supersedes`, `constrains`, `mitigates`, `alternativeTo`, `informs` |
| LifecycleEvents[] rarely populated today | Medium | Auto-populate on state change (ORES addgate workflow) |
| No reverse-link query in OSDU Search | Low | Search by DataObjectParameter value (works today) |
| `ext.equinor.*` fields are operator-specific | Low | Core patterns use only standard M27 fields; ext is optional enrichment |

---

## Slide 9: Further Use Cases

| Use Case | Ontology Pattern | OSDU Implementation |
|---|---|---|
| **FMU ensemble tracking** | Actions (batch runs) | Activity records per realisation, linked via ActivityTemplate |
| **Well decision tree** | Alternatives + constraints | Parameters[alternativeTo] between WellPlan BDs |
| **CCS monitoring lifecycle** | Audit trail + risk evolution | LifecycleEvents[] on CP; Risk records linked per injection period |
| **IOR screening** | Evidence chain + comparison | PersistedCollections per IOR method; side-by-side analysis |
| **License round portfolio** | Multi-gate governance | One CP per license; gate checklists per regulatory milestone |
| **Asset handover** | Provenance + completeness | PersistedCollection completeness vs. ActivityStates[] checklist |

All implementable with the same M27 field patterns - only reference-data definitions vary.

---

## Slide 10: Status & Outlook

### What Exists Today
- M27 schemas with all required fields (deployed since M27 release)
- ORES demo with enrichment, rendering, and ingestion (deployed on Radix)
- Verified on 2 OSDU instances (eqndev + interop)
- 7 ontology patterns demonstrated with Drogon DG1→DG2 data
- GUI panels operational: gate checklist, relationship graph, timeline, typed remarks
- Generic generators for repeatable ontology record creation (`demo/scripts/generators/gen_ontology.py`)

### Next Steps

| Item | Tier | Effort |
|---|---|---|
| Propose relationship ref-data to OSDU Forum | Convention | 1 week |
| Visual provenance DAG (D3 interactive graph) | A | 1-2 days |
| Alternative comparison view (side-by-side BDs) | A | 2 days |
| Object relationship explorer (clickable graph) | A | 2-3 days |
| Cross-gate risk swimlane timeline | A | 1-2 days |
| RDDMS graph traversal (OSDU→RESQML boundary) | B | 3-5 days |
| Auto-populate LifecycleEvents[] on addgate | B | 1 day |
| Real-time collaboration feed (SSE) | C | Significant |

### OSDU Community Actions Needed
1. **Standardise edge-type vocabulary** as reference-data entries
2. **Document LifecycleEvents[] usage** in CollaborationProject best practices
3. **Add reverse-link search support** (search by DataObjectParameter target)

---

## Slide 11: Key Takeaway

> **OSDU M27 is already an ontology platform.**
> The schemas have the fields. What was missing was the conventions -
> and now we have them.

Six relationship types. One key convention (`ParameterKey="relationship"`).
Full decision lifecycle coverage from DG1 through FID.

---

## Appendix A: Relationship Type Vocabulary

| Edge Type | Semantics | Drogon Example |
|---|---|---|
| `evidences` | A supports/proves B | REV-Statistics → BD (volumes prove the decision) |
| `supersedes` | A replaces B | DG2 ETPDataspace → DG1 ETPDataspace |
| `constrains` | A limits/bounds B | Porosity Risk → BD (risk constrains decision space) |
| `mitigates` | A reduces impact of B | 4D Seismic → Fault Compartment Risk |
| `alternativeTo` | A is a variant of B | Reduced-Scope Concept → Full-Scope Concept |
| `informs` | A provides context to B | Production Forecast → BD |

## Appendix B: Record Structure (JSON)

```json
{
  "Parameters": [{
    "Title": "Updated geomodel (RDDMS)",
    "Selection": "Post-DG1: structural uncertainty + porosity revised",
    "DataObjectParameter": "dev:dataset--ETPDataspace:maap-drogon_dg2:1",
    "ParameterKindID": "dev:reference-data--ParameterKind:DataObject:",
    "ParameterRoleID": "dev:reference-data--ParameterRole:InputReference:",
    "Keys": [
      {"ParameterKey": "artifact", "StringParameterKey": "ETPDataspace"},
      {"ParameterKey": "relationship", "StringParameterKey": "evidences"}
    ]
  }]
}
```

The `Keys[]` array adds metadata to any parameter link - transforming a simple reference into a typed, semantically rich edge.

## Appendix C: File References

| File | Content |
|---|---|
| `demo/ontology/specs/` | All ontology generator specs (Drogon DG1/DG2, Omegas WPC) |
| `demo/ontology/ingest.py` | Unified generate + ingest script |
| `demo/scripts/generators/gen_ontology.py` | Generic ontology record generator |
| `app/bd_enrichment.py` | Backend enrichment (resolves CP, checklist, relationships) |
| `app/templates/bd_ontology_panels.html` | GUI components (gate, graph, timeline) |
| `md/BusinessDecision.md` | BD schema & linking patterns guide |
| `md/Activity.md` | Activity & ActivityTemplate guide |
| `md/BdDemo.md` | Drogon demo walkthrough |
| `md/DevConcept.md` | DevelopmentConcept schema reference |
| `md/Risk.md` | Risk data management approach |
