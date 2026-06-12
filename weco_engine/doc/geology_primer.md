# WeCo Geology Primer

> **What is well correlation and how does WeCo solve it?**
>
> A beginner-friendly introduction for users who are new to
> stratigraphic well correlation, graph-DTW, and cost functions.

> **Origin & License:**
> The WeCo correlation engine originates from the
> [RING team](https://www.ring-team.org/) at Université de Lorraine /
> ASGA (Association Scientifique pour la Géologie et ses Applications).
> The core graph-DTW algorithm is based on research by Baville, Lallier,
> Edwards, Caumon, and Julio at the RING laboratory.
> See [license.txt](license.txt) for the original ASGA/RING license terms.

---

## What is Well Correlation?

**Well correlation** is the process of connecting equivalent
stratigraphic horizons between wells.  When you drill multiple wells
through sedimentary rock, you see similar layers - but they don't
line up perfectly because:

- Layers **thicken and thin** laterally
- Some layers **pinch out** (disappear) between wells
- **Erosion** removes parts of the section
- **Facies change** laterally (sand becomes shale towards the basin)

A correlation connects the "same" layer across wells, producing a
**stratigraphic framework** used for geological modelling.

```
Well A        Well B        Well C
───┬───       ───┬───       ───┬───
   │ Sand        │ Sand        │ Silt   ← Same horizon (correlated)
───┼───       ───┼───       ───┼───
   │ Shale       │ Shale       │ Shale  ← Same horizon
───┼───       ───┼───       ───┼───
   │ Sand        │ Silt        │ Shale  ← Facies change!
───┴───       ───┴───       ───┴───
```

## What is DTW (Dynamic Time Warping)?

**Dynamic Time Warping** is an algorithm that finds the optimal
alignment between two sequences.  Originally from speech recognition,
it naturally handles stretching and compression - exactly what
happens to geological layers.

In WeCo's context:
- Each well is a **sequence** of markers (depth samples)
- Each marker has **data** (log values: GR, density, porosity, ...)
- DTW finds the alignment that **minimises the total cost**

```
Well A markers:  a₁  a₂  a₃  a₄  a₅  a₆
                   \  |  / \  |    |
                    ↘ ↓ ↙   ↘ ↓    ↓
Well B markers:  b₁  b₂  b₃  b₄  b₅
```

The alignment can be one-to-one, one-to-many (stretching), or skip
markers entirely (gaps = missing layers).

## What is the Cost Function?

The **cost function** measures how "expensive" it is to correlate
two markers.  Lower cost = better match.  WeCo uses a **composite
cost function** that combines multiple geological criteria:

### Variance Cost (`var-data`, `var-weight`)
Penalises correlating markers with **different log values**.
If marker A has GR=30 (sand) and marker B has GR=120 (shale),
the cost is high - they probably aren't the same layer.

$$c_{\text{var}} = \text{Var}(v_1, v_2, \ldots, v_n)$$

### Gap Cost (`gap-const-cost`, `gap-func-cost`)
Penalises **skipping** markers (gaps).  A gap means "this marker
in well A has no equivalent in well B" - it represents a missing
or eroded layer.  Some gaps are geologically expected; too many
suggest a bad correlation.

### Same Region Cost (`same-region`)
Penalises correlating markers from **different zones**.  If
biostratigraphy says marker A is in zone "Early Jurassic" and
marker B is in "Late Jurassic", they should not be correlated.

### No Crossing (`no-crossing`)
A **hard constraint**: correlation lines cannot cross certain
boundaries.  Used for biozones, sequence boundaries, or other
surfaces that are known to be time-equivalent.

### Distality Cost (`dist-on`)
For lateral facies changes: penalises correlations that are
inconsistent with the **depositional environment**.  If well A
is proximal (near shore) and well B is distal (basin), their
facies should change systematically - not randomly.

### B3D Cost (Bézier 3D)
Penalises correlations that create **geologically implausible
geometries** (e.g., very steep dips, reversals).

## What is k-Best?

WeCo doesn't just find the **single best** correlation - it finds
the **k best** correlations (controlled by `nbr-cor` and
`out-nbr-cor`).  This is crucial because:

1. The "best" correlation may not be geologically correct
2. Multiple valid interpretations exist (uncertainty!)
3. You want to explore alternative scenarios

The k-best results are ranked by total cost.  The ground truth
should ideally appear as one of the top-ranked results.

## What Affects Correlation Quality?

| Factor | Impact | Control |
|--------|--------|---------|
| **Log quality** | Noisy logs → noisy correlation | Preprocessing (smoothing, QC) |
| **Cost weights** | Wrong weights → wrong priorities | `var-weight`, `gap-const-cost` |
| **Constraints** | Too few → noise; too many → over-constrained | `same-region`, `no-crossing` |
| **Well order** | Different merge order → different results | `order` option, sensitivity analysis |
| **k value** | Too low → miss the truth; too high → slow | `nbr-cor`, `max-cor` |

## WeCo Workflow

```
1. Load wells          ← Data page
2. Condition data      ← Preprocessing (Vshale, normalise, electrofacies)
3. Configure costs     ← Parameters page
4. Run engine          ← Run page
5. View results        ← Results page (correlation viewer)
6. Export              ← Zonation, picks, surfaces → GOCAD / RESQML / RMS
```

## Further Reading

- Baville (2022) *"Stochastic stratigraphic correlation using
  graph-DTW"* - PhD thesis, the theoretical foundation of WeCo
- Lallier et al. (2013) *"Uncertainty of well correlation"*
  - DTW applied to well correlation
- Catuneanu (2006) *"Principles of Sequence Stratigraphy"*
  - geological background for hierarchical correlation
