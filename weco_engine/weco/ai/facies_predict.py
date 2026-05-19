"""
weco.ai.facies_predict — Automated facies prediction from well logs
====================================================================

Predict sedimentary facies from raw well-log data using gradient-boosted
decision trees.  This enables the distality cost function even when no
manual facies interpretation is available.

Typical usage::

    from weco.ai.facies_predict import FaciesPredictor

    fp = FaciesPredictor(n_classes=5, window=3)

    # Train on wells that already have interpreted facies
    fp.train(interpreted_wells, log_names=["GR", "RT", "RHOB"],
             facies_name="FACIES")

    # Predict facies on un-interpreted wells
    for well in raw_wells:
        fp.predict(well, log_names=["GR", "RT", "RHOB"],
                   output_region="predicted_facies")

Reference
---------
Baville (2022) §3 — the distality cost function requires per-marker
facies.  Automated prediction removes the manual interpretation
bottleneck.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


# ---------------------------------------------------------------------------
#  Internal helpers
# ---------------------------------------------------------------------------

def _labels_to_intervals(labels: np.ndarray) -> list:
    """Convert a per-marker label array to [(id, start, length), …] region."""
    intervals: list = []
    if len(labels) == 0:
        return intervals
    start = 0
    cur = int(labels[0])
    for i in range(1, len(labels)):
        v = int(labels[i])
        if v != cur:
            intervals.append((cur, start, i - start))
            start = i
            cur = v
    intervals.append((cur, start, len(labels) - start))
    return intervals


def _region_to_array(well, region_name: str, default: float = 0.0) -> np.ndarray:
    """Expand a WeCo region to a per-marker float array."""
    if region_name not in well.region:
        raise KeyError(f"Region '{region_name}' not found in well '{well.name}'.")
    arr = np.full(well.size, default, dtype=np.float64)
    for rid, start, length in well.region[region_name]:
        arr[start:start + length] = float(rid)
    return arr


# ---------------------------------------------------------------------------
#  Feature engineering
# ---------------------------------------------------------------------------

def _featurise_single(
    well,
    log_names: List[str],
    window: int,
) -> np.ndarray:
    """Build a feature matrix for *one* well.

    For each marker *i*, the feature vector is the flattened log values
    in a symmetric window ``[i - window, i + window]``, padded at the
    edges.  This provides vertical context to the classifier.

    Shape: ``(well.size, n_logs * (2 * window + 1) + 2)``
    (the last two columns are normalised depth and marker index).
    """
    n_logs = len(log_names)
    n_markers = well.size
    win_width = 2 * window + 1
    n_features = n_logs * win_width + 2  # +2 for depth features

    logs = np.column_stack(
        [np.asarray(well.data[n], dtype=np.float64) for n in log_names]
    )  # (n_markers, n_logs)

    features = np.zeros((n_markers, n_features), dtype=np.float64)
    for i in range(n_markers):
        lo = max(0, i - window)
        hi = min(n_markers, i + window + 1)
        block = logs[lo:hi].flatten()
        # Left-align into the fixed-width slot
        features[i, :len(block)] = block

    # Normalised position features (helps capture depth trends)
    if n_markers > 1:
        features[:, -2] = np.linspace(0, 1, n_markers)
    features[:, -1] = np.arange(n_markers, dtype=np.float64) / max(n_markers - 1, 1)

    return features


# ═══════════════════════════════════════════════════════════════════════════
#  Main class
# ═══════════════════════════════════════════════════════════════════════════

class FaciesPredictor:
    """Predict facies from well logs using Gradient Boosted Trees.

    Parameters
    ----------
    n_classes : int
        Expected number of distinct facies classes (informational;
        the actual number is determined from training data).
    window : int
        Half-width of the vertical context window (in markers).
        A window of 3 means each feature vector contains
        ``2*3 + 1 = 7`` markers of log values.
    n_estimators : int
        Number of boosting stages (trees).
    max_depth : int
        Maximum tree depth.
    learning_rate : float
        Shrinkage applied to each tree.
    random_state : int or None
        Seed for reproducibility.
    """

    def __init__(
        self,
        n_classes: int = 5,
        window: int = 3,
        n_estimators: int = 200,
        max_depth: int = 6,
        learning_rate: float = 0.1,
        random_state: Optional[int] = 42,
    ):
        self.n_classes = n_classes
        self.window = window
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.random_state = random_state

        self._model = None
        self._log_names: List[str] = []
        self._classes: Optional[np.ndarray] = None
        self._feature_names: List[str] = []

    # ------------------------------------------------------------------
    #  Properties
    # ------------------------------------------------------------------

    @property
    def is_trained(self) -> bool:
        """Whether the model has been fitted."""
        return self._model is not None

    @property
    def classes(self) -> Optional[np.ndarray]:
        """Unique class labels seen during training."""
        return self._classes

    # ------------------------------------------------------------------
    #  Training
    # ------------------------------------------------------------------

    def train(
        self,
        wells: Sequence,
        log_names: List[str],
        facies_name: str = "FACIES",
        facies_source: str = "region",
    ) -> "FaciesPredictor":
        """Train the classifier on wells with interpreted facies.

        Parameters
        ----------
        wells : sequence of Well
            Wells that already have interpreted facies.
        log_names : list of str
            Log names to use as predictor features (e.g. ``["GR", "RT"]``).
        facies_name : str
            Name of the facies channel on each well.
        facies_source : ``"region"`` or ``"data"``
            Whether facies are stored as a WeCo *region* or as a *data*
            channel (integer values).

        Returns
        -------
        self
        """
        try:
            from sklearn.ensemble import GradientBoostingClassifier
        except ImportError as exc:
            raise ImportError(
                "scikit-learn is required for FaciesPredictor.  "
                "Install with:  pip install weco[ai]"
            ) from exc

        self._log_names = list(log_names)

        X_all: list = []
        y_all: list = []
        skipped = 0

        for well in wells:
            # Check that all required logs exist
            missing = [n for n in log_names if n not in well.data]
            if missing:
                skipped += 1
                continue

            X = _featurise_single(well, log_names, self.window)

            if facies_source == "region":
                if facies_name not in well.region:
                    skipped += 1
                    continue
                y = _region_to_array(well, facies_name)
            else:
                if facies_name not in well.data:
                    skipped += 1
                    continue
                y = np.asarray(well.data[facies_name], dtype=np.float64)

            y = y.astype(int)
            X_all.append(X)
            y_all.append(y)

        if not X_all:
            raise ValueError(
                f"No usable training wells.  Skipped {skipped} because of "
                f"missing logs {log_names!r} or facies '{facies_name}'."
            )

        X_train = np.vstack(X_all)
        y_train = np.concatenate(y_all)

        # Remove markers with NaN features (incomplete log coverage)
        valid = ~np.isnan(X_train).any(axis=1)
        X_train = X_train[valid]
        y_train = y_train[valid]

        if len(X_train) == 0:
            raise ValueError("All training samples contain NaN — check log data.")

        self._model = GradientBoostingClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            random_state=self.random_state,
        )
        self._model.fit(X_train, y_train)
        self._classes = np.unique(y_train)
        return self

    # ------------------------------------------------------------------
    #  Prediction
    # ------------------------------------------------------------------

    def predict(
        self,
        well,
        log_names: Optional[List[str]] = None,
        output_region: str = "predicted_facies",
        output_data: Optional[str] = None,
    ) -> np.ndarray:
        """Predict facies for a single well.

        Parameters
        ----------
        well : Well
            Target well (must have the same logs used in training).
        log_names : list of str, optional
            Override log names.  If None, uses the names from training.
        output_region : str or None
            If given, store predictions as a WeCo region on the well.
        output_data : str or None
            If given, also store predictions as a data channel.

        Returns
        -------
        ndarray of int
            Per-marker predicted facies labels.
        """
        if not self.is_trained:
            raise RuntimeError("Model not trained — call .train() first.")

        names = log_names or self._log_names
        missing = [n for n in names if n not in well.data]
        if missing:
            raise KeyError(
                f"Well '{well.name}' is missing log(s): {missing}.  "
                f"Available: {sorted(well.data.keys())}"
            )

        X = _featurise_single(well, names, self.window)

        # Replace NaN with 0 for prediction robustness
        np.nan_to_num(X, copy=False)

        labels = self._model.predict(X).astype(int)

        if output_region:
            intervals = _labels_to_intervals(labels)
            well.add_region(output_region, intervals)

        if output_data:
            well.add_data(output_data, labels.tolist())

        return labels

    # ------------------------------------------------------------------
    #  Predict probabilities
    # ------------------------------------------------------------------

    def predict_proba(
        self,
        well,
        log_names: Optional[List[str]] = None,
    ) -> np.ndarray:
        """Return per-marker class probabilities.

        Parameters
        ----------
        well : Well
        log_names : list of str, optional

        Returns
        -------
        ndarray of shape (n_markers, n_classes)
        """
        if not self.is_trained:
            raise RuntimeError("Model not trained — call .train() first.")

        names = log_names or self._log_names
        X = _featurise_single(well, names, self.window)
        np.nan_to_num(X, copy=False)
        return self._model.predict_proba(X)

    # ------------------------------------------------------------------
    #  Feature importance
    # ------------------------------------------------------------------

    def feature_importance(self) -> Dict[str, float]:
        """Return per-log feature importance (summed across window positions).

        Returns
        -------
        dict
            Mapping ``log_name -> importance``.
        """
        if not self.is_trained:
            raise RuntimeError("Model not trained.")

        importances = self._model.feature_importances_
        n_logs = len(self._log_names)
        win_width = 2 * self.window + 1
        per_log = {}
        for j, name in enumerate(self._log_names):
            # Sum importances across the window positions for this log
            indices = [j + k * n_logs for k in range(win_width)
                       if j + k * n_logs < len(importances)]
            per_log[name] = float(sum(importances[i] for i in indices))

        # Normalise
        total = sum(per_log.values()) or 1.0
        return {k: v / total for k, v in per_log.items()}

    # ------------------------------------------------------------------
    #  Cross-validation accuracy
    # ------------------------------------------------------------------

    def cross_validate(
        self,
        wells: Sequence,
        log_names: List[str],
        facies_name: str = "FACIES",
        facies_source: str = "region",
        n_folds: int = 5,
    ) -> Dict[str, float]:
        """Leave-one-well-out or k-fold cross-validation.

        If ``n_folds >= len(wells)`` or ``n_folds == -1``, uses
        leave-one-well-out.

        Returns
        -------
        dict
            Keys: ``accuracy``, ``per_class_accuracy``, ``n_samples``.
        """
        try:
            from sklearn.ensemble import GradientBoostingClassifier
        except ImportError as exc:
            raise ImportError("scikit-learn required") from exc

        log_names = list(log_names)

        # Collect per-well data
        well_data: List[Tuple[np.ndarray, np.ndarray]] = []
        for well in wells:
            missing_logs = [n for n in log_names if n not in well.data]
            if missing_logs:
                continue
            X = _featurise_single(well, log_names, self.window)
            if facies_source == "region":
                if facies_name not in well.region:
                    continue
                y = _region_to_array(well, facies_name).astype(int)
            else:
                if facies_name not in well.data:
                    continue
                y = np.asarray(well.data[facies_name], dtype=int)
            valid = ~np.isnan(X).any(axis=1)
            well_data.append((X[valid], y[valid]))

        if not well_data:
            raise ValueError("No wells usable for cross-validation.")

        n_wells = len(well_data)
        use_loocv = (n_folds >= n_wells) or (n_folds == -1)

        if use_loocv:
            # Leave-one-well-out
            all_true: list = []
            all_pred: list = []
            for i in range(n_wells):
                X_train = np.vstack([well_data[j][0] for j in range(n_wells) if j != i])
                y_train = np.concatenate([well_data[j][1] for j in range(n_wells) if j != i])
                X_test, y_test = well_data[i]
                model = GradientBoostingClassifier(
                    n_estimators=self.n_estimators,
                    max_depth=self.max_depth,
                    learning_rate=self.learning_rate,
                    random_state=self.random_state,
                )
                model.fit(X_train, y_train)
                all_pred.append(model.predict(X_test))
                all_true.append(y_test)
            y_true = np.concatenate(all_true)
            y_pred = np.concatenate(all_pred)
        else:
            # K-fold across concatenated wells
            X_all = np.vstack([d[0] for d in well_data])
            y_all = np.concatenate([d[1] for d in well_data])
            from sklearn.model_selection import cross_val_predict
            model = GradientBoostingClassifier(
                n_estimators=self.n_estimators,
                max_depth=self.max_depth,
                learning_rate=self.learning_rate,
                random_state=self.random_state,
            )
            y_pred = cross_val_predict(model, X_all, y_all, cv=n_folds)
            y_true = y_all

        accuracy = float(np.mean(y_true == y_pred))
        classes = np.unique(y_true)
        per_class = {}
        for c in classes:
            mask = y_true == c
            if mask.any():
                per_class[int(c)] = float(np.mean(y_pred[mask] == c))

        return {
            "accuracy": accuracy,
            "per_class_accuracy": per_class,
            "n_samples": int(len(y_true)),
        }

    # ------------------------------------------------------------------
    #  Serialisation
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Save trained model to a file (pickle).

        Parameters
        ----------
        path : str
            File path (e.g. ``"facies_model.pkl"``).
        """
        import pickle

        state = {
            "model": self._model,
            "log_names": self._log_names,
            "window": self.window,
            "classes": self._classes,
            "n_classes": self.n_classes,
            "n_estimators": self.n_estimators,
            "max_depth": self.max_depth,
            "learning_rate": self.learning_rate,
            "random_state": self.random_state,
        }
        with open(path, "wb") as f:
            pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def load(cls, path: str) -> "FaciesPredictor":
        """Load a previously saved model.

        Parameters
        ----------
        path : str

        Returns
        -------
        FaciesPredictor
        """
        import pickle

        with open(path, "rb") as f:
            state = pickle.load(f)  # noqa: S301

        fp = cls(
            n_classes=state.get("n_classes", 5),
            window=state.get("window", 3),
            n_estimators=state.get("n_estimators", 200),
            max_depth=state.get("max_depth", 6),
            learning_rate=state.get("learning_rate", 0.1),
            random_state=state.get("random_state", 42),
        )
        fp._model = state["model"]
        fp._log_names = state["log_names"]
        fp._classes = state.get("classes")
        return fp
