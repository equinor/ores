# Data Set 1.3 - Distality Cost Function Test (Walther's Law)

## Purpose

Synthetic toy example demonstrating the **distality** correlation cost
function (`dist-facies` + `dist-distal`). This cost function implements
**Walther's Law of Facies**: laterally adjacent environments must produce
vertically adjacent facies in conformable successions.

## Wells: 5

Five wells with interpreted **sedimentary facies** and **relative well
distality** (proximal–distal position), arranged in three different
cross-section geometries:

| File     | Geometry                           | Challenge            |
|----------|------------------------------------|-----------------------|
| wells_A  | Transverse section, basin margin   | Dip-parallel gradient |
| wells_B  | Longitudinal section, basin margin | Strike-parallel (no gradient) |
| wells_C  | Transverse section, bay-head delta | Convergent gradient   |

## Data Channels

- **Depth**: Measured depth (m)
- **Facies** (region): Sedimentary facies codes (ordered by distality)
- **Distality** (region): Relative well position along depositional dip
  (1 = most distal/offshore, N = most proximal/onshore)

## Correlation Cost Function

The distality cost penalises correlations that violate the expected
relationship between facies and well position:

$$C_{dist} = 0.9 \cdot (s \cdot \Delta d_{dist} - \Delta f)^2$$

where:
- $\Delta d_{dist}$ = difference in well distality between two wells
- $\Delta f$ = difference in facies code at tied markers
- $s$ = scaling factor (`dist-scaling`)

**Key behaviour**: If Well A is more proximal than Well B, then at
any correlated horizon, Well A should show a more proximal facies.
Violations are penalised quadratically.

## Geological Principle

Walther (1894):
> *"Die verschiedenen Fazies derselben Gebirgsgruppe [...] können sich
> nur in seitlich nebeneinanderliegenden Räumen entwickeln."*
>
> (The various facies of the same formation can only develop in
> laterally adjacent spatial domains.)

This means: facies transitions observed vertically at one location
must also occur as lateral transitions at the same time-horizon.

## References

- Walther, J. (1894) *Einleitung in die Geologie als historische
  Wissenschaft*, Bd. 3, Fischer, Jena, 535–1055.
- Baville, P. (2022) *Stratigraphic correlation of well logs using
  graph-based dynamic time warping*, PhD Thesis, Université de Lorraine, §5.
- Baville, P. et al. (2022) Computer-assisted stochastic multi-well
  correlation: Sedimentary facies versus well distality. *Marine and
  Petroleum Geology* 135, 105371.
- Caumon, G. et al. (2013) Surface-based 3D modeling of geological
  structures. *Mathematical Geosciences* 45, 927–952.

## Authors

Christophe Antoine, Guillaume Caumon, Paul Baville - ASGA/RING, Université de Lorraine.
