# Sigrun Field Dataset

## Overview

Hugin Formation (Upper Jurassic), Sigrun field, block 15/3, Norwegian North Sea.
A tide-influenced shallow marine system with lateral facies changes from tidal
channels/bars (proximal) to prodelta/offshore (distal). Wells spaced 3–8 km.

Rebuilt from original RMS well exports, Equinor biostrat/facies databases,
and published flooding surface picks. See `rebuild_from_source.py` for the
complete data pipeline.

---

## Wells (6)

| Well | Distality | GR | NPHI | Core facies | Biostratigraphy |
|------|-----------|----|----|-------------|-----------------|
| 15_3-4 | 1 (proximal) | ✓ | ✓ | ✓ | ✓ |
| 15_3-5 | 2 | ✓ | ✓ | ✓ | ✓ |
| 15_3-9_T2 | 3 | ✓ | ✓ | GR-derived | ✓ |
| 15_3-7 | 3 | ✓ | - | GR-derived | ✓ |
| 15_3-3 | 3 | ✓ | - | GR-derived | ✓ |
| 15_3-1_S | 4 (distal) | ✓ | - | GR-derived | ✓ |

Sampling: ~1.5 m (resampled from 0.15 m wireline resolution for
sequence-scale correlation).

---

## Data Channels (7)

| Channel | Description | Source |
|---------|-------------|--------|
| GR | Gamma ray (API) | LFP_GR from RMS well export |
| NPHI | Total porosity (v/v) | LFP_PHIT; -999.25 where unavailable |
| BIOZONE | Biozone group (1–5) | Biozones_and_bioconfidence_edt.xlsx |
| SEQUENCE | Sequence zone (1–4) | Common flooding surface picks |
| FACIES | 5-class depositional facies | Core in 15_3-4/5; GR-derived elsewhere |
| FACIES3 | 3-class consolidation (Sand/Mixed/Shale) | Simplified from FACIES |
| ZONELOG_REF | Existing zone interpretation | RMS ZONELOG - for validation only |

## Regions (5)

| Region | Description | Entries |
|--------|-------------|---------|
| SEQUENCE | 4 zones from 3 flooding surfaces (FS_i, FS_h, FS_g) | All wells |
| BIOZONE | Biozone group intervals | All wells |
| FACIES | 5-class depositional facies intervals | All wells |
| FACIES3 | 3-class facies intervals | All wells |
| DISTALITY | Single-value per well (1=proximal, 4=distal) | All wells |

---

## Facies Classification

### FACIES (5-class, consolidation B)

| Code | Association | Typical GR | Wells with core |
|------|------------|-----------|-----------------|
| 1 | Channel / Bar | Low (< 50) | 15_3-4, 15_3-5 |
| 2 | Shoreface / Tidal Flat | Low–Med | 15_3-4, 15_3-5 |
| 3 | Lagoon / Bay | Med–High | 15_3-4, 15_3-5 |
| 4 | Prodelta / Offshore | High (> 80) | 15_3-4, 15_3-5 |
| 5 | Continental | Variable | 15_3-4, 15_3-5 |

### FACIES3 (3-class, consolidation C)

| Code | Class | GR threshold | Purpose |
|------|-------|-------------|---------|
| 1 | Sand | GR < 55 | Most conservative grouping |
| 2 | Mixed | 55 ≤ GR ≤ 85 | Transitional |
| 3 | Shale | GR > 85 | Fine-grained |

Wells without core (15_3-9_T2, 15_3-7, 15_3-3, 15_3-1_S) have facies
derived from GR cutoffs, consistent with the core-calibrated wells.

---

## Biostratigraphy

| Code | Age | Biozone (NPD) |
|------|-----|---------------|
| 1 | Oxfordian | Zone 35 |
| 2 | Early Kimmeridgian | Zone 36 |
| 3 | Late Kimmeridgian | Zone 37 |
| 4 | Early Volgian | Zone 38 |
| 5 | Late Volgian | Zone 39 |

Source: `Biozones_and_bioconfidence_edt.xlsx` (edited from Equinor reports).

---

## Flooding Surfaces (Sequence Boundaries)

Common markers present in ALL 6 wells, used for no-crossing constraint:

| Surface | Sequence below → above | Geological significance |
|---------|----------------------|------------------------|
| Hugin_FS_i | Zone 1 → 2 | Mid-Kimmeridgian flooding |
| Hugin_FS_h | Zone 2 → 3 | Late Kimmeridgian flooding |
| Hugin_FS_g | Zone 3 → 4 | Volgian flooding |

Additional picks exist (FS_j, FS_f, FS_fm, TopSleipner) but are NOT
used as constraints because they are not reliably identified in all wells.

---

## Correlation Scenarios (6)

All scenarios run in ~5 seconds (1.5 m sampling, 46–165 samples/well).

| # | File | Method | Nodes | Cors | Purpose |
|---|------|--------|-------|------|---------|
| 1 | `options_1_gr_baseline.txt` | GR only | 256 | 1200 | Unconstrained reference |
| 2 | `options_2_gr_sequence.txt` | GR + no-crossing=SEQUENCE | 269 | 864 | Constrained by flooding surfaces |
| 3 | `options_3_gr_facies5.txt` | GR + dist-facies (5-class) | 256 | 198 | Facies-distality, most constrained |
| 4 | `options_4_gr_facies3.txt` | GR + dist-facies (3-class) | 256 | 1600 | Conservative facies |
| 5 | `options_5_composite_sequence.txt` | GR+NPHI + no-crossing | 252 | 1920 | Multi-signal |
| 6 | `options_6_full.txt` | GR + sequence + facies3 | 268 | 1400 | Combined constraints |

### Design philosophy

- Scenario 1 = **full uncertainty** (what does GR alone say?)
- Scenarios 2–5 = each adds ONE constraint type to test if it helps
- Scenario 6 = combination of best constraints
- Compare: if more constrained → LESS plausible → that constraint = noise

### Key findings

- Scenario 3 (5-class facies) gives fewest correlations (198) = most constrained
- Scenario 4 (3-class facies) is looser (1600) = conservative consolidation works better
- No-crossing + dist-facies combined (in initial tests) over-constrains → designed
  Scenario 6 to use sequence + facies3 (softer combination) instead

---

## Validation Against Published Correlation

The reference correlation panel (`tmp/sigrun/Correlation_panel_1_500_sigrun_wells.pdf`)
shows Equinor's internal interpretation of Hugin flooding surfaces. This represents
ONE of many possible solutions.

**Validation approach**: The published correlation should appear as one of the
n-best solutions in Scenarios 2 or 6 (which use the same flooding surfaces as
constraints). The remaining solutions represent genuine geological uncertainty.

**ZONELOG_REF** (existing zone log) is included as a data channel for
post-hoc validation - it is NEVER used as an input constraint.

---

## Source Data

| File | Content |
|------|---------|
| `tmp/sigrun/sigrun_wells/*.rmswell` | RMS well exports (7 wells, 6 used) |
| `tmp/sigrun/pickst.txt` | Flooding surface picks (well, surface, MD, TVDSS) |
| `tmp/sigrun/Biozones_and_bioconfidence_edt.xlsx` | Biozone assignments |
| `tmp/sigrun/15_3 Facies zones.xlsx` | Facies zone reference |
| `tmp/sigrun/depofacies.xlsx` | Depositional facies codes |
| `tmp/sigrun/doc/` | PDFs of correlation panels, reports, papers |

---

## References

### Primary geological references

- Kieft, R.L. et al. (2010) Sedimentology and sequence stratigraphy of the
  Hugin Formation, South Viking Graben. *Norwegian Journal of Geology* 90, 65–86.
- Hoth, S. et al. (2018) The Gudrun Field. In: *Norwegian Petroleum Society
  Special Publications*, Geological Society, London.
- Knaust, D. & Hoth, S. (2021) Depositional environment and reservoir quality
  of the Hugin Formation, Gudrun–Sigrun area, South Viking Graben. *Marine and
  Petroleum Geology* 133, 105236.
- Cole, J.M. et al. (2008) The Hugin Formation: Reservoir geology and
  palaeogeography in the Gudrun–Sigrun area. *Petroleum Geology Conference
  Proceedings* 7, 689–699.

### Regional stratigraphy

- Husmo, T. et al. (2003) Lower and Middle Jurassic. In: Evans, D. et al.
  (eds) *The Millennium Atlas*, Geological Society, London, 129–156.
- Rattey, R.P. & Hayward, A.B. (1993) Sequence stratigraphy of a failed rift
  system: the Middle Jurassic to Early Cretaceous basin evolution of the Central
  and Northern North Sea. *Geological Society Special Publication* 71, 215–249.
- Gudrun Regional Update (2012) Equinor internal report (Eriksfiord).

### Facies and depositional models

- Boyd, R. et al. (2006) Estuarine and incised valley facies models. In:
  *Facies Models Revisited*, SEPM Special Publication 84, 171–234.
- Walker, R.G. & Plint, A.G. (2006) Wave- and storm-dominated shallow marine
  systems. In: *Facies Models Revisited*, SEPM Special Publication 84.

### WeCo method

- Baville, P. (2022) *Stratigraphic correlation of well logs using graph-based
  dynamic time warping*, PhD Thesis, Université de Lorraine.
- Baville, P. et al. (2022) Computer-assisted stochastic multi-well correlation:
  Sedimentary facies versus well distality. *Marine and Petroleum Geology* 135,
  105371.

### Well data sources

- Well data: Equinor ASA / DISKOS national well database (public domain)
- Core facies interpretation: D. Knaust (Equinor)
- Biostratigraphy: Equinor / Eriksfiord reports
- Correlation panel: Equinor internal (15/3 Sigrun area)

---

## Rebuild

```bash
cd demo/data/data_set_sigrun
python rebuild_from_source.py
```

Requires: `tmp/sigrun/sigrun_wells/` (RMS exports), `tmp/sigrun/pickst.txt`,
`tmp/sigrun/Biozones_and_bioconfidence_edt.xlsx`.

Outputs: `wells.txt`, `wells.weco.json`, 6 option files.
