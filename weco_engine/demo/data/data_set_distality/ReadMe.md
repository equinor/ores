# Data Set 3 - Hugin Formation, Gudrun–Sigrun Field Area (7 wells)

## Source

**Hugin Formation** (Upper Jurassic, Oxfordian–Kimmeridgian), Gudrun–Sigrun
field area, blocks 15/3 and 15/5, South Viking Graben, Norwegian North Sea.
Well data provided by **Equinor ASA**.

## Wells: 7

Seven exploration/appraisal wells with interpreted sedimentary facies,
relative well distality, and biostratigraphic data.

## Data Channels

- **Depth**: Measured depth (m)
- **Facies** (region): Interpreted depositional facies (tide-influenced
  shallow marine, codes 1–8)
- **Distality** (region): Relative proximal-distal position
  (1=distal/offshore → N=proximal/onshore)

## Well Subsets

| File     | Wells              | Purpose                              |
|----------|--------------------|--------------------------------------|
| wells_A  | All 7              | Full correlation problem             |
| wells_B  | W04, W11           | Two-well pair (distality demo)       |
| wells_C  | W04, W05, W11      | Three-well sub-panel                 |
| wells_D  | W01, W03, W07      | Alternative three-well selection     |
| wells_E  | W07, W09, W11      | Distal wells only                    |

## Geological Context

The Hugin Formation is a **tide-dominated shallow marine** to coastal-plain
succession deposited during the late rifting phase of the Viking Graben.
The depositional system shows a proximal-to-distal gradient from tidal
channels and bars (high-energy, sandy) to prodelta and offshore muds
(low-energy, shaly).

Key geological features:
- **Lateral facies change**: Dramatic change from proximal tidal channels
  to distal offshore over ~10 km
- **Repeated parasequences**: Multiple transgressive–regressive cycles
  create correlation ambiguity
- **Biostratigraphic control**: Palynological biozones constrain
  chronostratigraphy (hard boundaries)

## Correlation Strategy

### Distality cost (option files 1x)
Uses `dist-distal` + `dist-facies` → enforces Walther's Law.
Facies ordering reflects palaeogeographic position.

### Multi-distality (option files 2x)
Tests multiple sediment transport directions (`multi_distal.txt`)
to determine best-fit palaeogeography.

## Validation

Correlation results are validated against **biostratigraphic interpretations**:
> "Multiple geological scenarios validation by confronting stratigraphic
> well correlation simulations to biostratigraphic interpretations."
> - Baville et al., Annual RING Meeting, 2022.

## References

- Baville, P. et al. (2022) Computer-assisted stochastic multi-well
  correlation: Sedimentary facies versus well distality. *Marine and
  Petroleum Geology* 135, 105371.
- Baville, P. (2022) *Stratigraphic correlation of well logs using
  graph-based dynamic time warping*, PhD Thesis, Université de Lorraine.
- Knaust, D. & Hoth, S. (2021) Depositional environment of the Hugin
  Formation in the Gudrun/Sigrun area. *Marine and Petroleum Geology*
  133, 105236.
- Cole, J.M. et al. (2008) The Hugin Formation: Reservoir geology and
  palaeogeography, Gudrun–Sigrun Area, North Sea. *Petrol. Geol. Conf.
  Proceedings* 7, 689–699.
- Boyd, R. et al. (2006) Estuarine and incised valley facies models.
  In: *Facies Models Revisited*, SEPM Spec. Pub. 84, 171–234.

## Authors

Christophe Antoine, Guillaume Caumon, Paul Baville - ASGA/RING, Université de Lorraine.
Well data courtesy of Equinor ASA.
