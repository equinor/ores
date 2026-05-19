"""
weco.ai.quality — Correlation quality scoring
===============================================

Assign a composite quality score to each correlation line based on
multiple geological and statistical criteria.

Usage::

    from weco.ai.quality import CorrelationQuality

    scorer = CorrelationQuality()
    scores = scorer.score_correlations(res_file, well_list)
    # scores: list of dicts with per-correlation metrics
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np


class CorrelationQuality:
    """
    Multi-criteria quality scorer for WeCo correlation results.

    Criteria
    --------
    1. **Cost** — Lower total cost → higher quality (from engine).
    2. **Gap fraction** — Fewer gaps in the correlation → higher quality.
    3. **Log similarity** — High similarity at tied markers → higher quality.
    4. **Marker density** — More tied markers → higher quality.
    5. **Geometric plausibility** — Sub-horizontal correlation lines → higher.
    """

    def __init__(
        self,
        weight_cost: float = 0.30,
        weight_gaps: float = 0.20,
        weight_similarity: float = 0.25,
        weight_density: float = 0.15,
        weight_geometry: float = 0.10,
    ):
        self.weights = {
            "cost": weight_cost,
            "gaps": weight_gaps,
            "similarity": weight_similarity,
            "density": weight_density,
            "geometry": weight_geometry,
        }

    def score_correlations(
        self,
        res_file,
        well_list,
        log_name: Optional[str] = None,
        n_correlations: Optional[int] = None,
    ) -> List[Dict]:
        """
        Score each correlation in the result file.

        Parameters
        ----------
        res_file : ResFile
        well_list : WellList
        log_name : str, optional
            Log to use for similarity scoring. If None, uses the first
            available data channel.
        n_correlations : int, optional
            Number of top correlations to score.  None → all.

        Returns
        -------
        list of dict
            Each dict has keys: ``index``, ``cost``, ``gap_fraction``,
            ``similarity``, ``density``, ``geometry``, ``total``.
        """
        n = n_correlations or res_file.nbr_cor()
        n = min(n, res_file.nbr_cor())

        # Find a log to use for similarity
        if log_name is None:
            for w in well_list.wells:
                if w.data:
                    log_name = next(iter(w.data))
                    break

        # Get cost range for normalisation
        costs = []
        for i in range(n):
            try:
                costs.append(res_file.cor(i).cost)
            except (AttributeError, IndexError):
                costs.append(float("nan"))
        costs = np.array(costs)
        cost_range = np.nanmax(costs) - np.nanmin(costs)
        if cost_range < 1e-30:
            cost_range = 1.0

        results = []
        for i in range(n):
            try:
                cor = res_file.cor(i)
            except (IndexError, AttributeError):
                continue

            record = {"index": i, "cost": float(costs[i])}

            # Normalised cost score (lower cost = higher score)
            cost_score = 1.0 - (costs[i] - np.nanmin(costs)) / cost_range

            # Gap fraction
            gap_frac = self._gap_fraction(cor, well_list)
            gap_score = 1.0 - gap_frac

            # Log similarity at tied markers
            sim_score = self._log_similarity(cor, well_list, log_name)

            # Marker density (fraction of markers that are tied)
            dens_score = self._density(cor, well_list)

            # Geometric plausibility
            geom_score = self._geometry(cor, well_list)

            total = (
                self.weights["cost"] * cost_score
                + self.weights["gaps"] * gap_score
                + self.weights["similarity"] * sim_score
                + self.weights["density"] * dens_score
                + self.weights["geometry"] * geom_score
            )

            record.update({
                "gap_fraction": round(gap_frac, 4),
                "similarity": round(sim_score, 4),
                "density": round(dens_score, 4),
                "geometry": round(geom_score, 4),
                "total": round(total, 4),
            })
            results.append(record)

        return results

    # ------------------------------------------------------------------
    #  Sub-scores
    # ------------------------------------------------------------------

    @staticmethod
    def _gap_fraction(cor, well_list) -> float:
        """Fraction of correlation steps that are gaps (same-marker jumps)."""
        try:
            total = 0
            gaps = 0
            nw = len(well_list.wells)
            for wi in range(nw):
                markers = cor.get_well_markers(wi)
                for j in range(1, len(markers)):
                    total += 1
                    if markers[j] == markers[j - 1]:
                        gaps += 1
            return gaps / max(total, 1)
        except (AttributeError, IndexError):
            return 0.5

    @staticmethod
    def _log_similarity(cor, well_list, log_name) -> float:
        """Average log-value similarity at tied markers between adjacent wells."""
        if not log_name:
            return 0.5

        try:
            nw = len(well_list.wells)
            similarities = []
            for wi in range(nw - 1):
                w1 = well_list.wells[wi]
                w2 = well_list.wells[wi + 1]
                if log_name not in w1.data or log_name not in w2.data:
                    continue
                d1 = np.asarray(w1.data[log_name], dtype=np.float64)
                d2 = np.asarray(w2.data[log_name], dtype=np.float64)
                m1 = cor.get_well_markers(wi)
                m2 = cor.get_well_markers(wi + 1)
                n = min(len(m1), len(m2))
                if n == 0:
                    continue
                vals1 = d1[np.clip(m1[:n], 0, len(d1) - 1)]
                vals2 = d2[np.clip(m2[:n], 0, len(d2) - 1)]
                # Normalised similarity (1 - normalised MAE)
                rng = max(np.ptp(d1), np.ptp(d2), 1e-10)
                mae = np.mean(np.abs(vals1 - vals2)) / rng
                similarities.append(max(0, 1.0 - mae))
            return float(np.mean(similarities)) if similarities else 0.5
        except (AttributeError, IndexError):
            return 0.5

    @staticmethod
    def _density(cor, well_list) -> float:
        """Fraction of total markers that participate in a tie."""
        try:
            total_markers = sum(w.size for w in well_list.wells)
            tied = 0
            for wi in range(len(well_list.wells)):
                markers = cor.get_well_markers(wi)
                tied += len(set(markers))
            return tied / max(total_markers, 1)
        except (AttributeError, IndexError):
            return 0.5

    @staticmethod
    def _geometry(cor, well_list) -> float:
        """
        Penalise large vertical jumps in correlation lines.
        
        A perfectly horizontal correlation (in fractional depth) scores 1.0.
        Large dip → lower score.
        """
        try:
            nw = len(well_list.wells)
            if nw < 2:
                return 1.0
            penalties = []
            for wi in range(nw - 1):
                w1 = well_list.wells[wi]
                w2 = well_list.wells[wi + 1]
                m1 = np.array(cor.get_well_markers(wi), dtype=float)
                m2 = np.array(cor.get_well_markers(wi + 1), dtype=float)
                if len(m1) == 0:
                    continue
                # Normalise to fractional depth [0, 1]
                f1 = m1 / max(w1.size - 1, 1)
                f2 = m2 / max(w2.size - 1, 1)
                n = min(len(f1), len(f2))
                dip = np.abs(f1[:n] - f2[:n])
                penalties.append(np.mean(dip))
            if not penalties:
                return 1.0
            avg_dip = np.mean(penalties)
            # Score: 1.0 at dip=0, decays toward 0
            return float(np.exp(-3.0 * avg_dip))
        except (AttributeError, IndexError):
            return 0.5
