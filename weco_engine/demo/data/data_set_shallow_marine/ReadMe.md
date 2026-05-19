# Shallow Marine Dataset — Hugin Formation Analogue

## Geological Setting

Prograding wave-dominated shoreface / bay-fill system inspired by the
Upper Jurassic **Hugin Formation** (Viking Graben, North Sea). The
succession records five stacked parasequences (PS1–PS5) spanning a
shoreface–bay fill depositional system.

Wells are arranged along **depositional dip** (Y axis). The key
architectural element is **clinoform progradation**: individual beds
*thicken downdip*, producing the lateral thickness changes that challenge
standard layer-cake correlation.

## Facies Model (8 facies)

| ID | Name              | GR (API) | RT (Ω·m) | RHOB (g/cc) | NPHI (v/v) | DT (µs/ft) |
|----|-------------------|----------|-----------|-------------|------------|-------------|
|  1 | Offshore mud      |  120±12  |  1.5±0.4  | 2.45±0.03   | 0.32±0.03  |   95±8      |
|  2 | Offshore transit. |   90±15  |  3.0±0.8  | 2.40±0.04   | 0.28±0.03  |   85±7      |
|  3 | Lower shoreface   |   65±12  |  8.0±2.0  | 2.30±0.04   | 0.22±0.03  |   75±6      |
|  4 | Upper shoreface   |   40±10  | 15.0±4.0  | 2.20±0.03   | 0.18±0.02  |   68±5      |
|  5 | Foreshore         |   25±8   | 25.0±6.0  | 2.15±0.03   | 0.14±0.02  |   62±4      |
|  6 | Bay-fill mud      |  110±15  |  2.0±0.5  | 2.50±0.04   | 0.35±0.04  |   98±9      |
|  7 | Tidal channel     |   35±10  | 12.0±3.0  | 2.22±0.04   | 0.20±0.03  |   70±6      |
|  8 | Transgressive lag |   45±12  | 20.0±5.0  | 2.55±0.05   | 0.12±0.03  |   60±5      |

## Parasequence Stacking

| PS  | Base thickness | Proximal                   | Distal                   | Thickening |
|-----|---------------|----------------------------|--------------------------|------------|
| PS1 |  8.0 m        | LSF → USF → Foreshore      | Offshore → Transit → LSF | 15%/well   |
| PS2 |  6.0 m        | Tidal → USF → Foreshore    | Bay-fill → Transit → LSF | 10%/well   |
| PS3 | 10.0 m        | LSF → USF → Foreshore      | Transit → LSF → USF      | 20%/well   |
| PS4 |  3.0 m        | Lag → Transit → LSF        | Lag → Offshore → Transit | 5%/well    |
| PS5 |  9.0 m        | LSF → USF → Foreshore      | Transit → LSF → USF      | 18%/well   |

## Biozones

Two biostratigraphic markers subdivide the section:

- **BZ1** — base of PS2 (separates PS1 from PS2–PS5)
- **BZ2** — base of PS4 (separates PS2–PS3 from PS4–PS5)

## Correlation Strategy

### `options.txt` — default
Uses **GR** (50%) + **RHOB** (30%) + **DT** (20%) variance cost functions.
Works well for clean sand/shale discrimination.

### `options_distality.txt` — with distality cost
Adds the **distality** cost function (FACIES channel) at 10% weight.
Facies groups encode lateral equivalence:
`1,6; 2,8; 3,7; 4,5` — onshore mud ↔ offshore mud, etc.

### `options_with_biozones.txt` — biozone constraints
Uses biozone region as `no_crossing` constraint, preventing
correlations from crossing BZ1 or BZ2 boundaries. This dramatically
reduces the search space and improves accuracy.

## Running

```bash
cd data/data_set_shallow_marine
python generate_shallow_marine.py       # generates wells.txt + options
weco wells.txt -o options.txt           # run default correlation
weco wells.txt -o options_distality.txt # run with distality
weco wells.txt -o options_with_biozones.txt  # run with biozones
```

## References

- Baville (2022) *Stratigraphic correlation of well logs using graph-based
  dynamic time warping*, PhD Thesis, Université de Lorraine, §6.
- Kieft et al. (2010) Sedimentology of the Hugin Formation, North Sea.
- Ainsworth (2005) Sequence stratigraphy of the Upper Jurassic shallow
  marine deposits.
- Catuneanu (2006) *Principles of Sequence Stratigraphy*, Elsevier.
