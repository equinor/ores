# Ontology in OSDU — Using M27 Schemas as a Knowledge Graph

**ECIM 2026 — Conference Presentation Structure**

---

## Slide 1: Title

**"OSDU as an Ontology Platform: Relationship Semantics in M27 Without New Schemas"**

- Equinor / ORES Team
- ECIM 2026

---

## Slide 2: What Is an Ontology?

An ontology is a formal representation of knowledge:
- **Objects** (typed entities with attributes)
- **Relationships** (named, directed edges between objects)
- **Actions** (verbs that transform or link objects)
- **Lifecycle** (state transitions, audit trail, provenance)
- **Constraints** (rules, checklists, governance gates)

Traditional knowledge-graph platforms (e.g. Palantir Foundry, Neo4j) provide these as first-class primitives.

**Question**: Can OSDU M27 schemas deliver the same capabilities — without extensions?

---

## Slide 3: What's New — Our Discovery

**M27 already contains underutilized fields that implement ontology patterns.**

No new `kind` definitions. No schema proposals. Just conventions on existing fields.

| Ontology Pattern | M27 Field | Used How |
|---|---|---|
| **Named relationships** | `Parameters[].Keys[ParameterKey="relationship"]` | Edge type: `evidences`, `supersedes`, `constrains`, `mitigates`, `alternativeTo`, `informs` |
| **Audit trail** | `CollaborationProject.LifecycleEvents[]` | Timestamped events: approvals, escalations, revisions |
| **Gate checklist** | `ActivityStates[]` with prefixed `MilestoneID` | Required deliverables per gate with completion status |
| **Actions as verbs** | `Activity` + `ActivityTemplate` | Each user action = one Activity record with typed Parameters |
| **Typed annotations** | `Remarks[]` with `RemarkSource` | Categorised notes: RISK, RECOMMENDATION, ECONOMIC, TECHNICAL |
| **Evidence packages** | `PersistedCollection` → `Parameters[]` | Frozen artifact sets linked to decisions |

---

## Slide 4: Example — Drogon DG1 → DG2 Lifecycle

```
BusinessDecision (DG1)          BusinessDecision (DG2)
  ├─ evidences → REV-Statistics    ├─ supersedes → DG1 REV
  ├─ evidences → GeoLabelSet       ├─ evidences → DG2 REV  
  ├─ informs   → InputParameters   ├─ alternativeTo → ReducedScope
  ├─ evidences → ETPDataspace      ├─ constrains → WaterBreakthroughRisk
  └─ constrains → PorosityRisk     └─ evidences → DG2 ETPDataspace

CollaborationProject (cross-gate)
  ├─ LifecycleEvents[]: 12 events (approvals, volume revisions, risk changes)
  ├─ ActivityStates[]: 9 gate items, all completed
  └─ Parameters[]: 6 linked artifacts (dataspaces, volumes, evidence)
```

**Key insight**: The `Keys[ParameterKey="relationship"]` pattern turns every `Parameters[]` entry into a typed, directed edge.

---

## Slide 5: Example — Omega Sør SSVP (Real Data)

| Property | Value |
|---|---|
| Decision | WPC (Well Planning Committee) |
| NPV | 116 MUSD (P50 economics case) |
| IRR | 62% |
| Breakeven | 25 USD/bbl |
| STOIIP Mean | 19.3 MSm³ |
| Risks | 8 (barium scale, injectivity, shallow gas, H₂S, …) |
| Relationships | 11 Parameters with named edge types |
| Remarks | 14 typed (RISK, RESERVOIR, DRILLING, ECONOMIC, SCHEDULE) |
| Gate Checklist | 8/9 items completed |
| Lifecycle Events | 8 (pilot results, volume upgrades, BoD approval, …) |

All stored in standard `BusinessDecision` + `CollaborationProject` M27 schemas.
No custom kinds. No schema extensions beyond `ext.equinor.Alternatives[]`.

---

## Slide 6: What Is the Gain?

### For Subsurface Teams
- **Decision traceability**: Every decision links to its evidence chain
- **Cross-gate tracking**: See how volumes, risks, and economics evolve DG1→FID
- **Gate readiness at a glance**: Progress bar shows 7/9 items linked (what's missing?)
- **Risk lifecycle**: Track escalation, mitigation, addition across gates

### For Data Management
- **No new schemas to propose/review/approve** — weeks of community process saved
- **Portable**: Works on any M27-compliant OSDU instance (interop-verified)
- **Discoverable**: Relationships queryable via standard OSDU search API
- **Versionable**: Parameters[] versioned with the record; LifecycleEvents[] append-only

### For Platform Teams
- **Zero infrastructure cost**: No graph database, no additional services
- **Schema-validated**: All edges pass OSDU schema validation
- **Indexable**: Keys[] values indexed for search; relationship queries possible today

---

## Slide 7: Requirements & Challenges

### What's Needed
1. **Conventions** — Agreement on `ParameterKey` values (only 6 edge types needed)
2. **Reference data** — New MilestoneID entries per gate type (trivial)
3. **Application logic** — Enrichment code to follow links and render graphs
4. **Culture change** — Teams must populate Parameters[] and LifecycleEvents[] (currently sparse)

### Current Challenges
| Challenge | Severity | Mitigation |
|---|---|---|
| No OSDU-standard edge-type vocabulary | Medium | Propose ref-data: `evidences`, `supersedes`, `constrains`, `mitigates`, `alternativeTo`, `informs` |
| LifecycleEvents[] rarely populated today | Medium | Auto-populate on state change (via ORES addgate workflow) |
| No reverse-link query in OSDU Search | Low | Search by DataObjectParameter value (works today) |
| No real-time push notifications | Low | Not blocking for ontology; nice-to-have for collaboration |
| `ext.equinor.Alternatives[]` is operator-specific | Low | Decision alternatives can also use Parameters[] with `alternativeTo` key |

---

## Slide 8: Implementation — What We Built

### Demo Stack (ORES)
```
┌─────────────────────────────────────────────────────┐
│  OSDU M27 Storage (Azure ADME)                       │
│    BusinessDecision, CollaborationProject,           │
│    Activity, Risk, REV, PersistedCollection          │
├─────────────────────────────────────────────────────┤
│  ORES Backend (Python FastAPI)                       │
│    bd_enrichment.py → _enrich_bd_collaboration()     │
│    search_router.py → 7-task parallel gather         │
├─────────────────────────────────────────────────────┤
│  ORES Frontend (Jinja2 + Chart.js + Mermaid)         │
│    bd_ontology_panels.html → Gate + Graph + Timeline │
└─────────────────────────────────────────────────────┘
```

### Deployed Records
| Instance | Dataset | Records |
|---|---|---|
| **interop** (ADME Interop) | Drogon DG1 | 1 BD |
| **eqndev** (Equinor SWE Dev) | Drogon DG1 + DG2 | 2 BD + 1 CP + 2 Activity |
| **eqndev** | Omega Sør WPC | 1 BD + 1 CP |

### GUI Additions
- **Gate Readiness Panel**: Progress bar + checklist grid (from ActivityStates[])
- **Relationship Graph**: Mermaid flowchart (from Parameters[].Keys[])
- **Activity Timeline**: Vertical CSS timeline (from LifecycleEvents[])
- **Typed Remarks**: Color-coded by RemarkSource category

---

## Slide 9: Further Use Cases

| Use Case | Ontology Pattern | OSDU Implementation |
|---|---|---|
| **FMU ensemble tracking** | Actions (batch runs) | Activity records per realization, linked via ActivityTemplate |
| **Well decision tree** | Alternatives + constraints | Parameters[alternativeTo] between WellPlan BDs |
| **CCS monitoring lifecycle** | Audit trail + risk evolution | LifecycleEvents[] on CP; Risk records linked per injection period |
| **IOR screening** | Evidence chain + comparison | PersistedCollections per IOR method; analyse.py for side-by-side |
| **License round portfolio** | Multi-gate governance | One CP per license; gate checklists per regulatory milestone |
| **Asset handover** | Provenance + completeness | PersistedCollection completeness vs. ActivityStates[] checklist |

All implementable with the same M27 field patterns — only reference-data definitions vary.

---

## Slide 10: Status & Outlook

### What Exists Today ✅
- M27 schemas with all required fields (deployed since M27 release)
- ORES demo with enrichment, rendering, and ingestion (this branch)
- Verified on 2 OSDU instances (eqndev + interop)
- 7 ontology patterns demonstrated with real and synthetic data
- GUI panels operational (gate checklist, relationship graph, timeline)

### Next Steps (Roadmap)
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
> The schemas have the fields. What was missing was the conventions —
> and now we have them.

Six relationship types. One key convention (`ParameterKey="relationship"`).
Zero new schemas. Full decision lifecycle coverage.

---

## Appendix A: Relationship Type Vocabulary

| Edge Type | Semantics | Example |
|---|---|---|
| `evidences` | A supports/proves B | REV → BD (volumes prove the decision) |
| `supersedes` | A replaces B | DG2 ETPDataspace → DG1 ETPDataspace |
| `constrains` | A limits/bounds B | Risk → BD (risk constrains decision space) |
| `mitigates` | A reduces impact of B | Seismic study → Fault risk |
| `alternativeTo` | A is a variant of B | ReducedScope BD → FullField BD |
| `informs` | A provides context to B | InputParameters → BD |

## Appendix B: Record Structure (JSON)

```json
{
  "Parameters": [{
    "Title": "Geomodel dataspace",
    "DataObjectParameter": "dev:dataset--ETPDataspace:maap-drogon_dg:1",
    "Keys": [
      {"ParameterKey": "artifact", "StringParameterKey": "ETPDataspace"},
      {"ParameterKey": "relationship", "StringParameterKey": "evidences"}
    ]
  }]
}
```

The `Keys[]` array adds metadata to any parameter link — transforming a simple reference into a typed, semantically rich edge.

## Appendix C: File References

| File | Content |
|---|---|
| `demo/drogon_dg1/ontology_examples/` | 8 synthetic Drogon records (DG1→DG2) |
| `demo/eqn/omegas/ontology_examples/` | 2 real Omega Sør records (WPC/SSVP) |
| `app/bd_enrichment.py` | Backend enrichment (resolves CP, checklist, relationships) |
| `app/templates/bd_ontology_panels.html` | GUI components (gate, graph, timeline) |
| `todo.md` | Full roadmap with tier classification |
