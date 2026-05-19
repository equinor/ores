# WeCo Validation Report — Truth Recovery at Scale

## Overview

This document summarises WeCo's truth-recovery performance across
synthetic geological models with known ground-truth correlations.

## Test Framework

The validation uses `weco.roundtrip` generators that produce wells with
embedded ground-truth marker positions:

| Generator | Description | Difficulty |
|-----------|-------------|------------|
| `generate_parallel` | Horizontal layers, uniform | Easy |
| `generate_clinoform` | Wedge/progradation shift | Medium |
| `generate_prograding_delta` | Parasequence shingling | Medium-Hard |
| `generate_shallow_marine` | Hugin Fm analogue, 8 facies | Hard |
| `generate_fluvial` | Laterally discontinuous channels | Very Hard |

Each generator is tested with noise injection at 0%, 5%, 10%, and 20%
levels.  The correlation is run with `k=10` n-best paths and the
ground-truth ranking is recorded.

## Key Metrics

- **Truth Rank**: Position of ground truth in n-best list (0 = best)
- **Marker MAE**: Mean absolute error of marker positions (samples)
- **Recovery Rate**: Fraction of tests where truth appears in top-5

## Expected Results

| Model | 0% Noise | 5% Noise | 10% Noise | 20% Noise |
|-------|----------|----------|-----------|-----------|
| Parallel | Rank 0 | Rank 0 | Rank 0-1 | Rank 0-3 |
| Clinoform | Rank 0 | Rank 0-1 | Rank 0-3 | Rank 1-5 |
| Delta | Rank 0-1 | Rank 0-2 | Rank 1-5 | Variable |
| Shallow Marine | Rank 0-2 | Rank 0-3 | Rank 1-5 | Variable |
| Fluvial | Rank 0-3 | Variable | Variable | Often >5 |

## Running the Tests

```bash
# Quick test
pytest pytest/test_truth.py::TestRoundtripGenerators -v

# Full validation notebook
jupyter notebook doc/validation_report.ipynb
```

## Interpretation

The **fluvial** model represents the hardest scenario because
sandbodies are laterally discontinuous and the DTW assumption of
monotonic depth correspondence is strained.  For operational use:

1. Use `generate_parallel` / `generate_clinoform` tests as regression checks
2. Use `generate_shallow_marine` as the primary validation target
3. Use `generate_fluvial` as a stress test — expect degraded performance

## References

- Baville (2022) — Graph-DTW validation methodology
- `pytest/test_truth.py::TestRoundtripGenerators` — Automated tests
- `doc/validation_report.ipynb` — Interactive visualisation
