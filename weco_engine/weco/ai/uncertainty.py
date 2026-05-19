"""
weco.ai.uncertainty — Correlation uncertainty quantification
=============================================================

Estimate confidence / uncertainty for every correlation line by
analysing the spread of WeCo's n-best solutions or via Monte-Carlo
parameter perturbation.

Typical usage::

    from weco.ai.uncertainty import CorrelationUncertainty

    cu = CorrelationUncertainty()

    # After running WeCo with max_cor >= 10:
    unc = cu.from_n_best(res_file, n_paths=10)
    # unc is a dict: (well_i, well_j) -> ndarray of per-marker std
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np


class CorrelationUncertainty:
    """
    Quantify correlation uncertainty from multiple solution paths.

    WeCo can return the *n*-best correlation paths (controlled by
    ``max_cor``).  The spread of marker assignments across these paths
    is a natural measure of local confidence:

    * **Low spread** → engine is confident about the marker tie.
    * **High spread** → multiple plausible ties exist; expert judgement needed.
    """

    @staticmethod
    def from_n_best(
        res_file,
        n_paths: Optional[int] = None,
    ) -> Dict[Tuple[str, str], np.ndarray]:
        """
        Compute per-marker uncertainty from n-best correlation paths.

        Parameters
        ----------
        res_file : ResFile
            Result file from a WeCo run (must contain multiple correlations).
        n_paths : int, optional
            Number of top paths to consider. None → use all available.

        Returns
        -------
        dict
            Mapping ``(well_A, well_B) -> ndarray`` of per-marker standard
            deviation of the correlated position across the n-best paths.
        """
        uncertainty = {}

        n = n_paths or res_file.nbr_cor()
        n = min(n, res_file.nbr_cor())

        if n <= 1:
            return uncertainty

        # res_file.well_pairs is a list of (w1_name, w2_name)
        # res_file.get_correlation(i) returns the i-th best correlation
        # Each correlation has .markers: dict[well_name -> list[int]]

        try:
            well_names = [w.name for w in res_file.well_list.wells]
        except AttributeError:
            well_names = res_file.well_names if hasattr(res_file, 'well_names') else []

        if len(well_names) < 2:
            return uncertainty

        # Collect all correlation-line data across n-best
        # ResFile stores correlations as ordered lists of marker ties
        for cor_idx in range(n):
            try:
                cor = res_file.cor(cor_idx)
            except (IndexError, AttributeError):
                break

            if cor is None:
                continue

            nw = len(well_names)
            for wi in range(nw):
                for wj in range(wi + 1, nw):
                    key = (well_names[wi], well_names[wj])
                    if key not in uncertainty:
                        uncertainty[key] = []

                    # Extract marker pairs for this well pair from this correlation
                    try:
                        markers_i = cor.get_well_markers(wi)
                        markers_j = cor.get_well_markers(wj)
                        uncertainty[key].append(np.array(markers_j, dtype=float))
                    except (AttributeError, IndexError):
                        pass

        # Compute standard deviation across paths
        result = {}
        for key, marker_lists in uncertainty.items():
            if len(marker_lists) > 1:
                # Paths may have different lengths; pad to max length with NaN
                max_len = max(len(m) for m in marker_lists)
                padded = np.full((len(marker_lists), max_len), np.nan)
                for i, m in enumerate(marker_lists):
                    padded[i, :len(m)] = m
                result[key] = np.nanstd(padded, axis=0)
            elif len(marker_lists) == 1:
                result[key] = np.zeros_like(marker_lists[0])

        return result

    @staticmethod
    def confidence_classification(
        uncertainty: Dict[Tuple[str, str], np.ndarray],
        low_threshold: float = 0.5,
        high_threshold: float = 2.0,
    ) -> Dict[Tuple[str, str], np.ndarray]:
        """
        Classify each marker tie as high/medium/low confidence.

        Parameters
        ----------
        uncertainty : dict
            Output from :meth:`from_n_best`.
        low_threshold : float
            std < low_threshold  → high confidence (3).
        high_threshold : float
            std > high_threshold → low confidence (1).

        Returns
        -------
        dict
            Same structure, values are integer arrays:
            3 = high confidence, 2 = medium, 1 = low.
        """
        result = {}
        for key, std_arr in uncertainty.items():
            conf = np.full_like(std_arr, 2, dtype=int)  # default medium
            conf[std_arr < low_threshold] = 3   # high
            conf[std_arr > high_threshold] = 1  # low
            result[key] = conf
        return result

    @staticmethod
    def monte_carlo(
        well_list,
        base_params: dict,
        n_runs: int = 30,
        noise_sigma: float = 0.2,
        seed: int = 42,
    ) -> Dict[str, np.ndarray]:
        """
        Estimate uncertainty by running WeCo multiple times with
        perturbed cost-function weights.

        Each run applies log-normal noise to weights:
        ``perturbed = base * exp(N(0, sigma))``

        Parameters
        ----------
        well_list : WellList
            Input wells.
        base_params : dict
            Base parameter dict (e.g. ``{"var_weight": 1.0, ...}``).
        n_runs : int
            Number of Monte Carlo samples.
        noise_sigma : float
            Std of the log-normal perturbation.
        seed : int
            Random seed.

        Returns
        -------
        dict
            Mapping ``param_name -> ndarray[n_runs]`` of sampled values.
            Also key ``"costs"`` with array of total costs.

        Notes
        -----
        Requires the WeCo engine to be available.
        """
        from weco.ext import ProjectExt

        rng = np.random.default_rng(seed)
        results = {k: [] for k in base_params}
        results["costs"] = []

        weight_keys = [k for k in base_params
                       if "weight" in k or "cost" in k or "scaling" in k]

        for _ in range(n_runs):
            params = dict(base_params)
            for k in weight_keys:
                val = params[k]
                if isinstance(val, (int, float)) and val != 0:
                    params[k] = float(val) * np.exp(rng.normal(0, noise_sigma))

            proj = ProjectExt()
            proj.set_options_ext(params)
            proj.run(well_list)
            rf = proj.get_res_file()

            for k in base_params:
                results[k].append(params[k])

            # Get cost of best correlation
            try:
                results["costs"].append(rf.cor(0).cost)
            except (AttributeError, IndexError):
                results["costs"].append(float("nan"))

        for k in results:
            results[k] = np.array(results[k])

        return results

    @staticmethod
    def posterior_ensemble(
        res_file,
        n_paths: int = 50,
        temperature: float = 1.0,
    ) -> Dict[str, np.ndarray]:
        """
        Generate a posterior ensemble of correlations using Boltzmann weighting.

        Treats n-best paths as samples from a posterior distribution:
        ``p(path_i) ∝ exp(-cost_i / T)``

        Parameters
        ----------
        res_file : ResFile
            Result with multiple correlations (max_cor >= n_paths).
        n_paths : int
            Number of paths to include in the ensemble.
        temperature : float
            Boltzmann temperature — lower = sharper distribution around
            the best solution; higher = more uniform sampling.

        Returns
        -------
        dict
            ``"weights"`` — Boltzmann weights for each path (sum to 1).
            ``"costs"`` — Cost of each path.
            ``"entropy"`` — Shannon entropy of the distribution (bits).
            ``"effective_n"`` — Effective sample size ``1/Σ(w²)``.
        """
        n = min(n_paths, res_file.nbr_cor())
        if n <= 0:
            return {"weights": np.array([]), "costs": np.array([]),
                    "entropy": 0.0, "effective_n": 0.0}

        costs = np.array([res_file.cor(i).cost for i in range(n)])

        # Boltzmann weights with numerical stability
        shifted = -(costs - costs.min()) / max(temperature, 1e-12)
        exp_w = np.exp(shifted)
        weights = exp_w / exp_w.sum()

        # Shannon entropy
        nonzero = weights[weights > 0]
        entropy = -np.sum(nonzero * np.log2(nonzero))

        # Effective sample size (Kish's ESS)
        effective_n = 1.0 / np.sum(weights ** 2)

        return {
            "weights": weights,
            "costs": costs,
            "entropy": float(entropy),
            "effective_n": float(effective_n),
        }
