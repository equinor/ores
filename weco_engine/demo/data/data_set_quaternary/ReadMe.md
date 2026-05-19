# Quaternary Hydrogeological Dataset
## Synthetic glacial/fluvioglacial well panel for aquifer–aquitard mapping

### Geological Setting
Northern European glacial lowland (Pleistocene).  Modelled on the
Dutch/German/Danish glacial stratigraphy (Weichselian/Saalian/Elsterian).

### Stratigraphy (top → bottom)
| Unit | Name           | Age              | Dominant Lithology        |
|:----:|----------------|------------------|---------------------------|
| U1   | Holocene       | 0–11.7 ka        | Peat, clay, sand          |
| U2   | Weichselian    | 11.7–115 ka      | Till, outwash sand/gravel |
| U3   | Eemian         | 115–130 ka       | Marine clay, peat         |
| U4   | Saalian        | 130–300 ka       | Till, outwash sand/gravel |
| U5   | Elsterian      | >300 ka          | Tunnel-valley gravel, till|

### Facies Scheme
| ID | Name         | GR (API) | RT (Ω·m) | MS (SI×1e-5) | Hydro Role     |
|:--:|--------------|:--------:|:---------:|:------------:|----------------|
| 1  | Gravel       | 10–30    | 80–300    | 5–25         | High-K aquifer |
| 2  | Sand         | 25–55    | 50–150    | 10–40        | Aquifer        |
| 3  | Silty Sand   | 45–75    | 25–80     | 25–55        | Leaky aquitard |
| 4  | Till         | 70–120   | 15–50     | 80–160       | Aquitard       |
| 5  | Clay         | 90–140   | 5–25      | 30–70        | Aquiclude      |
| 6  | Peat         | 10–35    | 5–20      | 3–18         | Marker horizon |
| 7  | Ice Wedge    | 15–40    | 70–200    | 10–30        | Periglacial    |
| 8  | Cryoturbate  | 40–100   | 20–70     | 40–120       | Periglacial    |
| 9  | Dropstone    | 15–50    | 100–350   | 30–90        | Periglacial    |

### Periglacial Features (Permafrost Zone: y > 3000 m)
- **Eiskeil (ice-wedge casts)**: Vertical gravel/sand-filled fractures 1–3 m
  deep in U2/U4 till.  GR lows + RT/COND spikes in uniform till.
  ~30% of permafrost-zone wells.
- **Cryoturbation (Kryoturbation)**: Frost-heave mixing in the active layer
  (uppermost 1–3 m).  Erratic GR/RT fluctuations.  ~25% of permafrost wells.
- **Dropstones (Geschiebe)**: Isolated erratics in clay/silt producing
  single-sample GR lows and RT/SPT spikes.  ~15% of wells with fine sediment.
- **Frost cracks (Frostspalten)**: Small vertical sand-filled fractures
  (~0.3–1 m), subtler than Eiskeil.  ~20% of permafrost wells.

### Well Logs
| Log  | Description                           | Unit            |
|------|---------------------------------------|-----------------|
| GR   | Natural gamma ray                     | API             |
| RT   | Resistivity                           | Ω·m             |
| SPT  | Standard Penetration Test             | blows/30 cm     |
| COND | Hydraulic conductivity (est.)         | m/s             |
| MS   | Magnetic susceptibility               | SI × 10⁻⁵       |
| WC   | Water content                         | % by weight     |

### Geological Features
- **Morainic ridge** (x=2000–3500, y=1500–4000): till-dominated U2
- **Outwash plain** (outside moraine zone): sand/gravel-dominated U2
- **Eemian missing** in ~30% of wells (eroded on topographic highs)
- **Buried tunnel valley** (NW–SE axis): thick gravel fill in U5
- **Sand channels** within till (20% of moraine wells)
- **Peat marker beds** at Holocene/Weichselian and within Eemian
- **Per-well GR calibration shift** (±5 API) for realism

### Recommended WeCo Parameters
See `options.txt` — optimised for this dataset.

### Facies Groups for `remap_facies_groups()`
Aquifer: 1,2,7,9 | Leaky: 3,8 | Aquitard: 4,5,6
Spec string: `"1,2,7;3,8,9;4,5,6"`

### Generation
- Wells: 100
- Seed: 2026
- Grid: 10×10 at 500 m nominal spacing
- Sample spacing: 0.5 m
- Generator: `data/data_set_quaternary/generate_quaternary.py`
