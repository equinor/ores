# Data Set 1.2 - No-Crossing Cost Function Test

## Purpose

Synthetic toy example demonstrating the **no-crossing** constraint.
Correlation lines are forbidden from crossing defined stratigraphic
boundaries (e.g., biozone limits, sequence boundaries).

## Wells: 3

Three synthetic wells with defined interval boundaries (**NoCrossing**
region) that act as hard constraints.

## Data Channels

- **Depth**: Simulated measured depth
- **NoCrossing** (region): Interval boundaries that horizons cannot cross

## Correlation Cost Function

The **no-crossing** constraint works as an infinite penalty: any
candidate correlation path that would place a horizon on the wrong
side of a boundary is assigned cost = ∞ and excluded from the
dynamic programming search.

This implements the biostratigraphic principle that:
> Biozones define time intervals - correlation lines connecting
> coeval strata cannot cross biozone boundaries.

In the DTW graph, no-crossing modifies the adjacency structure by
removing edges that would violate boundary ordering.

## Geological Analogue

- **Biozones**: First/last occurrence of index fossils
- **Sequence boundaries**: Unconformity surfaces
- **Ash beds (bentonites)**: Isochronous volcanic markers
- **Magnetic polarity reversals**: Global time markers

## References

- Edwards, J. et al. (2017) Uncertainty management in stratigraphic well
  correlation. *Computers & Geosciences* 111, 1–17.
- Lallier, F. (2012) *Corrélation de puits en domaine carbonaté*, PhD
  Thesis, Université de Lorraine.
- Gradstein, F.M. et al. (2012) *The Geologic Time Scale 2012*, Elsevier.
- Baville, P. (2022) PhD Thesis, Université de Lorraine, §3.4.

## Authors

Christophe Antoine, Guillaume Caumon, Paul Baville - ASGA/RING, Université de Lorraine.
