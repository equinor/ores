# Data Set 2 - Dionisos Process-Based Geomodel (Coastal Deltaic)

## Purpose

Synthetic dataset generated from the **Dionisos** forward stratigraphic
modelling software. Represents a coastal deltaic system where the
stratigraphy is *known* because it was forward-modelled - providing
ground truth for validation.

## Wells: 9

Nine wells extracted from a Dionisos 3D stratigraphic simulation of
a prograding coastal deltaic system.

## Data Channels

- **X, Y, Depth**: 3D coordinates
- **Facies** (region): Depositional facies from forward model
- **Azimuth**: Structural azimuth from model geometry
- **Dip**: Structural dip from model geometry

## External Files

- **dep_profile.txt**: Depositional profile from Dionisos output
- **dep_facies.txt**: Facies spatial distribution from forward model

## Geological Context

Dionisos (developed at IFP Energies nouvelles) simulates sediment
transport, deposition, and compaction over geological time scales.
The resulting 3D model is *physically consistent* - mass is conserved,
Walther's Law is satisfied by construction, and the geometry
reflects the modelled basin accommodation and sediment supply.

## Correlation Strategy

Uses the **B3D** (3D Bézier) cost function with structural dip/azimuth
data from the forward model. The known model stratigraphy serves as
ground truth for assessing correlation accuracy.

## Significance

Process-based models provide the **only true ground truth** for
correlation algorithms because the time-surfaces are known exactly.
Real outcrop/well data always has residual uncertainty in the
reference correlation itself.

## References

- Granjeon, D. & Joseph, P. (1999) Concepts and applications of a 3-D
  multiple lithology, diffusive model in stratigraphic modeling. In:
  *Numerical Experiments in Stratigraphy*, SEPM Spec. Pub. 62, 197–210.
- Granjeon, D. (2014) 3D forward modelling of the impact of sediment
  transport and base level cycles on continental margins and incised
  valleys. *Int. Assoc. Sedimentol. Spec. Pub.* 46, 453–472.
- Baville, P. (2022) *Stratigraphic correlation of well logs using
  graph-based dynamic time warping*, PhD Thesis, Université de Lorraine, §6.2.
- Burgess, P.M. (2012) A brief review of developments in stratigraphic
  forward modelling. In: *Regional Geology and Tectonics*, Elsevier.

## Authors

Christophe Antoine, Guillaume Caumon, Paul Baville - ASGA/RING, Université de Lorraine.
