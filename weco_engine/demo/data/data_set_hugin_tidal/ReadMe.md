# EAGE 2024 Conference Dataset

## Source

Demonstration dataset prepared for the **EAGE 2024 Annual Conference**
(Oslo, Norway). Consists of 2 wells from the **Hugin Formation** (Gudrun–Sigrun
field area, Norwegian North Sea) with interpreted depositional facies.

## Wells: 2

Well_11, Well_04 - extracted from Equinor ASA subsurface database.

## Data Channels

- **Depth**: Measured depth (m)
- **Facies**: Interpreted sedimentary facies (1–8, tide-influenced shallow marine)
- **Distality**: Relative well distality (1=distal, 4=proximal)

## Geological Context

The Hugin Formation (Upper Jurassic, Oxfordian–Kimmeridgian) is a tide-dominated
shallow marine to coastal plain succession in the South Viking Graben. The two
wells span the proximal (tidal channel/bar) to distal (prodelta/offshore)
environmental gradient of the depositional system.

This subset was used to demonstrate the **distality cost function** (Walther's
Law constraint) at the EAGE workshop on automated stratigraphic correlation.

## Correlation Strategy

Uses the **distality cost function** (`dist-facies` + `dist-distal`) to enforce
the lateral facies ordering predicted by Walther's Law of Facies:
> Facies that are found superimposed on one another in conformable vertical
> succession must also occur in laterally adjacent environments.

## References

- Baville, P. et al. (2024) Automated stratigraphic well correlation with
  geological constraints. *EAGE Annual Conference*, Oslo.
- Baville, P. (2022) *Stratigraphic correlation of well logs using
  graph-based dynamic time warping*, PhD Thesis, Université de Lorraine.
- Knaust, D. & Hoth, S. (2021) Depositional environment of the Hugin
  Formation in the Gudrun/Sigrun area, South Viking Graben, Norwegian
  North Sea. *Marine and Petroleum Geology* 133, 105236.
- Walther, J. (1894) *Einleitung in die Geologie als historische
  Wissenschaft*, Bd. 3, Fischer, Jena, 535–1055.
