# Fluvial Channel Belt Dataset

## Geological Setting

Synthetic **fluvial channel belt** system representing a low-accommodation
alluvial plain (Triassic Skagerrak / Statfjord / Ivishak analogue). Wells
penetrate laterally discontinuous channel sandbodies encased in floodplain
mudstones. This represents one of the **hardest correlation scenarios** in
subsurface geology because:

- Individual channels do **not** extend laterally across all wells
- Channels at similar depths in adjacent wells may be **unconnected**
- Stacked channels from **avulsion** mimic a single amalgamated body
- No marine flooding surfaces → no isochronous markers

## Facies Model

| ID | Name              | GR (API) | Geometry                         |
|----|-------------------|----------|----------------------------------|
| 1  | Channel sand      | 25–45    | Blocky (fining-up top), 3–12 m   |
| 2  | Crevasse splay    | 45–65    | Thin sheet, 0.5–3 m              |
| 3  | Floodplain mud    | 90–130   | Background, 2–20 m               |
| 4  | Paleosol          | 65–85    | Mottled, 0.5–2 m (time marker)   |
| 5  | Lacustrine        | 100–120  | Thin, correlatable marker         |

## Wells

20 wells on a grid. Channel connectivity varies from well to well:
some well-pairs share the same channel body, others see entirely
different channel systems at the same depth.

## Data Channels

- **GR**: Gamma ray (API) - sole correlation log
- Regions: none (unconstrained - reflects real-world fluvial data poverty)

## Correlation Strategy

### `options.txt` - GR variance only
Low `const-gap-cost` (0.5) allows isolated sand lenses that don't correlate.
High `min-dist` (0.4) forces genuinely different geometric interpretations:
- Connected-sheet scenario (all channels correlate → one reservoir unit)
- Isolated-lens scenario (channels don't correlate → separate compartments)

## Key Correlation Challenges

1. **No unique solution**: The same GR pattern can be matched in multiple
   stratigraphically valid ways
2. **Lateral discontinuity**: Channels pinch out between wells - gap cost
   controls whether the engine "jumps" across or respects the discontinuity
3. **Amalgamation ambiguity**: Multiple stacked channels with thin mud
   between them could be one amalgamated body or separate events
4. **No time markers**: Without biozone/sequence constraints, the engine
   relies entirely on log-shape similarity

## Geological Significance

Fluvial reservoirs are notoriously difficult for correlation:

> "In channelised fluvial systems, traditional marker-bed correlation
> is impossible because no single bed is laterally continuous."
> - Bridge & Leeder (1979)

The n-best diverse outputs represent fundamentally different reservoir
connectivity models, each with different implications for fluid flow.

## References

- Bridge, J.S. & Leeder, M.R. (1979) A simulation model of alluvial
  stratigraphy. *Sedimentology* 26, 617–644.
- Gibling, M.R. (2006) Width and thickness of fluvial channel bodies and
  valley fills in the geological record. *J. Sed. Res.* 76, 731–770.
- Colombera, L. et al. (2013) A quantitative approach to fluvial facies
  models: Methods and example results. *Sedimentology* 60, 1526–1558.
- Larue, D.K. & Hovadik, J. (2006) Connectivity of channelized reservoirs:
  A modelling approach. *Petroleum Geoscience* 12, 291–308.
- Baville, P. (2022) *Stratigraphic correlation of well logs using
  graph-based dynamic time warping*, PhD Thesis, Université de Lorraine.
- Miall, A.D. (1996) *The Geology of Fluvial Deposits*, Springer, 582 pp.

## Generation

```bash
python generate_fluvial.py [--n_wells 20] [--seed 42]
```
