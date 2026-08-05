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
| **Actions (verbs on objects)** | Activity + ActivityTemplate already model actions; each action run = Activity record with typed Parameters[] | ✅ Schema exists — surface in UI as named verbs |
| **Named relationship types** | `Parameters[].Keys[ParameterKey]` already supports arbitrary tags — use as relationship-type label (e.g. `relationship-kind`=`evidences`) | ✅ Schema exists — define conventions + ref-data values |
| **Object change history / audit** | `CollaborationProject.LifecycleEvents[]` has EventID, DateTime, Remark, ResourceCollectionID — **heavily underutilized** | ✅ Schema exists — populate on each state change |
| **Decision alternatives** | `ext.equinor.Alternatives[]` on BD already holds Name, Rank, Rationale, RecommendedAction | ✅ Schema exists — already in Drogon demo |
| **Gate checklist / required items** | `ActivityStates[]` with custom MilestoneID + ActivityStatusID ref-data; or derive from ActivityStateTemplate | ✅ Schema exists — define ref-data items per gate |
| **Structured annotations** | `Remarks[]` with RemarkSource categorization — use as typed notes/comments | ✅ Schema exists — convention only |
| **Live collaboration (real-time)** | No push notifications; polling only; no SSE/websocket feeds | ⚠️ Gap (infrastructure) |
| **User-configurable dashboards** | Fixed templates per view; users cannot compose custom KPI layouts | ⚠️ Gap (UI framework) |
| **Ontology-level access control** | OSDU ACL per record; no object-type or relationship-scoped permissions | ⚠️ Gap (OSDU platform limitation) |

**Summary**: ~18/21 core ontology concepts are covered by existing M27 schema fields. Many "gaps" are actually underutilized fields that just need conventions and reference-data values. Only 3 true gaps remain: real-time push, configurable dashboards, and ontology-level ACL.

---

## Existing M27 Fields to Exploit (no schema changes needed)

| Field | Location | Current Use | Ontology Reuse |
|---|---|---|---|
| `Parameters[].Keys[ParameterKey]` | BD, Activity | artifact typing (`REV-raw`, `GeoLabelSet`) | **Relationship types**: set ParameterKey=`relationship-kind`, value=`evidences`/`supersedes`/`constrains` |
| `ProjectSpecifications[]` | BD | Economics (NPV, IRR, CAPEX) | **Any quantified metric** — define new ParameterTypeID ref-data |
| `ActivityStates[]` | BD, CP | Gate progression (DG1→DG4) | **Any lifecycle checklist** — custom MilestoneID + ActivityStatusID per gate |
| `LifecycleEvents[]` | CollaborationProject | Minimal (creation only) | **Full audit trail** — EventID for state transitions, revisions, approvals |
| `Remarks[]` | BD | Recommendations text | **Typed annotations** — RemarkSource as category key |
| `ext.equinor.Alternatives[]` | BD | DG scenario ranking | **Decision alternatives** — already structured (Name, Rank, Rationale, Action). ⚠️ Custom extension (`data.ext.equinor`), not OSDU standard — portable via `ext` mechanism but needs agreement for cross-operator use |
| `Activity` records | Standalone | Workflow provenance | **Actions as first-class verbs** — each user action = Activity with template |
| `Parameters[].Selection` | BD, Activity | Sparse | **Context/explanation** per linked object |

**Reference-data items to define** (zero schema changes, just new ref-data records):
- `ParameterKey` conventions: `relationship-kind`, `gate-requirement`, `completeness-role`
- `ParameterTypeID` additions: custom KPIs beyond economics
- `MilestoneID` additions: per-gate required items (e.g. `DG2-Volumes`, `DG2-DevConcept`)
- `ActivityStatusID` additions: `Satisfied`, `Outstanding`, `Waived`
- `EventID` conventions: `StateTransition`, `EvidenceAdded`, `RiskEscalation`, `ApprovalGranted`

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

### B5. Atomic Collaboration Actions (using existing audit fields)
- [ ] ORES endpoints: POST `/bd/{id}/add-alternative`, `/bd/{id}/update-volume`, `/bd/{id}/flag-risk`
- [ ] Each action: updates BD Parameters[] or linked records + appends `LifecycleEvents[]` entry on CP
- [ ] Also creates Activity record (with ActivityTemplate="CollaborationAction") for full provenance
- [ ] Use `ext.equinor.Alternatives[]` for alternative management (already structured)
- [ ] Feed into A6 (activity feed) automatically via LifecycleEvents[] + Activity queries
- **Deps**: A6 design. Existing addgate logic for record creation
- **Effort**: ~4-5 days. Multiple endpoints + dual audit (LifecycleEvents + Activity)

### B6. RDDMS Change Notification (Polling)
- [ ] RDDMS periodic check: compare dataspace object list/timestamps vs last known state
- [ ] ORES: on BD detail view, show "2 objects modified since last gate freeze"
- [ ] Lightweight — no webhook infrastructure needed, just timestamp comparison
- **Deps**: B1 (object listing with timestamps)
- **Effort**: ~2 days atop B1

---

## Tier C — True infrastructure gaps (cannot solve with existing schemas)

### C1. Real-Time Collaboration (Webhooks/SSE)
- [ ] RDDMS webhook: push notification when ETP dataspace objects change
- [ ] ORES Server-Sent Events: live updates to open BD detail views
- [ ] Requires infrastructure: message bus or polling service + SSE endpoint
- **Deps**: B6 is the lightweight precursor
- **Effort**: ~2 weeks (infrastructure + RDDMS webhook + ORES SSE + reconnection logic)

### C2. User-Configurable Dashboard Builder
- [ ] Domain users compose custom BD views: pick which Parameters[] to surface, KPI cards, graph layouts
- [ ] Requires a layout persistence model + dynamic rendering engine
- [ ] Consider: saved views as JSON in user preferences or as OSDU Document WPC
- **Deps**: A1-A6 provide the building blocks; this makes them composable
- **Effort**: ~2 weeks (layout engine + persistence + UI)

### ~~C3-C5. Previously proposed new schemas — NOW UNNECESSARY~~

**Eliminated by reusing existing M27 fields:**

| Was | Replaced By |
|---|---|
| ~~`DecisionAlternative` WPC~~ | `ext.equinor.Alternatives[]` already on BD + B4 dataspace branching |
| ~~`RelationshipType` ref-data kind~~ | `Parameters[].Keys[ParameterKey="relationship-kind"]` + conventions |
| ~~`GateChecklist` schema extension~~ | `ActivityStates[]` with custom MilestoneID/ActivityStatusID ref-data |
| ~~`ChangeEvent` WPC~~ | `CollaborationProject.LifecycleEvents[]` + Activity records as audit trail |

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
B5 (atomic actions + audit)  ─┘   (uses LifecycleEvents[] + Activity)

B1 (RDDMS graph traversal)  ─┐
B2 (dataspace diff)          ─┤── Sprint 4: cross-boundary integration
B6 (change notification)     ─┘

C1-C2 (SSE + dashboards)    ─── Sprint 5+: infrastructure (no new OSDU schemas needed)

Ref-data setup (run once):   ─── Sprint 0: define conventions for Keys[], MilestoneID, EventID
```
