# Omega Sør — Ontology Demo Examples

Real data from `20260615_OmegaSør_SSVP.pptx`. SSVP (pre-DG0) gate for
Omega Sør Alfa field development, Snorre area, block 34/4, PL057.

## Files

| File | Content | Source slides |
|------|---------|---------------|
| `bd_omegas_ssvp.json` | BD with relationship Keys[], typed Remarks[], economics | Slides 3, 6, 9, 11, 15, 21, 35 |
| `cp_omegas_ssvp.json` | CP with LifecycleEvents[], gate checklist, personnel | Slides 5, 9, 14, 15, 18, 20 |

## Key Real Data (from SSVP pptx)

### Volumes (Slide 9 — simulation model 10th June)
| | P90 | Mean | P10 |
|---|---|---|---|
| In-place Oil (MSm³) | 15.8 | 19.3 | 22.9 |
| Recoverable Oil (MSm³) | 3.3 | 5.4 | 8.0 |
| Oil RF (%) | 16.3 | 28.5 | 43.1 |

### Economics (Slide 11 — EQN share)
| | Phase 1 | Phase 2 | Total |
|---|---|---|---|
| NPV a.t. (MUSD) | 96 | 21 | 116 |
| Break-even (USD/bbl) | 25 | 29 | 25 |
| IRR | 62% | 65% | 62% |
| CAPEX (MUSD nom.) | 163 | 49 | 213 |
| Production (Mboe) | 13.6 | 2.9 | 16.5 |

### Risks (Slides 15, 20–22)
- **Barium scale (#00061)** — Critical. Ba content unknown from 34/4-19 S. Decision tree in place.
- **Low permeability / injectivity** — Impact on development strategy, HIPS assessment.
- **Volume/structural uncertainty** — RF range 16–43%, at VPBO maturity level.
- **Drilling & completion** — Deformation bands near ISF, sidetrack from existing well.
- **Schedule & cost overrun** — Adapted CVP timeline for subsea tieback.
- **Shallow gas, BOP reliability, H₂S** — Registered in PIMS PM978.

### Well Plans (Slides 34–35)
- **Pilot**: From template to deeper structure (OWC, Ba, Tarbert, deformation bands, core)
- **Producer**: Keeper from CAP-X, deep ST from 34/4-19 S, perf Tarbert+Rannoch
- **Injector**: From 4-slot template, ST from pilot, perf Tarbert only (base case), WI placement 5–20 m above OWC

### Facility Concept (Slides 6, 10)
- 4-slot template south of production CAP-X
- 8" production flowline, 6" water injection flowline
- Tieback to Snorre N-template (northern towhead structure)
- WAG-ready template, no gas injection line in Phase 1

### Schedule (Slide 14)
- SSVP: June 2026 (completed)
- DG0/WPC: Sep 2026 (pending pilot)
- DG3: Mar 2027
- DG4/FID: Sep 2027
- Installation: Jun 2028
- First oil: Jan 2029
- Phase 2: Jan 2030

## Ontology Patterns Applied

Same conventions as Drogon examples:
- `Parameters[].Keys[ParameterKey="relationship"]` — `evidences`, `informs`, `constrains`
- `LifecycleEvents[]` — audit trail with EventID conventions
- `ActivityStates[]` with `SSVP-*` prefix — gate deliverable checklist (8/9 done)
- `Remarks[]` with RemarkSource — `SSVP-Recommendation`, `SSVP-Condition`, `SSVP-SubsurfaceRisk`, `DG0-Recommendation`, `Audit-Note`
