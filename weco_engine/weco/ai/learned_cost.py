"""
weco.ai.learned_cost — Machine-learning cost function (§6.2)
=============================================================

Train a cost function from expert-labelled correlation panels.
The model learns to predict whether a marker tie is "correct" based
on log-curve features, then produces a cost value from the predicted
probability.

Usage::

    from weco.ai.learned_cost import LearnedCostModel

    model = LearnedCostModel()
    model.fit(training_panels)
    model.save("learned_cost.pkl")

    # At correlation time:
    model = LearnedCostModel.load("learned_cost.pkl")
    cost = model.predict_cost(features_i, features_j)
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class LearnedCostModel:
    """
    Learn a DTW cost function from expert correlation picks.

    The model extracts per-marker feature vectors (log values, depths,
    well distances) and trains a classifier to distinguish correct ties
    from incorrect ones.  The cost for a candidate tie is then:

        cost = -log(P(correct | features))

    This ensures correct ties have low cost and unlikely ties have high cost.
    """

    def __init__(
        self,
        n_estimators: int = 100,
        max_depth: int = 6,
        feature_names: Optional[List[str]] = None,
    ):
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.feature_names = feature_names or [
            "log_diff", "depth_ratio", "well_distance",
            "thickness_ratio", "log_gradient_diff",
        ]
        self._model = None

    def _extract_features(
        self,
        well_a_values: np.ndarray,
        well_b_values: np.ndarray,
        marker_a: int,
        marker_b: int,
        well_distance: float = 1.0,
    ) -> np.ndarray:
        """Extract feature vector for a single marker tie."""
        va = well_a_values[marker_a]
        vb = well_b_values[marker_b]

        log_diff = abs(va - vb)
        depth_ratio = (marker_a + 1) / max(marker_b + 1, 1)
        thickness_ratio = 1.0  # placeholder — needs interval context

        # Log gradient (finite difference)
        grad_a = 0.0
        grad_b = 0.0
        if marker_a > 0:
            grad_a = well_a_values[marker_a] - well_a_values[marker_a - 1]
        if marker_b > 0:
            grad_b = well_b_values[marker_b] - well_b_values[marker_b - 1]
        grad_diff = abs(grad_a - grad_b)

        return np.array([
            log_diff,
            depth_ratio,
            well_distance,
            thickness_ratio,
            grad_diff,
        ])

    def fit(
        self,
        training_panels: List[Dict],
    ) -> "LearnedCostModel":
        """
        Train from labelled correlation panels.

        Parameters
        ----------
        training_panels : list of dict
            Each dict has:
            - ``"well_a_values"``: ndarray of log values for well A
            - ``"well_b_values"``: ndarray of log values for well B
            - ``"correct_ties"``: list of (marker_a, marker_b) correct ties
            - ``"well_distance"``: float (optional, default 1.0)

        Returns
        -------
        self
        """
        try:
            from sklearn.ensemble import GradientBoostingClassifier
        except ImportError:
            raise ImportError("scikit-learn required: pip install scikit-learn")

        X_all = []
        y_all = []

        for panel in training_panels:
            wa = panel["well_a_values"]
            wb = panel["well_b_values"]
            correct = set(map(tuple, panel["correct_ties"]))
            dist = panel.get("well_distance", 1.0)

            # Positive samples: correct ties
            for ma, mb in correct:
                feat = self._extract_features(wa, wb, ma, mb, dist)
                X_all.append(feat)
                y_all.append(1)

            # Negative samples: random incorrect ties
            rng = np.random.default_rng(42)
            n_neg = len(correct) * 3  # 3:1 negative ratio
            for _ in range(n_neg):
                ma = rng.integers(0, len(wa))
                mb = rng.integers(0, len(wb))
                if (ma, mb) not in correct:
                    feat = self._extract_features(wa, wb, ma, mb, dist)
                    X_all.append(feat)
                    y_all.append(0)

        X = np.array(X_all)
        y = np.array(y_all)

        self._model = GradientBoostingClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            random_state=42,
        )
        self._model.fit(X, y)
        logger.info(f"Trained on {len(X)} samples, accuracy={self._model.score(X, y):.3f}")

        return self

    def predict_cost(
        self,
        well_a_values: np.ndarray,
        well_b_values: np.ndarray,
        marker_a: int,
        marker_b: int,
        well_distance: float = 1.0,
    ) -> float:
        """
        Predict cost for a candidate marker tie.

        Returns ``-log(P(correct))`` so low probability → high cost.
        """
        if self._model is None:
            raise RuntimeError("Model not trained. Call fit() first.")

        feat = self._extract_features(
            well_a_values, well_b_values, marker_a, marker_b, well_distance
        ).reshape(1, -1)
        prob = self._model.predict_proba(feat)[0, 1]
        prob = np.clip(prob, 1e-10, 1.0)
        return float(-np.log(prob))

    def save(self, path: str) -> None:
        """Save trained model to file."""
        with open(path, "wb") as f:
            pickle.dump({"model": self._model, "features": self.feature_names}, f)
        logger.info(f"Saved model to {path}")

    @classmethod
    def load(cls, path: str) -> "LearnedCostModel":
        """Load a trained model from file."""
        with open(path, "rb") as f:
            data = pickle.load(f)
        obj = cls(feature_names=data["features"])
        obj._model = data["model"]
        return obj
