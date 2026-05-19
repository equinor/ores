"""
weco.ai — AI-enhanced preprocessing and postprocessing for WeCo
================================================================

This package provides machine-learning methods that wrap around the
deterministic WeCo correlation engine:

* **Preprocessing** — prepare better inputs (log QC, facies prediction)
* **Postprocessing** — interpret and validate outputs (uncertainty, quality)

The core engine remains unchanged; AI methods are strictly supplementary.

Modules
-------
log_qc
    Washout detection, missing-value imputation, cross-well normalisation.
facies_predict
    GBM-based facies prediction from well logs.
uncertainty
    N-best ensemble uncertainty, Monte Carlo perturbation.
quality
    Correlation quality scoring from multiple criteria.
anomaly
    Isolation-Forest anomaly detection for correlation results.
auto_tune
    Bayesian / differential-evolution parameter optimisation.

Optional dependencies
---------------------
- ``scikit-learn`` (required for most methods)
- ``scipy`` (required for auto-tuning)

Install with::

    pip install weco[ai]
"""

__all__ = [
    "log_qc",
    "facies_predict",
    "uncertainty",
    "quality",
    "anomaly",
    "auto_tune",
]
