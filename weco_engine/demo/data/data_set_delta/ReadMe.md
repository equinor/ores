# Prograding Delta Dataset

## Geological Setting

Synthetic **river-dominated prograding delta** system (Cretaceous Gulf Coast /
Brent Group analogue). Wells intersect stacked, laterally prograding
parasequences where clinoform geometry causes significant thickness change
between proximal (topset) and distal (prodelta) positions.

The key correlation challenge: **lateral facies change** combined with
**progradation** means the same time-surface connects very different log
responses at different positions along depositional dip.

## Facies Model

| ID | Name             | GR (API) | DEN (g/cc) | NPHI (v/v) | Position     |
|----|------------------|----------|------------|------------|--------------|
| 1  | Prodelta mud     | 110–130  | 2.45–2.55  | 0.30–0.36  | Distal       |
| 2  | Distal delta front| 75–95   | 2.35–2.45  | 0.24–0.30  | Intermediate |
| 3  | Proximal delta front| 45–65 | 2.25–2.35  | 0.18–0.24  | Intermediate |
| 4  | Distributary mouth bar| 30–50| 2.15–2.25 | 0.14–0.20  | Proximal     |
| 5  | Distributary channel| 20–40 | 2.10–2.20  | 0.12–0.18  | Proximal     |
| 6  | Interdistributary bay| 100–120| 2.48–2.55 | 0.32–0.38  | Distal       |
| 7  | Transgressive lag| 40–60   | 2.50–2.60  | 0.10–0.16  | All          |

## Wells

8 wells arranged along depositional dip (NW–SE). Proximal wells show
thick channel/mouth-bar sand packages; distal wells are mud-dominated
with thin turbidite-like lobes.

## Data Channels

- **GR**: Gamma ray (API) - primary correlation log
- **DEN**: Bulk density (g/cc) - secondary discriminator
- **NPHI**: Neutron porosity (v/v) - porosity indicator
- **FACIES**: Depositional facies (region, codes 1–7)
- **SEQSTRAT**: Sequence stratigraphic boundaries (region, no-crossing)
- **DISTAL**: Well distality position (region, 1=distal → N=proximal)

## Correlation Strategy

### `options.txt` - GR + DEN variance with sequence constraints
Primary correlation using log waveform matching. SEQSTRAT `no-crossing`
locks parasequence boundaries as hard constraints.

### `options_distality.txt` - with Walther's Law cost
Adds the **distality** cost function which penalises correlations that
violate the expected lateral facies ordering (Walther's Law of Facies).

## Key Correlation Challenges

1. **Clinoform progradation**: Time-surfaces dip basin-ward - not horizontal
2. **Mouth-bar amalgamation**: Stacked channels appear as single thick sand
3. **Flooding surface diachroneity**: Transgressive lags are slightly time-
   transgressive
4. **Autocyclicity**: Delta-lobe switching produces random-like vertical facies
   succession that mimics different allocyclic controls

## References

- Coleman, J.M. & Wright, L.D. (1975) Modern River Deltas: Variability of
  Processes and Sand Bodies. *Deltas: Models for Exploration*, Houston Geol.
  Soc., 99–149.
- Bhattacharya, J.P. (2006) Deltas. In: *Facies Models Revisited*, SEPM
  Special Publication 84, 237–292.
- Ainsworth, R.B. et al. (2017) Anatomy of a shoreline regression:
  Implications for the high-resolution stratigraphic architecture of deltas.
  *J. Sed. Res.* 87, 425–459.
- Baville, P. (2022) *Stratigraphic correlation of well logs using
  graph-based dynamic time warping*, PhD Thesis, Université de Lorraine, §6.
- Catuneanu, O. (2006) *Principles of Sequence Stratigraphy*, Elsevier.

## Generation

```bash
python generate_delta.py [--n_wells 8] [--seed 42]
```
