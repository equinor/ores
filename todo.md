# TODO - Ontology-Driven Improvements

## Recently Completed (Aug 2026)

| Item | What was done |
|---|---|
| **Compound cell-level AND filter** | New `compoundFilter` input on GraphQL `deepSearch` — ANDs multiple property thresholds at cell level, returns intersection count/fraction via `compoundMatch`. Memory-efficient: loads one array at a time (~7 MB), ANDs into a bytearray mask. PG-only; degrades gracefully on REST backends with a warning. |
| **Field Development preset queries (6)** | `markers_by_horizon`, `field_bypassed_oil` (compound filter), `field_water_breakthrough` (3 sub-queries), `field_injection_support`, `field_completion_ntg` (3 sub-queries), `field_segment_ranking` (4 sub-queries). Each has a "HOW TO READ" comment explaining result interpretation. |
| **Easy Mode field dev buttons** | 5 one-click buttons in Keys UI Easy Mode: Markers, Bypassed Oil, Water Breakthrough, Completion Pay, Segment Overview. Run full GraphQL presets but stay in Easy Mode with rendered results. |
| **Easy Mode compound result rendering** | `renderCompoundResults()` displays multi-alias deepSearch results with explanation banner. `extractRenderableObjects()` scans all aliases in compound query responses for 3D visualization. |
| **Drogon catalog records (13)** | Ingested to eqndev + interop: IjkGrid, WellboreFrame, Trajectory, Fault, StructuralOrg, GridConnection, OrganizationFeature, WellboreMarkerFrame objects for the Drogon field. |
| **PG backend bug fixes** | Fixed `_apply_compound`: was querying `obj.guid` (doesn't exist) → corrected to `res.guid`. Fixed property source query to match `pg_batch_property_sources` pattern (rel.dst_id + typ filter). |

---

## Already Covered - Ontology Features in M27 OSDU + ORES Today

| Ontology Concept | OSDU/ORES Coverage | Status |
|---|---|---|
| **Object Types** (typed, schema-validated entities) | M27 kinds: BusinessDecision, Reservoir, Risk, Activity, CollaborationProject, DevelopmentConcept, REV, PersistedCollection, etc. | ✅ Full |
| **Properties & nested structures** | JSON schema validation, typed sub-objects (FacilityConcept, WellPlan, DrainageStrategy, ProjectSpecifications) | ✅ Full |
| **Semantic links between objects** | `Parameters[]` with role semantics (Input/Output/InputReference), `PriorActivityIDs`, `RiskIDs`, `DecisionLevelID` | ✅ Partial - works but implicit, not named edge types |
| **Provenance / lineage** | Activity + ActivityTemplate chain; Parameters[] link inputs→outputs; `_enrich_bd_activity()` resolves full chain | ✅ Full |
| **Reference-data catalogs** | DecisionLevel, ApprovalStatus, RiskCategory, RiskSeverity, RiskProbability, PropertyType, FacilityType, ArtificialLiftType | ✅ Full |
| **Search & discovery** | ORES search: full-text, kind-filtered, wildcard, ref-data discovery; federated across OSDU + RDDMS | ✅ Full |
| **Object detail & enrichment** | BD enrichment: volumes, GeoLabelSet, production, maps, activity, dev concept - auto-resolved on view | ✅ Full |
| **Decision gate lifecycle** | ActivityStateTemplate milestones (6 presets: FieldDev, CCS, Exploration, Decom, IOR); gate progression DG0→FID | ✅ Full |
| **Collections / evidence packages** | PersistedCollection (hierarchical, 99+ refs at DG2); domain bundles (subsurface, well, risk) | ✅ Full |
| **Cross-gate namespace** | CollaborationProject as persistent master-data across DG1→FID; SoE↔SoR bridge | ✅ Full |
| **Comparison / analytics** | `analyse.py`: cross-gate volume deltas, risk evolution, economics trends, property diffs | ✅ Full |
| **Record creation with auto-linking** | `addgate.py`: one-click BD + Risks + Collection + CP + Activity; presets per project type | ✅ Full |
| **Subsurface object graph** | RDDMS GraphQL: object_relations (forward/reverse), deep_search, federated_search across dataspaces; field dev presets with multi-query sub-graph exploration | ✅ Full |
| **Array/grid data access** | RDDMS: HDF5 arrays, statistics, sampling; Grid2d/IjkGrid property visualization; compound cell-level AND filter with `compoundFilter` | ✅ Full |
| **Workflow templates** | ActivityTemplate (7 presets: Simulation, FMU, Drilling, ProdTest, Interpretation, QC, Custom) | ✅ Full |
| **Branching / versioning** | RDDMS dataspace clone + ETP transactions (start/commit/rollback) | ✅ Infrastructure exists, not yet surfaced as "alternatives" |
| **Actions (verbs on objects)** | Activity + ActivityTemplate already model actions; each action run = Activity record with typed Parameters[] | ✅ Schema exists - surface in UI as named verbs |
| **Named relationship types** | `Parameters[].Keys[ParameterKey]` already supports arbitrary tags - use as relationship-type label (e.g. `relationship-kind`=`evidences`) | ✅ Schema exists - define conventions + ref-data values |
| **Object change history / audit** | `CollaborationProject.LifecycleEvents[]` has EventID, DateTime, Remark, ResourceCollectionID - **heavily underutilized** | ✅ Schema exists - populate on each state change |
| **Decision alternatives** | `ext.equinor.Alternatives[]` on BD already holds Name, Rank, Rationale, RecommendedAction | ✅ Schema exists - already in Drogon demo |
| **Gate checklist / required items** | `ActivityStates[]` with custom MilestoneID + ActivityStatusID ref-data; or derive from ActivityStateTemplate | ✅ Schema exists - define ref-data items per gate |
| **Structured annotations** | `Remarks[]` with RemarkSource categorization - use as typed notes/comments | ✅ Schema exists - convention only |



| **Live collaboration (real-time)** | No push notifications; polling only; no SSE/websocket feeds | ⚠️ Gap (infrastructure) |
| **User-configurable dashboards** | Fixed templates per view; users cannot compose custom KPI layouts | ⚠️ Gap (UI framework) |
| **Ontology-level access control** | OSDU ACL per record; no object-type or relationship-scoped permissions | ⚠️ Gap (OSDU platform limitation) |

**Summary**: ~18/21 core ontology concepts are covered by existing M27 schema fields. Many "gaps" are actually underutilized fields that just need conventions and reference-data values. Only 3 true gaps remain: real-time push, configurable dashboards, and ontology-level ACL.

---

## Existing M27 Fields to Exploit (no schema changes needed)

| Field | Location | Current Use | Ontology Reuse |
|---|---|---|---|
| `Parameters[].Keys[ParameterKey]` | BD, Activity | artifact typing (`REV-raw`, `GeoLabelSet`) | **Relationship types**: set ParameterKey=`relationship-kind`, value=`evidences`/`supersedes`/`constrains` |
| `ProjectSpecifications[]` | BD | Economics (NPV, IRR, CAPEX) | **Any quantified metric** - define new ParameterTypeID ref-data |
| `ActivityStates[]` | BD, CP | Gate progression (DG1→DG4) | **Any lifecycle checklist** - custom MilestoneID + ActivityStatusID per gate |
| `LifecycleEvents[]` | CollaborationProject | Minimal (creation only) | **Full audit trail** - EventID for state transitions, revisions, approvals |
| `Remarks[]` | BD | Recommendations text | **Typed annotations** - RemarkSource as category key |
| `ext.equinor.Alternatives[]` | BD | DG scenario ranking | **Decision alternatives** - already structured (Name, Rank, Rationale, Action). ⚠️ Custom extension (`data.ext.equinor`), not OSDU standard - portable via `ext` mechanism but needs agreement for cross-operator use |
| `Activity` records | Standalone | Workflow provenance | **Actions as first-class verbs** - each user action = Activity with template |
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

## Tier A - Demo-ready with current M27 schemas

No new schemas or APIs. Uses existing BD, Parameters[], Activity, PersistedCollection, CollaborationProject, search, enrichment, analyse.

### A1. Gate Completeness Progress Bar ✅
- [x] `_enrich_bd_collaboration()` extracts ActivityStates[] checklist with MilestoneID + completion status
- [x] Progress bar + checklist grid in `bd_ontology_panels.html` (included from search_bd.html)
- [x] CSS in `search_styles.html` (`.bd-checklist-bar`, `.bd-cl-*`)

### A2. Visual Provenance DAG ✅
- [x] Pure HTML/CSS flowchart: Inputs → Activity → Outputs
- [x] Renders Activity parameters grouped by ParameterRoleID (Input/Output/Workflow)
- [x] Clickable links navigate to source OSDU records; param_labels resolved
- [x] Collapsible `<details>` in BD card, shows input/output counts in summary

### A3. Decision Alternative Comparison View ✅
- [x] Inline comparison table in BD card when >1 alternative exists (rank, name, action, economics, rationale)
- [x] "Open full comparison in Analyse →" link to cross-gate analysis
- [x] Full alternative comparison already in `analyse.html` (`buildAlternativesSection` + bar charts)

### A4. Object Relationship Graph Explorer ✅
- [x] Groups forward + reverse OSDU links by role (parent, child, reference, etc.)
- [x] Clickable nodes navigate to record detail; kind labels shown
- [x] RDDMS dataspace refs shown as separate group with link to Keys browser
- [x] Central self-node + grouped satellite layout in `bd_ontology_panels.html`

### A5. Cross-Gate Risk Evolution Timeline ✅
- [x] Risk evolution table + Chart.js bar chart in `analyse.html` (`buildRiskSection` + `chartRiskEvo`)
- [x] Shows open/mitigated/total per gate with severity change chips (↑/↓/✓)
- [x] Stacked bar + line chart with per-gate risk counts

### A6. CollaborationProject Activity Feed ✅
- [x] `_enrich_bd_collaboration()` extracts LifecycleEvents[] from CP
- [x] Vertical timeline in `bd_ontology_panels.html` with colored dots per event type
- [x] Event types: CreationEvent, EvidenceAdded, RiskEscalation, RiskMitigation, VolumeUpdate, StateTransition, ApprovalGranted

---

## Tier B - Needs ORES/RDDMS backend additions (M27 schemas still sufficient)

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
- [x] Compound cell-level AND filter (`compoundFilter`) — done for RDDMS property arrays
- [ ] Extend to OSDU side: "BD where Parameters[role=Output, kind=REV].P50 > X"
- [ ] Requires post-search enrichment filtering (OSDU search can't query nested arrays)
- [ ] Server-side: fetch candidates by kind → enrich → filter → return
- **Deps**: Existing enrichment pipeline. RDDMS compound filter is the pattern to follow.
- **Effort**: ~3 days for OSDU side. RDDMS side done.

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
- [ ] Lightweight - no webhook infrastructure needed, just timestamp comparison
- **Deps**: B1 (object listing with timestamps)
- **Effort**: ~2 days atop B1

---

## Tier C - True infrastructure gaps (cannot solve with existing schemas)

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

### ~~C3-C5. Previously proposed new schemas - NOW UNNECESSARY~~

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
