# Coal Basin Dataset
## Synthetic coal exploration borehole panel for seam correlation

### Geological Setting
Intracratonic coal basin (Carboniferous/Permian or Cenozoic).
Modelled on the Ruhr Basin (Germany) / Upper Silesian Basin / Bowen Basin.
Cyclic coal-bearing sequences (cyclothems) with 6 named seams.

### Cyclothem Model (top → bottom of each cycle)
| Element       | Typical Thickness | Diagnostic Log Response         |
|---------------|------------------:|---------------------------------|
| Roof shale    | 1–8 m             | GR high (110 API), RT low       |
| Marine band   | 0.2–0.8 m         | GR very high (130), DEN high    |
| **Coal seam** | **0.3–5 m**       | **GR 20, RT 500+, DEN 1.3**    |
| Tonstein      | 2–15 cm           | GR 140, RT 8  (within coal)     |
| Seat earth    | 0.3–2 m           | GR 65, rootlet bed (paleosol)   |
| Sandstone     | 0.5–15 m          | GR 35, RT 80, DEN 2.35         |
| Siltstone     | 2–10 m            | GR 72, RT 40                    |

### Named Seams
| Seam        | Base Thickness | Persistence | Notable Feature              |
|-------------|---------------:|:-----------:|------------------------------|
| Katharina   | 3.0 m          | 100%        | Thick, persistent, Tonstein  |
| Sonnenschein| 1.5 m          | 90%         | Often with marine band above |
| Präsident   | 2.5 m          | 95%         | Frequent splitting           |
| Zollverein  | 1.8 m          | 85%         | Moderate, reliable           |
| Flöz 9      | 1.2 m          | 80%         | Thinner, less reliable       |
| Flöz 10     | 0.8 m          | 70%         | Near economic threshold      |

### Lithology Scheme
| ID | Name           | GR (API) | RT (Ω·m) | DEN (g/cc) | SON (µs/ft) |
|:--:|----------------|:--------:|:---------:|:----------:|:-----------:|
|  1 | Coal           | 12–28    | 300–700+  | 1.2–1.4    | 105–135     |
|  2 | Tonstein       | 120–160  | 5–11      | 2.55–2.65  | 70–90       |
|  3 | Seat Earth     | 53–77    | 15–35     | 2.32–2.48  | 65–85       |
|  4 | Sandstone      | 25–45    | 55–105    | 2.29–2.41  | 50–66       |
|  5 | Siltstone      | 60–84    | 25–55     | 2.50–2.60  | 70–86       |
|  6 | Shale          | 95–125   | 5–15      | 2.54–2.66  | 80–100      |
|  7 | Mudstone       | 83–107   | 9–21      | 2.50–2.60  | 77–93       |
|  8 | Marine Band    | 112–148  | 8–16      | 2.61–2.69  | 85–105      |
|  9 | Brandschiefer  | 60–100   | 90–210    | 2.10–2.30  | 58–82       |
| 10 | Ironstone      | 35–55    | 60–140    | 3.35–3.65  | 47–63       |

### Geological Features
- **Seam splitting**: Thick seams split into upper/lower splits with dirt parting
- **Washout zones**: Fluvial channels locally erode and replace seams
- **Tonstein (volcanic ash)**: Isochronous marker within coal — best correlation tool
- **Marine bands (Goniatitenschicht)**: Basin-wide shale markers above major seams
- **Brandschiefer (burnt shale)**: Thermally altered roof from ancient seam fires
- **Ironstone nodules (Toneisenstein)**: Siderite concretions in roof shale
- **Rider seams**: Thin coal stringers above/below main seam
- **Rootlet beds (Wurzelboden)**: Seat earths with in-situ root traces

### Well Logs
| Log  | Description              | Unit    | Key Coal Response    |
|------|--------------------------|---------|----------------------|
| GR   | Natural gamma ray        | API     | Very low (20)        |
| RT   | Resistivity              | Ω·m     | Very high (500+)     |
| DEN  | Bulk density             | g/cc    | Very low (1.3)       |
| CAL  | Caliper                  | inches  | Washout (9–12)       |
| SON  | Sonic slowness           | µs/ft   | Very high (120)      |
| NEU  | Neutron porosity         | %       | Very high (55)       |

### Recommended WeCo Parameters
See `options_coal.txt` — optimised for multi-log seam correlation.

### Correlation Strategy
1. **Primary indicator**: DEN (bulk density) — coal at 1.3 g/cc is uniquely low
2. **Secondary**: GR — coal has very low radioactivity
3. **Supporting**: SON, RT — coal shows extreme values in both
4. **QC**: CAL — coal washout confirms seam identification
5. **Constraint**: SEAM region with `same-region` — if seam IDs are available

### Generation
- Wells: 30 (6×5 grid with jitter)
- Seed: 2026
- Sample spacing: 0.2 m (fine resolution for thin seams)
- Generator: `data/data_set_coal/generate_coal.py`
