# Carbonate Platform Dataset

## Geological Setting

Synthetic **tropical carbonate platform** (Jurassic/Cretaceous or Permian
analogue). Modelled on the **Arabian Plate** / **Bahamas** / **Permian Basin**
reef complexes. 20 boreholes through a prograding/aggrading carbonate
platform showing metre-scale (parasequence) and large-scale (3rd-order
sequence) cyclicity.

Carbonate platforms have fundamentally different correlation challenges
compared to siliciclastic systems:
- GR is **unreliable** (no clay baseline in clean carbonates)
- Porosity logs (**DEN, SON, NEU**) are the primary discriminators
- **Diagenetic overprint** can mask original depositional texture
- **Facies mosaics** change rapidly both vertically and laterally

## Facies Model (proximal → distal)

| ID | Name               | GR (API) | DEN (g/cc) | SON (µs/ft)| NEU (%) | Position |
|----|--------------------|----------|------------|-----------|---------|----------|
| 1  | Supratidal (sabkha)| 70–100   | 2.90–2.95  | 48–52     | 0–3     | Proximal |
| 2  | Intertidal laminite| 40–60    | 2.65–2.72  | 50–58     | 3–8     | Proximal |
| 3  | Lagoon (wackestone)| 25–45    | 2.50–2.65  | 55–68     | 8–15    | Intermediate |
| 4  | Shoal (grainstone) | 8–20     | 2.30–2.50  | 55–70     | 15–25   | Intermediate |
| 5  | Fore-reef (rudstone)| 15–30   | 2.35–2.55  | 52–65     | 10–20   | Distal   |
| 6  | Slope (argill. mud)| 50–80    | 2.50–2.60  | 60–75     | 5–12    | Distal   |
| 7  | Basin (pelagic marl)| 55–90   | 2.35–2.50  | 70–90     | 12–20   | Distal   |

## Logs

| Log  | Description            | Unit    | Key Feature                      |
|------|------------------------|---------|----------------------------------|
| GR   | Natural gamma ray      | API     | Low in carbonates, raised in marls|
| DEN  | Bulk density           | g/cc    | Anhydrite=2.95, porous grain=2.3 |
| SON  | Sonic slowness         | µs/ft   | Tight carbonate=48, porous=70    |
| NEU  | Neutron porosity       | %       | Grainstone=20%, mudstone=5%      |
| RT   | Resistivity            | Ω·m     | Tight >200, porous 20–50         |
| PEF  | Photoelectric factor   | barns/e | Limestone=5.1, dolomite=3.1      |

## Wells

20 wells arranged across the platform-to-basin transect. Proximal wells
dominated by shoal/lagoon facies; distal wells by slope/basinal marls.

## Correlation Strategy

Multi-log approach essential - GR alone cannot discriminate facies:
- **DEN** + **SON** + **GR** + **NEU** composite cost
- FACIES region with distality cost for Walther's Law enforcement
- Biozone no-crossing where available

## Key Correlation Challenges

1. **Diagenetic overprint**: Dolomitisation alters density/sonic locally
2. **Facies mosaic**: Patch reefs create lateral discontinuity at 100 m scale
3. **Cyclic repetition**: Metre-scale cycles repeat identically → ambiguity
4. **Karst unconformities**: Exposure surfaces create irregular erosion

## References

- Schlager, W. (2005) *Carbonate Sedimentology and Sequence Stratigraphy*,
  SEPM Concepts in Sedimentology and Paleontology 8, 200 pp.
- Tucker, M.E. & Wright, V.P. (1990) *Carbonate Sedimentology*, Blackwell, 482 pp.
- Lucia, F.J. (1999) *Carbonate Reservoir Characterization*, Springer, 226 pp.
- Kerans, C. & Tinker, S.W. (1997) *Sequence Stratigraphy and
  Characterization of Carbonate Reservoirs*, SEPM Short Course Notes 40.
- Goldhammer, R.K. et al. (1990) Depositional cycles, composite sea-level
  changes, cycle stacking patterns, and the hierarchy of stratigraphic
  forcing. *GSA Bulletin* 102, 535–562.
- Baville, P. (2022) *Stratigraphic correlation of well logs using
  graph-based dynamic time warping*, PhD Thesis, Université de Lorraine, §D6.

## Generation

```bash
python generate_carbonate.py
```
