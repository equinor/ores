# Well Planning Committee (WPC) Ontology — Omega Sør Demo

**Internal reference — ORES Team**

---

## Overview

This document describes how the OSDU M27 ontology patterns (typed relationships, gate checklists, lifecycle events, evidence chains) are applied to a **Well Planning Committee (WPC) decision** for the Omega Sør Alfa development.

All data sourced from the real SSVP presentation (`20260615_OmegaSør_SSVP.pptx`).

---

## Record Graph Summary

```
BusinessDecision: Omega Sør – WPC Decision
│
├── evidences  → PersistedCollection (WPC Evidence Package)
├── evidences  → ReservoirEstimatedVolumes (STOIIP P90/P50/P10 = 15.8/19.3/23.0 MSm³)
├── evidences  → ETPDataspace (RDDMS geomodel: maap/omegas)
├── evidences  → Wellbore:34-4-19S (exploration well)
│
├── informs    → ColumnBasedTable (Production Profile — 15-year P50)
├── informs    → DevelopmentConcept (4-slot template, CAP-X sidetrack)
├── informs    → Wellbore:Producer1 (planned producer)
├── informs    → Wellbore:Injector1 (planned injector)
├── informs    → Wellbore:34-4-19S (pilot scope)
│
├── constrains → Risk: Barium Scale (#00061) — CRITICAL
├── constrains → Risk: Injectivity — LOW PERM
│
├── PriorActivityIDs → Activity: WellCostEstimate
│
├── RiskIDs[] → 8 risks (Barium, Injectivity, Volume, Drilling,
│                        Schedule, ShallowGas, BOP, H2S)
│
└── ProjectSpecifications:
       NPV $116M, IRR 62%, CAPEX $213M, Breakeven $25/bbl, 16.5 Mboe

CollaborationProject: Omega Sør Field Development
├── LifecycleEvents[]:  8 events (project creation → SSVP delivery)
├── ActivityStates[]:   9 gate items (7 completed, 1 in-progress, 1 planned)
├── TrustedCollectionID → CollaborationProjectCollection (Trusted SoR)
└── Personnel[]:         stakeholders (RL, TL, geoscientist, drilling eng)
```

---

## Relationship Edges (Parameters[])

| Edge Type | Artifact | Title |
|---|---|---|
| `evidences` | PersistedCollection | WPC Evidence Package |
| `evidences` | REV-stats | Statistical volumes (P90/Mean/P10) |
| `evidences` | ETPDataspace | Geomodel dataspace (RDDMS) |
| `evidences` | — | Exploration well 34/4-19 S |
| `informs` | ProductionForecast | Production profile (15-year) |
| `informs` | DevelopmentConcept | Development Concept (4-slot template layout) |
| `informs` | Producer | Planned producer well |
| `informs` | Injector | Planned injector well |
| `informs` | Pilot | Pilot well scope |
| `constrains` | — | Barium scale risk (#00061) |
| `constrains` | — | Injectivity risk |

All implemented via `Keys[ParameterKey="relationship"]` — same pattern as Drogon DG1/DG2.

---

## Well Technical Records

The WPC decision links to a set of **well-focused technical records**:

### DevelopmentConcept (`OmegaSor-WPC:1`)

Contains inline structured data:
- **WellPlan**: 1 producer + 1 injector + 2 contingent slots
- **FacilityConcept**: Subsea tieback to Snorre N, 4-slot template, 8" prod flowline
- **DrainageStrategy**: Water injection (Tarbert), WAG-ready for Phase 2
- **EconomicsSummary**: NPV $116M at $75/bbl, CAPEX $213M

### GeoLabelSet (`OmegaSor-FormEval:1`)

Per-zone formation evaluation from 34/4-19 S well data:

| Zone | NTG | Phi | Sw | K (mD) | NetPay (m) | STOIIP P50 (MSm³) |
|------|-----|-----|----|----|--------|--------|
| Tarbert Fm | 0.92 | 0.24 | 0.18 | 850 | 52 | 13.1 |
| Rannoch Fm | 0.72 | 0.19 | 0.25 | 120 | 36 | 6.2 |
| **TOTAL** | **0.84** | **0.22** | **0.21** | **510** | **88** | **19.3** |

Linked to `Reservoir:OmegaSorAlfa:1` via `LabelledEntityID`.

### ColumnBasedTable — Production Profile (`OmegaSor-ProdProfile:1`)

15-year P50 forecast. Phase 1 (Jan 2029), Phase 2 (Jan 2030). Oil + water rates, cumulative oil.

### ColumnBasedTable — Well Cost AFE (`OmegaSor-WellCostAFE:1`)

Per-phase cost breakdown: mobilisation, surface hole, intermediate, reservoir section, completion, testing.

### TubularAssembly × 3

| Record | Content |
|--------|---------|
| `OmegaSor-Producer1-Completion:1` | Casing + completion for producer (CAP-X sidetrack) |
| `OmegaSor-Injector1-Completion:1` | Casing + completion for injector (4-slot template) |
| `OmegaSor-Contingency7Liner:1` | 7" contingency liner design |

### PPFGDataset (`OmegaSor-PPFG-Predrill:1`)

Pore pressure / fracture gradient – pre-drill prediction for Omega Sør.

### PlannedLithology (`OmegaSor-FormPrognosis:1`)

Formation prognosis for planned wells (zones, tops, expected lithology).

---

## Risk Records (8 total)

| ID | Name | Severity |
|----|------|----------|
| `OmegaSor-BariumScale-00061:1` | Barium scale (PIMS #00061) | **Critical** — Ba content unknown |
| `OmegaSor-Injectivity:1` | Low permeability / injectivity | Medium |
| `OmegaSor-VolumeUncertainty:1` | Subsurface volume uncertainty | Medium |
| `OmegaSor-DrillingCompletion:1` | Drilling & completion risk | Medium |
| `OmegaSor-ScheduleCost:1` | Schedule & cost overrun | Medium |
| `OmegaSor-ShallowGas:1` | Shallow gas (Hordaland Group) | Low-Medium |
| `OmegaSor-BOPReliability:1` | BOP reliability / well control | Low |
| `OmegaSor-H2S:1` | H₂S potential in reservoir | Low |

---

## CollaborationProject — Gate Lifecycle

### LifecycleEvents (8)

| Date | Event |
|------|-------|
| 2026-01-15 | Project created post exploration |
| 2026-02-01 | Exploration well results ingested |
| 2026-03-15 | Layout alternative — 4-slot template replaces injection CAP-X |
| 2026-06-10 | Simulation model delivered |
| 2026-06-10 | Economics delivered |
| 2026-06-12 | Barium scale risk raised to critical |
| 2026-06-15 | SSVP presentation delivered |
| 2026-06-15 | Preliminary well plans finalized |

### ActivityStates — Gate Checklist (9 items)

| Milestone | Status | Date |
|-----------|--------|------|
| SSVP-Volumes | ✅ Completed | 2026-06-10 |
| SSVP-Economics | ✅ Completed | 2026-06-10 |
| SSVP-WellPlan | ✅ Completed | 2026-06-15 |
| SSVP-DrainageStrategy | ✅ Completed | 2026-06-15 |
| SSVP-RiskAssessment | ✅ Completed | 2026-06-15 |
| SSVP-GeoModel | ✅ Completed | 2026-06-15 |
| SSVP-FacilityDesign | ✅ Completed | 2026-06-15 |
| SSVP-PilotWellScope | 🔄 InProgress | 2026-06-15 |
| SSVP-Approval | 📋 Planned | 2026-09-30 |

Gate readiness: **7/9 = 78%** (pilot well scope pending, approval target Sep 2026).

---

## Typed Remarks (BD)

| Source | Count | Example |
|--------|-------|---------|
| SSVP-Recommendation | 5 | "Approve Phase 1 wells (1P + 1I) for Omega Sør Alfa" |
| SSVP-Condition | 2 | "Pilot well must acquire formation water sample for Ba analysis" |
| SSVP-SubsurfaceRisk | 3 | "Gas cap probability negligible (PVT confirms). HIPS not required." |
| DG0-Recommendation | 2 | "Customize subsurface deliveries per adapted CVP" |
| Audit-Note | 2 | "SSVP presentation 2026-06-15. Concept screening validated post-exploration." |

---

## Full Record Inventory (Omega Sør, 209 total)

| Category | Kinds | Count |
|----------|-------|-------|
| **Decision** | BusinessDecision, CollaborationProject, PersistedCollection, CollaborationProjectCollection | 12 |
| **Wells** | Well, Wellbore, WellboreTrajectory, WellLog, WellboreMarkerSet | 14 |
| **Technical** | DevelopmentConcept, TubularAssembly, ColumnBasedTable, GeoLabelSet, PPFGDataset, PlannedLithology, Activity | 20+ |
| **Subsurface** | Reservoir, ReservoirSegment, ReservoirEstimatedVolumes | 4 |
| **Risks** | Risk | 8 |
| **Documents** | Document | 2 |
| **Geomodel** | ETPDataspace, GenericProperty, GenericRepresentation, HorizonInterpretation, FaultInterpretation, StratigraphicColumn/Unit, LocalBoundaryFeature | 80+ |
| **Seismic** | SeismicTraceData, FileCollection.SEGY, FileCollection.OpenVDS | 3 |

---

## Key Differences: WPC vs. Drogon DG2

| Aspect | Drogon DG2 (Concept Select) | Omega Sør WPC |
|--------|-------|-------|
| Decision type | Concept selection (3 alternatives) | Well planning approval |
| Edge types used | evidences, supersedes, constrains, mitigates, alternativeTo, informs | evidences, constrains, informs |
| `alternativeTo` | Yes (reduced-scope vs full) | No (single concept) |
| `supersedes` | Yes (DG1→DG2 evolution) | No (first WPC gate) |
| Well technical depth | Minimal (wells not designed yet) | Full (TubularAssembly, PPFG, PlannedLithology) |
| GeoLabelSet | Not used | Per-zone formation evaluation with Table |
| DevelopmentConcept | v4 with alternatives | v4 with inline WellPlan + FacilityConcept |
| Pilot well dependency | None | Critical (barium content drives decision tree) |
| Economics source | NPV $520M, IRR 17% | NPV $116M, IRR 62% |

---

## Data Sources

### SharePoint — Decision Documents

Project area: [Petec – Marginal Subsea Tieback Portfolio – OS](https://statoilsrm.sharepoint.com/sites/IDM-PM954-Petec/Snorre%20IOROS/DG1/OS)

| Document | SharePoint Path | Content |
|----------|----------------|---------|
| [20260615_OmegaSør_SSVP.pptx](https://statoilsrm.sharepoint.com/:p:/r/sites/IDM-PM954-Petec/Snorre%20IOROS/DG1/OS/SSVP/20260615_OmegaS%C3%B8r_SSVP.pptx?d=w93c48c340f23443e909fcf1e17be45a4&csf=1&web=1&e=wurdeE) | `SSVP/` | SSVP presentation — volumes, risks, economics, wells, maps |
| `Well information and design basis - Omega S.xlsx` | `SSVP/` | Casing design, PPFG, formation prognosis, contingency liner |
| `RCmeeting_OmegaSor.pptx` | `SSVP/` | Resource Committee meeting presentation |
| `DW112 - Activity Program Signature Presentation NO 34_4-19 S Omega S.pptx` | `exploration/` | Drilling activity program (BHA, casing, risk) |
| `EOWR - Omega S.pptx` | `exploration/` | End-of-well report (34/4-19 S) |
| `Risk analysis concept phase.pptx` | `exploration/` | Risk register & mitigations |
| `Handover MWP to PreEx.pptx` | `exploration/` | MWP → Pre-exploration handover |
| `Handover PEX to OC.pptx` | `exploration/` | Pre-exploration → OC handover |
| `34_4-19 S Omega S_DW100 Handover...docx` | `exploration/` | DW → Licence handover document |

Well project site: [WCPNO344-19S](https://statoilsrm.sharepoint.com/sites/WCPNO344-19S)

### RMS Geomodel

```
\\statoil.net\unix_st\project\snorre\reservoirmodels\omegasor\2026.2.0\rms\model\os_cond.rms15.0.1.0
```

RMS 15 model — authoritative source for all subsurface objects (horizons, faults, grid, trajectories, properties). Exported via EPC → ETP to RDDMS dataspace `maap/omegas`.

### DecisionSpace Geoscience (DSG)

| Property | Value |
|----------|-------|
| Project | `sipi_OmegaS_Postwell_2026` |
| District | VM (SNORRE_AREA / SNORRE_TORDIS_VIGDIS) |
| Seismic survey | CGG23M01_NVG21PH2-DAZ_final_Ki-PreSDM_t_fullstk |
| Clip | IL 6250–6450, XL 31200–31400 (±100 around 34/4-19 S) |

### Volume Tables

| Source | Content |
|--------|---------|
| `os.vol.xls_oil_1.xls` / `os.vol.xls_total_1.xls` | STOIIP, recovery factors per zone (RMS volumetrics export) |

### Well Data (SMDA cross-partition)

| Property | Value |
|----------|-------|
| Well | 34/4-19 S (NO 34/4-19 S) |
| SMDA Well ID | `data:master-data--Well:78aa3a39a9fe444eb50e3d843a25d796:` |
| SMDA Wellbore ID | `data:master-data--Wellbore:7dccc5be5a4944eda7cdc0c877be2729:` |
| TD (driller) | 4120 m MD / 3902.81 m TVD |

---

## File References

| File | Content |
|---|---|
| `demo/eqn/omegas/ontology_examples/bd_omegas_ssvp.json` | BD record (WPC decision with relationships) |
| `demo/eqn/omegas/ontology_examples/cp_omegas_ssvp.json` | CP record (lifecycle, gate checklist) |
| `demo/eqn/omegas/gen_well_technical_omegas.py` | Generator for all well technical records |
| `demo/eqn/omegas/manifest_welltechnical_omegas.json` | Output manifest (10 records) |
| `demo/eqn/omegas/gen_master_omegas.py` | Master data generator (Well, Wellbore, Reservoir) |
| `demo/eqn/omegas/gen_drilling_omegas.py` | Drilling activities + trajectories |
| `demo/eqn/omegas/gen_risk_omegas.py` | Risk records (8) |
| `demo/eqn/omegas/gen_volumes_omegas.py` | ReservoirEstimatedVolumes |
| `demo/eqn/omegas/gen_collection_omegas.py` | PersistedCollection + CollaborationProjectCollection |
