# OSDU as System of Record for Subsurface Decision Gates

**ECIM 2026 - Conference Presentation (12 min)**

---

## Slide 1: Title

**"OSDU as System of Record for Subsurface Decision Gates."**

- Equinor / ORES Team
- ECIM 2026

---

## Slide 2: Motivation - The Decision Data Problem

Subsurface decisions are complex webs of evidence, alternatives, risks, and stakeholders:

- A DG2 concept-select links to **volumes, risks, geomodels, forecasts, prior gates, and alternative concepts**
- Teams need to trace **why** a decision was made - not just what was decided
- Cross-gate tracking (DG1→DG2→DG3→FID) requires **relationship continuity** across years
- Regulatory and partner reviews demand **auditable evidence chains**

Today this knowledge lives in slide decks, spreadsheets, and people's heads.

What's needed is a **typed relationship layer**: named, directed links between records with lifecycle, provenance, and constraints — a lightweight knowledge graph on top of the existing data model.

Can OSDU's existing schema and services support this without additional graph infrastructure?

---

## Slide 3: Use Cases

| Use Case | What Teams Need | Relationship Pattern |
|---|---|---|
| **Decision traceability** | Link every DG decision to its evidence chain | Named relationships (evidencedBy, supersedes) |
| **Cross-gate analysis** | How volumes/risks/economics evolve DG1→FID | Lifecycle events + cross-gate delta queries |
| **Gate readiness** | "What's missing?" before a gate review | Gate checklist with completion status |
| **Risk lifecycle** | Track escalation, mitigation, addition per gate | Typed edges (constrainedBy, mitigates) |
| **Alternative comparison** | Compare development concepts side-by-side | alternativeTo edges + ranked evaluation |
| **Provenance** | Who changed what, when, with what impact | Activity records as first-class verbs |
| **Evidence packages** | Frozen artifact bundles for regulatory review | PersistedCollections linked to decisions |

---

## Slide 4: Strategy - Reusing OSDU Schema Fields as Relationship Primitives

**The OSDU Work-Product-Component schemas already contain underutilised fields that support typed linking.**

No new `kind` definitions needed. Conventions on existing fields.

| Pattern | OSDU Field | Used How |
|---|---|---|
| **Named relationships** | `Parameters[].Keys[ParameterKey="relationship"]` | Edge type: `evidencedBy`, `supersedes`, `constrainedBy`, `mitigates`, `alternativeTo`, `informedBy`, `selects`, `produces` |
| **Audit trail** | `CollaborationProject.LifecycleEvents[]` | Timestamped events: approvals, escalations, revisions |
| **Gate checklist** | `ActivityStates[]` with prefixed `MilestoneID` | Required deliverables per gate with completion status |
| **Actions as verbs** | `Activity` + `ActivityTemplate` | Each user action = one Activity record with typed Parameters |
| **Typed annotations** | `Remarks[]` with `RemarkSource` | Categorised notes: Recommendation, Condition, Risk, Audit |
| **Evidence packages** | `PersistedCollection` → `Parameters[]` | Frozen artifact sets linked to decisions |

The key insight: `Keys[ParameterKey="relationship"]` turns every `Parameters[]` entry into a **typed, directed edge** — a lightweight knowledge graph encoded within a document store. Edge labels are defined from the source record's perspective (e.g., a BD is `evidencedBy` its volumes, `constrainedBy` its risks). This is not a graph database (no native traversal, no path queries), but it provides sufficient structure for application-layer graph rendering and relationship-aware search.

---

## Slide 5: Drogon Example - DG1 → DG2 Decision Lifecycle

### The Story

Drogon field, Valysar formation. DG1 (Identify & Assess) approved Feb 2026.
Between gates: porosity downgrade (0.18→0.14), new risks added, 4D seismic confirms fault communication.
DG2 (Concept Select) approved May 2026 - full 7-segment subsea tieback.

### Relationship Graph (selected edges)

```
BusinessDecision: Drogon DG2 - Concept Select
│
├── supersedes    → BD: Drogon DG1 (prior gate)
│
├── evidencedBy   → REV-Statistics (P50 STOIIP 287 MSm³)
├── evidencedBy   → ETPDataspace (geomodel via RDDMS)
├── evidencedBy   → PersistedCollection (evidence package)
│
├── informedBy    → ProductionForecast (20-year, 7P/3I)
├── selects       → DevelopmentConcept: Full 7-segment (APPROVED)
├── alternativeTo → DevelopmentConcept: Reduced scope (REJECTED)
│
├── constrainedBy → Risk: Porosity & Cementation (ESCALATED)
├── mitigates     → Risk: Fault Compartment (4D confirms: High→Low)
```

Edge labels read from the BD's perspective: "this decision is *evidencedBy* the volumes", "this decision is *constrainedBy* the risk". Direction matches storage (`Parameters[]` on the BD record point to targets).

### Key Numbers (Drogon Demo)

| Metric | DG1 | DG2 |
|---|---|---|
| P50 STOIIP (MSm³) | 312 | 287 (−8%) |
| Risks | 2 | 4 (+2 new) |
| Relationship edges | 5 | 13 |
| Gate checklist items | — | 9 (8✓ + 1 outstanding) |

---

## Slide 6: Demo & Architecture

### ORES Rendering of Drogon DG2

**Screenshot slides**: Gate readiness panel (progress bar + checklist), relationship graph (Mermaid), risk evolution, volume comparison.

### Architecture

```
┌─────────────────────────────────────────────┐
│  OSDU Storage + Search (ADME)            │
│    BD, CP, Activity, Risk, REV, RDDMS    │
├─────────────────────────────────────────────┤
│  ORES (Python FastAPI)                    │
│    Enrichment → follows edges, builds graph│
├─────────────────────────────────────────────┤
│  Frontend (Chart.js + Mermaid)             │
│    Gate panel, graph, timeline, analytics │
└─────────────────────────────────────────────┘
```

Verified on 2 OSDU instances (eqndev + interop).

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

## Slide 8: OSDU Data Model & Services Assessment

### What OSDU Provides

| Capability | OSDU Service | Assessment |
|---|---|---|
| **Record storage** | Storage API | Document store with JSON schema validation. Adequate for relationship encoding via `Parameters[]`. |
| **Keyword search** | Search API | Full-text + field-level queries. Supports searching by `DataObjectParameter` value (forward-link lookup) and `Keys[]` values. |
| **Schema flexibility** | Schema API | `Parameters[]` and `Keys[]` accept arbitrary key-value pairs — sufficient for typed edge encoding without schema changes. |
| **Versioning** | Storage API | Per-record versioning with `modifyTime`. Relationships versioned with parent record. |
| **Access control** | Entitlements | Per-record ACL. No relationship-aware access control (edge visibility independent of node visibility). |
| **Notifications** | Notification API | Record-level change events. Could trigger downstream re-enrichment on relationship changes. |

### What OSDU Lacks — Critical Gaps

| Gap | Impact | Current Workaround |
|---|---|---|
| **No graph traversal API** | Every edge follow = 1 REST call. N-hop traversal = N sequential calls. No transitive closure, no shortest path, no subgraph queries. | Application-layer enrichment (ORES `bd_enrichment.py` performs 7 parallel fetch tasks). |
| **No reverse-link index** | "What records link TO this record?" requires full-scan search, not indexed lookup. | Search by `DataObjectParameter` value — works but O(n) over catalog. |
| **No referential integrity** | Deleting a target record leaves dangling edges. No cascade, no constraint enforcement. | Application-level validation on ingest. |
| **No spatial query operators** | Records have `SpatialArea`/`SpatialPoint` but Search API has no `ST_Within`, no spatial join, no proximity queries. | External spatial index or client-side filtering. |
| **No temporal query model** | `createTime`/`modifyTime` are system timestamps only. No bi-temporal model, no "as-of" queries, no time-range search on `LifecycleEvents[]`. | Application-level time filtering on fetched records. |
| **No workflow/process engine** | No state machine, no task routing, no approval workflows. Gate process tracking is purely data (ActivityStates[]), not orchestrated. | ORES addgate UI + manual state management. |
| **No aggregation in Search** | COUNT only. No GROUP BY, SUM, AVG. Cross-gate statistics require client-side computation. | ORES backend computes all analytics post-fetch. |
| **Record size limit** | 1 MB per record. Limits relationship density (~200-300 Parameters[] entries max). | Split across multiple records for very large evidence sets. |

### Classification: Where Does OSDU Sit?

In information science terms:

| System Type | Characteristics | OSDU? |
|---|---|---|
| **Formal ontology** (OWL/RDF) | Class hierarchies, axioms, logical inference, reasoning | No — no inference engine, no axioms |
| **Knowledge graph** (Neo4j, Stardog) | Native graph storage, traversal queries, path algorithms | No — document store, no native adjacency |
| **Linked data** (JSON-LD, RDF) | Typed URIs as edges, dereferenceable identifiers, standard vocabularies | Partial — `DataObjectParameter` is a typed URI reference, but no standard vocabulary, no content negotiation |
| **Document store with conventions** | Schema-flexible records, application-defined linking patterns | **Yes** — this is what OSDU is |

OSDU is a **schema-validated document store** with sufficient flexibility to encode typed relationships. The "knowledge graph" emerges at the **application layer** (ORES enrichment + rendering), not from the platform itself.

---

## Slide 9: Beyond Governance — Analysis and Decision Science

| Capability | What It Enables | OSDU + ORES Implementation |
|---|---|---|
| **Cross-gate volume tracking** | Calibrate estimation bias across an asset portfolio | Search BD per reservoir → compare P10/P50/P90 across DG1→FID |
| **Risk evolution analysis** | Identify systematic risk patterns (which risks escalate vs. resolve?) | Risk records linked per gate; severity/probability deltas computed |
| **Sensitivity attribution** | Which parameter change drove the volume revision? | Activity records with typed cause→effect links |
| **Alternative evaluation** | Structured comparison of development concepts with evidence | `alternativeTo` edges + ranked Remarks[] |
| **Portfolio-level queries** | "Show all DG2 decisions with NPV > 300 MUSD and outstanding risks" | OSDU Search on kind + nested field queries |
| **AI/ML readiness** | Structured, typed, queryable decision data as training corpus | Consistent schema → direct feature extraction |

The transition from **governance** ("was the process followed?") to **decision science** ("was the decision good?") requires exactly this: typed, queryable evidence chains across gates.

### Further Domain Applications

| Use Case | Relationship Pattern | OSDU Implementation |
|---|---|---|
| **FMU ensemble tracking** | Actions (batch runs) | Activity records per realisation, linked via ActivityTemplate |
| **Well decision tree** | Alternatives + constraints | Parameters[alternativeTo] between WellPlan BDs |
| **CCS monitoring lifecycle** | Audit trail + risk evolution | LifecycleEvents[] on CP; Risk records linked per injection period |
| **IOR screening** | Evidence chain + comparison | PersistedCollections per IOR method; side-by-side analysis |
| **Asset handover** | Provenance + completeness | PersistedCollection completeness vs. ActivityStates[] checklist |

All implementable with the same schema field patterns — only reference-data definitions vary.

---

## Slide 10: Status & Outlook

### What Exists Today
- OSDU schemas with all required fields for typed linking (Parameters[], Keys[], LifecycleEvents[], ActivityStates[])
- ORES application with enrichment, graph rendering, and ingestion (deployed on Radix)
- Verified on 2 OSDU instances (eqndev + interop)
- 6 relationship patterns demonstrated with Drogon DG1→DG2 data
- GUI panels operational: gate checklist, relationship graph, timeline, typed remarks
- Generic generators for repeatable record creation (`demo/scripts/generators/gen_ontology.py`)

### What's Needed — Requirements

1. **Conventions** — Agreement on edge-type vocabulary (`ParameterKey` values)
2. **Reference data** — MilestoneID entries per gate type
3. **Application logic** — Enrichment code to follow links and render graphs (OSDU itself cannot do this)
4. **Culture** — Teams populate Parameters[] and LifecycleEvents[] consistently

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

### OSDU Community / Platform Actions Needed
1. **Standardise edge-type vocabulary** as reference-data entries (6 types proposed)
2. **Add reverse-link search support** — index `DataObjectParameter` targets for efficient "what links to X?" queries
3. **Document LifecycleEvents[] usage** in CollaborationProject best practices
4. **Consider graph traversal API** — even 2-hop traversal would eliminate most application-layer workarounds
5. **Spatial query operators** — `ST_Within`, proximity search on SpatialArea fields
6. **Temporal range queries** — search within LifecycleEvents[] date ranges

---

## Slide 11: Key Takeaway

> **OSDU's schema model is flexible enough to encode typed decision-evidence relationships.**
> The platform provides the storage and search foundation.
> The knowledge graph — traversal, rendering, analysis — is built at the application layer.

Nine relationship types. One key convention (`ParameterKey="relationship"`).
Full decision lifecycle coverage from DG1 through FID.

**What OSDU is:** A schema-validated document store with sufficient flexibility for relationship encoding.
**What the application adds:** Graph traversal, enrichment, visualisation, cross-gate analytics.
**What the platform needs next:** Reverse-link indexing, graph traversal API, spatial/temporal query operators.

---

## Appendix A: Relationship Type Vocabulary

All edges are stored as `Parameters[]` on the source record. Labels are defined from the source record's perspective.

| Edge Type | Semantics (source → target) | Example |
|---|---|---|
| `evidencedBy` | Source is supported/proved by target | BD ← REV-Statistics (volumes support the decision) |
| `supersedes` | Source replaces target | BD DG2 → BD DG1 (new gate replaces prior) |
| `constrainedBy` | Source is limited/bounded by target | BD ← Porosity Risk (risk constrains the decision) |
| `mitigates` | Source's evidence reduces impact of target | BD → Fault Risk (4D seismic mitigates compartment risk) |
| `alternativeTo` | Source is a variant of target | DevConcept Reduced ↔ DevConcept Full (symmetric) |
| `informedBy` | Source is informed by target (input) | BD ← ProductionForecast (forecast is input to decision) |
| `selects` | Source selects/approves target (output) | BD → DevelopmentConcept (decision approves this concept) |
| `produces` | Source produces target (Activity output) | Activity → REV (volume update produces new volumes) |
| `informs` | Source informs target (Activity → BD) | Activity → BD (action informs the decision) |

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
      {"ParameterKey": "relationship", "StringParameterKey": "evidencedBy"}
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
