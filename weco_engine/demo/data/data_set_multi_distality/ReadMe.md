# Data Set 1.4 - Multi-Distality Cost Function Test

## Purpose

Synthetic toy example demonstrating the **multi-distality** cost function
(`multi-dist-distal`). Unlike the single distality cost (data_set_same_region), this
tests **multiple sediment transport directions** simultaneously and selects
the one producing the best correlation.

## Wells: 5

Five wells with interpreted **sedimentary facies**. No single distality
ordering is imposed on the wells - instead, several candidate transport
directions are evaluated during the correlation search.

## External Data

- **multi_distal.txt**: File containing N candidate sediment transport
  direction vectors. Each line defines a distality ordering for the wells.

## Geological Motivation

In many basins, the **palaeogeographic** transport direction is unknown
or changes through time (e.g., during tectonic rotation, delta lobe
switching, or at sequence boundaries). The multi-distality cost function
explores several plausible transport directions and reports which one
is most consistent with the observed facies distributions.

This addresses the question: *"What was the depositional dip direction?"*

## Cross-Section Variants

| File     | Geometry                          |
|----------|-----------------------------------|
| wells_A  | Transverse section, basin margin  |
| wells_B  | Longitudinal section, basin margin|
| wells_C  | Transverse section, bay-head delta|

## Correlation Cost Function

For each candidate transport direction $\mathbf{t}_k$:

1. Project well positions onto $\mathbf{t}_k$ → distality values
2. Compute standard distality cost $C_{dist,k}$
3. Select $\arg\min_k C_{dist,k}$ as the best-fit palaeotransport

## References

- Baville, P. (2022) *Stratigraphic correlation of well logs using
  graph-based dynamic time warping*, PhD Thesis, Université de Lorraine, §5.3.
- Baville, P. et al. (2022) Computer-assisted stochastic multi-well
  correlation: Sedimentary facies versus well distality. *Marine and
  Petroleum Geology* 135, 105371.
- Julio, C. et al. (2012) Statistical analysis of indirect stratigraphic
  simulations. *Mathematical Geosciences* 44, 891–910.

## Authors

Christophe Antoine, Guillaume Caumon, Paul Baville - ASGA/RING, Université de Lorraine.
