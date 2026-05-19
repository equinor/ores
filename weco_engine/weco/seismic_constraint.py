"""
weco.seismic_constraint — Seismic-guided correlation (§6.4)
============================================================

Tie DTW correlation to seismic horizon interpretations.  Adds a cost
term that penalises marker ties inconsistent with picked seismic
horizons at well locations.

Usage::

    from weco.seismic_constraint import SeismicConstraint
    from weco.ext import ProjectExt, CCFPartExt

    sc = SeismicConstraint(horizon_picks, well_list)
    # Register as a Python cost function
    project.add_ccf_part(sc)
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class SeismicHorizonPicks:
    """
    Container for seismic horizon picks at well locations.

    Stores TWT (two-way-time) or depth picks for named horizons at each well.

    Parameters
    ----------
    picks : dict
        ``{horizon_name: {well_name: depth_or_twt}}``
    """

    def __init__(self, picks: Dict[str, Dict[str, float]]):
        self.picks = picks

    @property
    def horizon_names(self) -> List[str]:
        return list(self.picks.keys())

    def get_pick(self, horizon: str, well: str) -> Optional[float]:
        return self.picks.get(horizon, {}).get(well)

    def wells_for_horizon(self, horizon: str) -> List[str]:
        return list(self.picks.get(horizon, {}).keys())

    @classmethod
    def from_csv(cls, path: str) -> "SeismicHorizonPicks":
        """
        Load picks from CSV: ``horizon,well,depth``.
        """
        import csv

        picks: Dict[str, Dict[str, float]] = {}
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                h = row["horizon"].strip()
                w = row["well"].strip()
                d = float(row["depth"])
                picks.setdefault(h, {})[w] = d
        return cls(picks)


class SeismicConstraint:
    """
    DTW cost penalty for violating seismic horizon constraints.

    For each horizon pick, if the correlated marker depth at a well
    deviates from the seismic pick by more than ``tolerance``, a
    penalty is added:

        cost += weight × ((depth - pick) / sigma)²

    This softly ties the correlation to seismic interpretations while
    still allowing the DTW to find the optimal overall solution.
    """

    def __init__(
        self,
        horizon_picks: SeismicHorizonPicks,
        weight: float = 1.0,
        sigma: float = 5.0,
        tolerance: float = 0.0,
    ):
        self.horizon_picks = horizon_picks
        self.weight = weight
        self.sigma = sigma
        self.tolerance = tolerance

    def compute_penalty(
        self,
        well_name: str,
        marker_depth: float,
    ) -> float:
        """
        Compute seismic-consistency penalty for a marker at given depth.

        Checks all horizons and returns the minimum penalty (assumes the
        marker should match the closest horizon).
        """
        min_penalty = 0.0
        best_match = False

        for horizon in self.horizon_picks.horizon_names:
            pick = self.horizon_picks.get_pick(horizon, well_name)
            if pick is None:
                continue

            deviation = abs(marker_depth - pick)
            if deviation <= self.tolerance:
                return 0.0  # within tolerance of a pick

            penalty = self.weight * ((deviation - self.tolerance) / self.sigma) ** 2
            if not best_match or penalty < min_penalty:
                min_penalty = penalty
                best_match = True

        return min_penalty if best_match else 0.0

    def build_cost_matrix_modifier(
        self,
        well_a_name: str,
        well_b_name: str,
        depths_a: np.ndarray,
        depths_b: np.ndarray,
    ) -> np.ndarray:
        """
        Build an additive cost matrix for seismic horizon constraints.

        Parameters
        ----------
        well_a_name, well_b_name : str
            Well identifiers.
        depths_a, depths_b : ndarray
            Marker depths for each well.

        Returns
        -------
        ndarray, shape (n_a, n_b)
            Penalty to add to the base cost matrix.
        """
        n_a, n_b = len(depths_a), len(depths_b)
        penalty = np.zeros((n_a, n_b), dtype=np.float64)

        for i in range(n_a):
            pa = self.compute_penalty(well_a_name, depths_a[i])
            for j in range(n_b):
                pb = self.compute_penalty(well_b_name, depths_b[j])
                penalty[i, j] = pa + pb

        return penalty


def create_seismic_cost_function(
    horizon_csv: str,
    weight: float = 1.0,
    sigma: float = 5.0,
) -> SeismicConstraint:
    """
    Factory: create a SeismicConstraint from a CSV file.

    CSV format: ``horizon,well,depth``
    """
    picks = SeismicHorizonPicks.from_csv(horizon_csv)
    logger.info(f"Loaded {len(picks.horizon_names)} seismic horizons from {horizon_csv}")
    return SeismicConstraint(picks, weight=weight, sigma=sigma)
