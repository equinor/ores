# Data Set 1.5 - B3D (3D Bézier) Cost Function Test

## Purpose

Synthetic toy example demonstrating the **B3D** (3D Bézier curve/patch)
correlation cost function. This advanced cost function uses structural
geometry (dip, azimuth) and a conceptual depositional profile to
constrain correlations in three-dimensional space.

## Wells: 7

Seven wells with interpreted **sedimentary facies**, **structural dip**,
and **structural azimuth** as functions of depth.

## Data Channels

- **Depth**: Measured depth (m)
- **Facies** (region): Depositional facies codes
- **Dip**: Structural dip angle (degrees from horizontal)
- **Azimuth**: Structural azimuth (degrees from north)

## External Files

- **dep_profile.txt**: Conceptual depositional profile parameters -
  spatial extension of the depositional system and sediment transport
  direction (dx, dy, dz, sed_dir).
- **dep_facies.txt**: Theoretical facies distribution as a function of
  depositional depth within the profile - defines where each facies
  *should* occur in 3D space (id, dx, dy, dz, z↑, z↓).

## Correlation Cost Function

The B3D cost function fits a 3D Bézier curve (or patch) through the
correlation markers, honouring:

1. **Structural dip/azimuth** at each well → tangent constraint
2. **Depositional facies position** within the conceptual profile
3. **Smooth geometry** → Bézier parametrisation prevents kinks

This produces geologically reasonable 3D surface shapes rather than
arbitrary zigzag paths through the DTW graph.

## Geological Motivation

In structurally complex settings (tilted fault blocks, growth faults,
clinoform-dominated deltas), horizons are not horizontal in depth space.
The B3D cost function encodes the expectation that:

- Horizons have **smooth, continuous curvature**
- The **dip direction** is consistent with measured dipmeter data
- Facies positions respect the **depositional model geometry**

## References

- Baville, P. (2022) *Stratigraphic correlation of well logs using
  graph-based dynamic time warping*, PhD Thesis, Université de Lorraine, §7.
- Baville, P. et al. (2024) 3D Bézier curve fitting for stratigraphic
  correlation with structural constraints. *Mathematical Geosciences*.
- Caumon, G. et al. (2013) Surface-based 3D modeling of geological
  structures. *Mathematical Geosciences* 45, 927–952.
- Farin, G. (2002) *Curves and Surfaces for CAGD*, 5th ed., Morgan Kaufmann.

## Authors

Christophe Antoine, Guillaume Caumon, Paul Baville - ASGA/RING, Université de Lorraine.
