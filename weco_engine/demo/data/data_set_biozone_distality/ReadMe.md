# Data Set 4 - Hugin Formation, Sigrun Field (2 wells, facies grouping)

## Source

**Hugin Formation** (Upper Jurassic), Sigrun field, block 15/3, South
Viking Graben, Norwegian North Sea. Two wells provided by **Equinor ASA**.

## Wells: 2

Two wells (W04, W11) with detailed facies interpretation and multiple
facies grouping schemes to test the effect of **facies equivalence classes**
on correlation results.

## Data Channels

- **Depth**: Measured depth (m)
- **Facies** (region): Full depositional facies (8 categories)
- **Facies_1, Facies_2, ...** (regions): Grouped facies schemes where
  laterally equivalent facies share the same code
- **Distality** (region): Relative well position (proximal/distal)

## Geological Context

The same geological setting as data_set_distality (tide-dominated shallow marine),
but focusing on **two wells** to study how facies grouping affects the
distality cost function.

### Facies Grouping Philosophy

Not all individual facies transitions are geologically meaningful for
correlation. Some facies are **lateral equivalents** that should be
treated as the same category for Walther's Law purposes:

| Group | Contains              | Geological Meaning           |
|-------|-----------------------|------------------------------|
| A     | Tidal channel + Bar   | Proximal high-energy system  |
| B     | Upper/Lower shoreface | Intermediate wave zone       |
| C     | Prodelta + Offshore   | Distal low-energy system     |

Different grouping schemes (Facies_1, Facies_2, ...) produce different
correlation results - demonstrating the **sensitivity of distality-based
correlation to the geological interpretation**.

## Correlation Strategy

Tests the `dist-facies` option with different `Facies_i` columns,
combined with `dist-distal` = Distality and `dist-scaling` = 1.0.

### Gap cost sensitivity
Also includes outcome files for varying `const-gap-cost` (4, 5, 7, 8)
to demonstrate how gap penalty affects discontinuity handling.

## References

- Knaust, D. & Hoth, S. (2021) Depositional environment of the Hugin
  Formation in the Gudrun/Sigrun area, South Viking Graben. *Marine
  and Petroleum Geology* 133, 105236.
- Baville, P. et al. (2022) Computer-assisted stochastic multi-well
  correlation: Sedimentary facies versus well distality. *Marine and
  Petroleum Geology* 135, 105371.
- Baville, P. (2022) *Stratigraphic correlation of well logs using
  graph-based dynamic time warping*, PhD Thesis, Université de Lorraine, §5.
- Ainsworth, R.B. (2005) Sequence stratigraphic-based analysis of
  reservoir connectivity: influence of sealing faults - a case study
  from a marginal marine depositional setting. *Petroleum Geoscience*
  11, 257–276.

## Authors

Christophe Antoine, Guillaume Caumon, Paul Baville - ASGA/RING, Université de Lorraine.
Well data courtesy of Equinor ASA.
