# Bryson Canyon Dataset

## Source
Neslen Formation (Upper Cretaceous), Bryson Canyon, Book Cliffs, Utah.
Coastal plain to estuarine deposits - coal-bearing sequences.
Exported from IC (Integrated Correlation) software as discrete facies logs.

## Wells: 7
B10, B11, B3, B5, B6, B7, B9

## Data Channels
- **MD**: Measured depth (m, positive downward, converted from TVD-SS)
- **FACIES**: Depositional facies (1-8)
- **DISTALITY**: Proximal-distal position derived from facies (1=proximal, 4=distal)
- **ZONE**: Reservoir zonation / sedimentary units (1-6)
- **SEQSTRAT**: Sequence stratigraphy boundaries (4th/5th order)

## Facies Legend
| Code | Name | Distality | Description |
|------|------|-----------|-------------|
| 1 | Coal | 1 (prox.) | Peat-forming swamp |
| 2 | Marsh | 1 (prox.) | Coastal marsh/swamp |
| 3 | Wave-influenced bayfill | 3 (dist.) | Wave-worked estuarine bay |
| 4 | Sub-bay | 4 (dist.) | Central bay/lagoon |
| 5 | Bayhead delta | 2 (int.) | Progradational bay-fill sand |
| 6 | Crevasse splay | 2 (int.) | Overbank sand sheets |
| 7 | Distributary channel | 1 (prox.) | Channel belt sand bodies |
| 8 | Lagoonal mud | 4 (dist.) | Quiet-water bay/lagoon mud |

## Sequence Stratigraphy
| Code | Name | Order |
|------|------|-------|
| 1 | Cozzette-SB | 4th |
| 2 | Buck MFS3 | 5th |
| 3 | Buck FS2 | 5th |
| 4 | Buck FS1 | 5th |
| 5 | Buck-SB | 4th |
| 6 | Corcoran FS3 | 5th |
| 7 | Corcoran MFS2 | 5th |
| 8 | Corcoran FS1 | 5th |
| 9 | Corcoran-SB | 4th |

## Correlation Strategy
1. **options_distal.txt**: Distal CCF - facies + distality (Walther's Law)
2. **options_seqstrat.txt**: Variance + SEQSTRAT same-region constraint
3. **options_basic.txt**: Unconstrained (shows ambiguity from coal seam repetition)

## Geological Context
The Neslen Formation represents tide/wave-influenced coastal-plain to estuarine
deposits. Coal seams form excellent local markers but split/merge laterally.
The challenge: repeated Coal-Marsh-Bayfill cyclicity creates ambiguity in
well-to-well correlation. Reservoir zonation (units 1-6) and 4th/5th-order
sequence boundaries constrain valid correlations.

## References

- Hettinger, R.D. & Kirschbaum, M.A. (2002) Stratigraphy of the Upper
  Cretaceous Mancos Shale and Mesaverde Group in the southern part of the
  Uinta and Piceance Basins. *USGS DDS-69-B*, 21 pp.
- Cole, R.D. & Cumella, S.P. (2005) Sand-body architecture in the Lower
  Williams Fork Formation (Upper Cretaceous), Coal Canyon, Colorado. *The
  Mountain Geologist* 42, 85–107.
- Yoshida, S. et al. (2004) Sequence stratigraphy and correlation of the
  Neslen and lower Farrer Formations, Book Cliffs, Utah. *SEPM Spec. Pub.*
  80, 221–246.
- Pattison, S.A.J. (2019) Re-interpreting stratigraphy of the Upper Cretaceous
  Mesaverde Group, Book Cliffs, Utah. *Sedimentology* 66, 1–35.
- Van Wagoner, J.C. et al. (1990) Siliciclastic sequence stratigraphy in
  well logs, cores, and outcrops. *AAPG Methods Explor.* 7, 55 pp.
- Baville, P. (2022) *Stratigraphic correlation of well logs using
  graph-based dynamic time warping*, PhD Thesis, Université de Lorraine.

## Authors

Christophe Antoine, Guillaume Caumon, Paul Baville - ASGA/RING, Université de Lorraine.
