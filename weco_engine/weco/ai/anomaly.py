"""
weco.ai.anomaly — Anomaly detection for correlation results
=============================================================

Automatically flag **suspicious correlation lines** that may need
expert review: unusually high cost, large depth jumps, poor log
similarity, or statistically outlier feature vectors.

Uses an Isolation Forest on a feature vector extracted from each
correlation line.

Typical usage::

    from weco.ai.anomaly import CorrelationAnomalyDetector

    detector = CorrelationAnomalyDetector()
    report = detector.flag_anomalies(res_file, well_list)
    for entry in report:
        if entry["anomaly"]:
            print(f"Correlation {entry['index']} flagged — review needed")

Reference
---------
§12.8 of the WeCo todo — Isolation Forest on per-correlation features.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np


# ---------------------------------------------------------------------------
#  Feature extraction
# ---------------------------------------------------------------------------

def _extract_correlation_features(
    res_file,
    well_list,
    log_name: Optional[str] = None,
) -> np.ndarray:
    """Build a feature matrix with one row per correlation line.

    Features per correlation:
        0. cost               — total dynamic-programming cost
        1. gap_fraction        — fraction of markers that are gaps
        2. mean_depth_offset   — mean |Δdepth| between tied markers
        3. max_depth_offset    — max |Δdepth| across tied markers
        4. log_similarity      — mean absolute log difference at ties
        5. n_tied_markers      — number of non-gap tied markers
    """
    n_cor = res_file.nbr_cor()
    features = np.full((n_cor, 6), np.nan, dtype=np.float64)

    # Pre-fetch log data once
    log_data: Dict[str, np.ndarray] = {}
    if log_name is None:
        for w in well_list.wells:
            if w.data:
                log_name = next(iter(w.data))
                break
    if log_name:
        for w in well_list.wells:
            if log_name in w.data:
                log_data[w.name] = np.asarray(w.data[log_name], dtype=np.float64)

    well_names = [w.name for w in well_list.wells]

    for i in range(n_cor):
        cor = res_file.cor(i)
        if cor is None:
            continue

        # Feature 0: cost
        try:
            features[i, 0] = cor.cost
        except AttributeError:
            features[i, 0] = 0.0

        # Analyse marker ties
        depth_offsets: List[float] = []
        log_diffs: List[float] = []
        n_gaps = 0
        n_total = 0

        try:
            # cor.list is [(well_a_marker, well_b_marker), …] for each pair
            if hasattr(cor, "list") and cor.list is not None:
                for pair_list in cor.list:
                    if pair_list is None:
                        continue
                    for entry in pair_list:
                        n_total += 1
                        if entry is None or (hasattr(entry, "is_gap") and entry.is_gap):
                            n_gaps += 1
                            continue
                        try:
                            if hasattr(entry, "depth_a") and hasattr(entry, "depth_b"):
                                offset = abs(entry.depth_a - entry.depth_b)
                                depth_offsets.append(offset)
                        except (TypeError, AttributeError):
                            pass
        except (TypeError, AttributeError):
            pass

        # Feature 1: gap fraction
        features[i, 1] = n_gaps / max(n_total, 1)

        # Feature 2-3: depth offsets
        if depth_offsets:
            features[i, 2] = np.mean(depth_offsets)
            features[i, 3] = np.max(depth_offsets)
        else:
            features[i, 2] = 0.0
            features[i, 3] = 0.0

        # Feature 4: log similarity (use cost as proxy if detailed unavailable)
        if log_diffs:
            features[i, 4] = np.mean(log_diffs)
        else:
            features[i, 4] = features[i, 0]  # fallback: use cost

        # Feature 5: tied markers
        features[i, 5] = float(n_total - n_gaps)

    return features


# ═══════════════════════════════════════════════════════════════════════════
#  CorrelationAnomalyDetector
# ═══════════════════════════════════════════════════════════════════════════

class CorrelationAnomalyDetector:
    """Detect anomalous (suspicious) correlations using Isolation Forest.

    Parameters
    ----------
    contamination : float
        Expected fraction of anomalies in [0, 0.5].  ``0.1`` means
        roughly 10 % of correlations will be flagged.
    random_state : int or None
        Seed for reproducibility.
    """

    def __init__(
        self,
        contamination: float = 0.1,
        random_state: Optional[int] = 42,
    ):
        if not 0.0 < contamination < 0.5:
            raise ValueError(f"contamination must be in (0, 0.5), got {contamination}")
        self.contamination = contamination
        self.random_state = random_state
        self._model = None

    # ------------------------------------------------------------------
    #  Core API
    # ------------------------------------------------------------------

    def flag_anomalies(
        self,
        res_file,
        well_list,
        log_name: Optional[str] = None,
        n_correlations: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Flag anomalous correlations.

        Parameters
        ----------
        res_file : ResFile
            WeCo result.
        well_list : WellList
            Well data used for the run.
        log_name : str, optional
            Log channel for similarity computation.
        n_correlations : int, optional
            Limit to top-n correlations.

        Returns
        -------
        list of dict
            Each dict has:
            - ``index``: correlation index
            - ``anomaly``: True if flagged
            - ``score``: anomaly score (more negative = more anomalous)
            - ``features``: dict of feature values
        """
        try:
            from sklearn.ensemble import IsolationForest
        except ImportError as exc:
            raise ImportError(
                "scikit-learn is required for anomaly detection.  "
                "Install with:  pip install weco[ai]"
            ) from exc

        features = _extract_correlation_features(res_file, well_list, log_name)

        if n_correlations is not None:
            features = features[:n_correlations]

        n = len(features)
        if n < 2:
            return [{"index": 0, "anomaly": False, "score": 0.0, "features": {}}] if n == 1 else []

        # Impute NaN with column medians
        col_medians = np.nanmedian(features, axis=0)
        for j in range(features.shape[1]):
            mask = np.isnan(features[:, j])
            features[mask, j] = col_medians[j] if not np.isnan(col_medians[j]) else 0.0

        # Fit Isolation Forest
        effective_contamination = min(self.contamination, (n - 1) / n)
        self._model = IsolationForest(
            contamination=effective_contamination,
            random_state=self.random_state,
            n_estimators=100,
        )
        labels = self._model.fit_predict(features)
        scores = self._model.decision_function(features)

        feature_names = [
            "cost", "gap_fraction", "mean_depth_offset",
            "max_depth_offset", "log_similarity", "n_tied_markers",
        ]

        report: List[Dict[str, Any]] = []
        for i in range(n):
            feat_dict = {name: float(features[i, j])
                         for j, name in enumerate(feature_names)}
            report.append({
                "index": i,
                "anomaly": bool(labels[i] == -1),
                "score": float(scores[i]),
                "features": feat_dict,
            })

        return report

    # ------------------------------------------------------------------
    #  Convenience
    # ------------------------------------------------------------------

    def anomaly_indices(
        self,
        res_file,
        well_list,
        log_name: Optional[str] = None,
    ) -> List[int]:
        """Return just the indices of flagged correlations."""
        report = self.flag_anomalies(res_file, well_list, log_name)
        return [r["index"] for r in report if r["anomaly"]]

    def summary(
        self,
        res_file,
        well_list,
        log_name: Optional[str] = None,
    ) -> str:
        """Human-readable anomaly summary."""
        report = self.flag_anomalies(res_file, well_list, log_name)
        n_anom = sum(1 for r in report if r["anomaly"])
        lines = [
            f"Anomaly report: {n_anom}/{len(report)} correlations flagged",
        ]
        for r in report:
            if r["anomaly"]:
                lines.append(
                    f"  Correlation {r['index']}: score={r['score']:.3f}  "
                    f"cost={r['features'].get('cost', '?'):.3f}  "
                    f"gaps={r['features'].get('gap_fraction', 0):.1%}"
                )
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
#  Statistical anomaly detection (no sklearn required)
# ═══════════════════════════════════════════════════════════════════════════

class StatisticalAnomalyDetector:
    """Simple z-score-based anomaly detection (no sklearn dependency).

    Flags correlations where any feature is more than ``threshold``
    standard deviations from the mean.

    Parameters
    ----------
    threshold : float
        Number of standard deviations beyond which a feature is
        considered anomalous.  Default: 2.5.
    """

    def __init__(self, threshold: float = 2.5):
        self.threshold = threshold

    def flag_anomalies(
        self,
        res_file,
        well_list,
        log_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Flag correlations with outlier features.

        Returns the same format as
        :meth:`CorrelationAnomalyDetector.flag_anomalies`.
        """
        features = _extract_correlation_features(res_file, well_list, log_name)
        n = len(features)

        if n < 2:
            return [{"index": 0, "anomaly": False, "score": 0.0, "features": {}}] if n == 1 else []

        # Impute NaN
        col_medians = np.nanmedian(features, axis=0)
        for j in range(features.shape[1]):
            mask = np.isnan(features[:, j])
            features[mask, j] = col_medians[j] if not np.isnan(col_medians[j]) else 0.0

        means = features.mean(axis=0)
        stds = features.std(axis=0) + 1e-10

        z_scores = np.abs((features - means) / stds)
        max_z = z_scores.max(axis=1)  # worst feature per correlation

        feature_names = [
            "cost", "gap_fraction", "mean_depth_offset",
            "max_depth_offset", "log_similarity", "n_tied_markers",
        ]

        report: List[Dict[str, Any]] = []
        for i in range(n):
            feat_dict = {name: float(features[i, j])
                         for j, name in enumerate(feature_names)}
            report.append({
                "index": i,
                "anomaly": bool(max_z[i] > self.threshold),
                "score": float(-max_z[i]),  # negative = more anomalous
                "features": feat_dict,
            })
        return report
