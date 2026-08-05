# TODO — Ontology-Driven Improvements

## Already Covered — Ontology Features in M27 OSDU + ORES Today

| Ontology Concept | OSDU/ORES Coverage | Status |
|---|---|---|
| **Object Types** (typed, schema-validated entities) | M27 kinds: BusinessDecision, Reservoir, Risk, Activity, CollaborationProject, DevelopmentConcept, REV, PersistedCollection, etc. | ✅ Full |
| **Properties & nested structures** | JSON schema validation, typed sub-objects (FacilityConcept, WellPlan, DrainageStrategy, ProjectSpecifications) | ✅ Full |
| **Semantic links between objects** | `Parameters[]` with role semantics (Input/Output/InputReference), `PriorActivityIDs`, `RiskIDs`, `DecisionLevelID` | ✅ Partial — works but implicit, not named edge types |
| **Provenance / lineage** | Activity + ActivityTemplate chain; Parameters[] link inputs→outputs; `_enrich_bd_activity()` resolves full chain | ✅ Full |
| **Reference-data catalogs** | DecisionLevel, ApprovalStatus, RiskCategory, RiskSeverity, RiskProbability, PropertyType, FacilityType, ArtificialLiftType | ✅ Full |
| **Search & discovery** | ORES search: full-text, kind-filtered, wildcard, ref-data discovery; federated across OSDU + RDDMS | ✅ Full |
| **Object detail & enrichment** | BD enrichment: volumes, GeoLabelSet, production, maps, activity, dev concept — auto-resolved on view | ✅ Full |
| **Decision gate lifecycle** | ActivityStateTemplate milestones (6 presets: FieldDev, CCS, Exploration, Decom, IOR); gate progression DG0→FID | ✅ Full |
| **Collections / evidence packages** | PersistedCollection (hierarchical, 99+ refs at DG2); domain bundles (subsurface, well, risk) | ✅ Full |
| **Cross-gate namespace** | CollaborationProject as persistent master-data across DG1→FID; SoE↔SoR bridge | ✅ Full |
| **Comparison / analytics** | `analyse.py`: cross-gate volume deltas, risk evolution, economics trends, property diffs | ✅ Full |
| **Record creation with auto-linking** | `addgate.py`: one-click BD + Risks + Collection + CP + Activity; presets per project type | ✅ Full |
| **Subsurface object graph** | RDDMS GraphQL: object_relations (forward/reverse), deep_search, federated_search across dataspaces | ✅ Full |
| **Array/grid data access** | RDDMS: HDF5 arrays, statistics, sampling; Grid2d/IjkGrid property visualization | ✅ Full |
| **Workflow templates** | ActivityTemplate (7 presets: Simulation, FMU, Drilling, ProdTest, Interpretation, QC, Custom) | ✅ Full |
| **Branching / versioning** | RDDMS dataspace clone + ETP transactions (start/commit/rollback) | ✅ Infrastructure exists, not yet surfaced as "alternatives" |
| **Actions (verbs on objects)** | Implicit in code (enrich, freeze, compare) — not yet exposed as typed ontology actions | ⚠️ Gap |
| **Named relationship types** | Parameters[] roles exist but links are unnamed edges; no `informsDecision` / `supersedes` vocabulary | ⚠️ Gap |
| **Object change history / audit** | OSDU legal tags + version increment; no fine-grained event log per collaboration | ⚠️ Gap |
| **Live collaboration (real-time)** | No push notifications; polling only; no SSE/websocket feeds | ⚠️ Gap |
| **User-configurable dashboards** | Fixed templates per view; users cannot compose custom KPI layouts | ⚠️ Gap |
| **Ontology-level access control** | OSDU ACL per record; no object-type or relationship-scoped permissions | ⚠️ Gap (OSDU platform limitation) |

**Summary**: ~15/21 core ontology concepts are already operational. The gaps cluster around explicit relationship naming, first-class actions, change audit, and real-time collaboration — which map to Tiers B and C below.

---

Items ranked by implementation complexity. Tiers:
- **A** = Implementable now in ORES demo with M27 schemas (no new kinds, no new APIs)
- **B** = Needs minor ORES backend work or RDDMS endpoint additions (existing schemas)
- **C** = Requires new OSDU schema extensions or significant new services

---

## Tier A — Demo-ready with current M27 schemas

No new schemas or APIs. Uses existing BD, Parameters[], Activity, PersistedCollection, CollaborationProject, search, enrichment, analyse.

### A1. Gate Completeness Progress Bar
- [ ] Define per-DecisionLevel checklist as a JSON config in ORES (not a schema change — just app logic)
- [ ] Compare BD's Parameters[] roles against the checklist → "7/9 items linked"
- [ ] Show progress bar in search result cards and BD detail view
- **Deps**: None. Uses existing `bd_enrichment` + `addgate` preset definitions
- **Effort**: ~1 day. Config + UI template update

### A2. Visual Provenance DAG
- [ ] Render Activity → inputs/outputs as a directed graph (D3/Mermaid in template)
- [ ] `_enrich_bd_activity()` already resolves Activity + ActivityTemplate + parameter labels
- [ ] Add a "Provenance" tab on BD detail view showing the DAG
- **Deps**: None. Data already fetched in enrichment
- **Effort**: ~1 day. Frontend rendering only

### A3. Decision Alternative Comparison View
- [ ] `analyse.py` already compares gates for same Reservoir — extend to compare two BDs at same gate level (alternatives)
- [ ] Side-by-side: volumes, risks, economics, development concept diffs
- [ ] UI: pick two BDs → show delta table (reuse existing metric delta logic)
- **Deps**: A working analyse.py (already exists)
- **Effort**: ~2 days. Minor backend extension + new template section

### A4. Object Relationship Graph Explorer
- [ ] From any record, show forward links (Parameters[], explicit IDs) and reverse links (OSDU reverse lookup)
- [ ] Render as interactive node graph (D3 force layout or similar)
- [ ] Clicking a node navigates to that record's detail view
- **Deps**: Existing search enrichment already resolves forward + reverse links
- **Effort**: ~2-3 days. New template + recursive link resolution (depth-limited)

### A5. Cross-Gate Risk Evolution Timeline
- [ ] `analyse.py` already tracks risk added/removed/escalated per gate
- [ ] Render as a timeline/swimlane view: risk lifecycle across DG1→DG2→DG3
- [ ] Highlight escalations, new risks, mitigated items
- **Deps**: analyse.py risk diff logic
- **Effort**: ~1-2 days. Visualization only

### A6. CollaborationProject Activity Feed (simulated)
- [ ] Query Activities linked to CP (via PriorActivityIDs or Parameters[])
- [ ] Show chronological feed: "DG1 created", "Volume estimate updated (Activity X)", "Risk R3 added"
- [ ] Derive from existing Activity records + BD creation timestamps
- **Deps**: None — interprets existing records as events
- **Effort**: ~2 days. Query logic + feed UI

---

## Tier B — Needs ORES/RDDMS backend additions (M27 schemas still sufficient)

### B1. RDDMS Graph Traversal Endpoint
- [ ] New endpoint: given a BD SRN, walk Parameters[] → resolve ETPDataspace links → list RESQML objects in those dataspaces
- [ ] Returns unified graph: OSDU records + RESQML objects across the boundary
- [ ] ORES consumes this for the object explorer (A4) to include subsurface detail
- **Deps**: A4 benefits from this but works without it (OSDU-only graph)
- **Effort**: ~3-4 days RDDMS TypeScript endpoint + ORES integration

### B2. Dataspace Diff/Compare
- [ ] RDDMS endpoint: given two dataspaces (or two transaction snapshots), return structural diff
- [ ] Objects added/removed/modified, property changes, grid dimension changes
- [ ] ORES UI: show diff when comparing two BD alternatives that reference different dataspaces
- **Deps**: B1 (needs object listing per dataspace). A3 benefits from this
- **Effort**: ~4-5 days. RDDMS comparison logic + diff rendering

### B3. Relationship-Aware Search
- [ ] Extend search_router to support compound queries: "BD where Parameters[role=Output, kind=REV].P50 > X"
- [ ] Requires post-search enrichment filtering (OSDU search can't query nested arrays)
- [ ] Server-side: fetch candidates by kind → enrich → filter → return
- **Deps**: Existing enrichment pipeline
- **Effort**: ~3 days. Query parser + filter logic

### B4. Decision Branches via Dataspace Clone
- [ ] ORES UI: "Create Alternative" button on BD → clones linked RDDMS dataspace → creates new BD with cloned dataspace reference
- [ ] Names branch: "Alternative A - Water Injection" / "Alternative B - Gas Injection"
- [ ] Uses existing RDDMS Clone Dataspace API
- **Deps**: RDDMS clone endpoint exists. Needs ORES orchestration
- **Effort**: ~2-3 days. Orchestration + UI

### B5. Atomic Collaboration Actions
- [ ] ORES endpoints: POST `/bd/{id}/add-alternative`, `/bd/{id}/update-volume`, `/bd/{id}/flag-risk`
- [ ] Each action: updates BD Parameters[] or linked records + creates an Activity record as audit trail
- [ ] Feed into A6 (activity feed) automatically
- **Deps**: A6 design. Existing addgate logic for record creation
- **Effort**: ~4-5 days. Multiple endpoints + Activity auto-creation

### B6. RDDMS Change Notification (Polling)
- [ ] RDDMS periodic check: compare dataspace object list/timestamps vs last known state
- [ ] ORES: on BD detail view, show "2 objects modified since last gate freeze"
- [ ] Lightweight — no webhook infrastructure needed, just timestamp comparison
- **Deps**: B1 (object listing with timestamps)
- **Effort**: ~2 days atop B1

---

## Tier C — Requires new OSDU schema extensions or significant new infrastructure

### C1. `DecisionAlternative` WPC Schema
- [ ] New kind: `work-product-component--DecisionAlternative:1.0.0`
- [ ] Fields: AlternativeName, AlternativeDescription, RankedPosition, SelectionRationale, LinkedDataspaceID
- [ ] BD links to alternatives via Parameters[role=Output, kind=DecisionAlternative]
- [ ] Enables native comparison queries without convention-dependent parsing
- **Deps**: OSDU schema registration. A3/B4 work without this but benefit from it
- **Effort**: ~1 week (schema design + registration + migration of existing demo data)

### C2. `RelationshipType` Reference-Data Kind
- [ ] New kind: `reference-data--RelationshipType:1.0.0`
- [ ] Values: `informsDecision`, `evidences`, `supersedes`, `alternativeTo`, `constrains`, `mitigates`
- [ ] Used in Parameters[].Keys[] or a new `RelationshipTypeID` field on links
- [ ] Makes the implicit link semantics explicit and queryable
- **Deps**: Schema registration. Changes how Parameters[] conventions work
- **Effort**: ~1 week (schema + convention documentation + demo data update)

### C3. `GateChecklist` Extension to DecisionLevel
- [ ] Extend `DecisionLevel` ref-data with `RequiredItems[]`: array of {Kind, Role, MinCount, Description}
- [ ] Or: new WPC `GateChecklist` linked from DecisionLevel
- [ ] Enables A1 to be schema-driven rather than app-config-driven
- **Deps**: A1 works without this (uses app config). This makes it portable/standard
- **Effort**: ~3-4 days (schema extension + ref-data update)

### C4. `ChangeEvent` Audit Records
- [ ] New kind: `work-product-component--ChangeEvent:1.0.0` or use Activity with a new template
- [ ] Fields: EventType, Actor, Timestamp, AffectedRecordIDs[], Description, PriorValue, NewValue
- [ ] Linked from CollaborationProject → provides true object history
- **Deps**: B5 can simulate this with Activity records. This formalizes it
- **Effort**: ~1 week (schema + ingestion pipeline + UI)

### C5. Real-Time Collaboration (Webhooks/SSE)
- [ ] RDDMS webhook: push notification when ETP dataspace objects change
- [ ] ORES Server-Sent Events: live updates to open BD detail views
- [ ] Requires infrastructure: message bus or polling service + SSE endpoint
- **Deps**: B6 is the lightweight precursor
- **Effort**: ~2 weeks (infrastructure + RDDMS webhook + ORES SSE + reconnection logic)

---

## Recommended Implementation Order

```
A1 (completeness bar)        ─┐
A2 (provenance DAG)          ─┤── Sprint 1: quick wins, pure frontend
A5 (risk timeline)           ─┘

A3 (alternative comparison)  ─┐
A4 (graph explorer)          ─┤── Sprint 2: navigation & comparison
A6 (activity feed)           ─┘

B4 (decision branches)       ─┐
B3 (relationship search)     ─┤── Sprint 3: backend enrichment
B5 (atomic actions)          ─┘

B1 (RDDMS graph traversal)  ─┐
B2 (dataspace diff)          ─┤── Sprint 4: cross-boundary integration
B6 (change notification)     ─┘

C1–C5                        ─── Sprint 5+: schema proposals (submit to OSDU forum)
```
