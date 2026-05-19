"""
weco.ai.auto_tune — Automatic parameter tuning for WeCo
=========================================================

Optimise WeCo correlation parameters against a reference correlation
using derivative-free global optimisation (differential evolution) or
Bayesian optimisation (Gaussian process surrogate).

Typical usage::

    from weco.ai.auto_tune import AutoTuner

    tuner = AutoTuner(
        well_file="wells.txt",
        reference_file="reference_res.txt",
    )
    best_params = tuner.optimise(max_iter=50)
    # best_params: dict of optimal engine options

Reference
---------
Baville (2022) §4.5.3 — the sensitivity of correlation results to
parameter choice motivates systematic optimisation.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np


# ---------------------------------------------------------------------------
#  Default parameter search space
# ---------------------------------------------------------------------------

#: Sensible bounds for the most important engine parameters.
DEFAULT_PARAM_BOUNDS: Dict[str, Tuple[float, float]] = {
    "var-weight":    (0.0, 5.0),
    "var-weight2":   (0.0, 5.0),
    "var-weight3":   (0.0, 5.0),
}

#: Extended bounds for advanced tuning.
EXTENDED_PARAM_BOUNDS: Dict[str, Tuple[float, float]] = {
    "var-weight":    (0.0, 5.0),
    "var-weight2":   (0.0, 5.0),
    "var-weight3":   (0.0, 5.0),
    "var-weight4":   (0.0, 5.0),
    "var-weight5":   (0.0, 5.0),
}


# ═══════════════════════════════════════════════════════════════════════════
#  Misfit functions
# ═══════════════════════════════════════════════════════════════════════════

def marker_offset_misfit(result, reference) -> float:
    """Mean absolute marker-position offset between two correlation results.

    For each correlation line in *reference*, find the nearest line in
    *result* and compute the absolute depth offset of tied markers.

    Parameters
    ----------
    result : ResFile
        Correlation result from an engine run.
    reference : ResFile
        Known-good (expert) correlation result.

    Returns
    -------
    float
        Mean absolute offset (lower = better).
    """
    total_error = 0.0
    n = 0

    n_cor_ref = reference.nbr_cor()
    n_cor_res = result.nbr_cor()

    if n_cor_ref == 0 or n_cor_res == 0:
        return float("inf")

    for i_ref in range(n_cor_ref):
        cor_ref = reference.cor(i_ref)
        if cor_ref is None:
            continue

        # Find closest correlation line in result by cost-weighted index
        best_dist = float("inf")
        best_cor = None
        for i_res in range(n_cor_res):
            cor_res = result.cor(i_res)
            if cor_res is None:
                continue
            try:
                dist = abs(cor_res.cost - cor_ref.cost)
            except AttributeError:
                dist = abs(i_res - i_ref)
            if dist < best_dist:
                best_dist = dist
                best_cor = cor_res

        if best_cor is None:
            continue

        # Compare marker ties
        try:
            ref_points = cor_ref.points if hasattr(cor_ref, "points") else []
            res_points = best_cor.points if hasattr(best_cor, "points") else []
            for rp, sp in zip(ref_points, res_points):
                total_error += abs(rp - sp)
                n += 1
        except (TypeError, AttributeError):
            # Fallback: compare cost as proxy
            try:
                total_error += abs(best_cor.cost - cor_ref.cost)
                n += 1
            except AttributeError:
                pass

    return total_error / max(n, 1)


def cost_misfit(result, reference) -> float:
    """Relative difference in total correlation cost.

    Useful when marker-level comparison is not possible.
    """
    try:
        c_res = sum(result.cor(i).cost for i in range(result.nbr_cor()))
        c_ref = sum(reference.cor(i).cost for i in range(reference.nbr_cor()))
    except (AttributeError, TypeError):
        return float("inf")

    denom = abs(c_ref) + 1e-10
    return abs(c_res - c_ref) / denom


# ═══════════════════════════════════════════════════════════════════════════
#  AutoTuner
# ═══════════════════════════════════════════════════════════════════════════

class AutoTuner:
    """Automatic WeCo parameter optimisation.

    Parameters
    ----------
    well_file : str or WellList
        Path to well data file, or a loaded WellList.
    reference_file : str or ResFile
        Path to a reference result file, or a loaded ResFile.
    param_bounds : dict, optional
        ``{param_name: (lo, hi), …}``.  Defaults to :data:`DEFAULT_PARAM_BOUNDS`.
    base_options : dict, optional
        Fixed engine options that should not be varied.
    misfit_fn : callable, optional
        ``misfit_fn(result, reference) -> float``.  Default:
        :func:`marker_offset_misfit`.
    """

    def __init__(
        self,
        well_file: Union[str, Any] = None,
        reference_file: Union[str, Any] = None,
        *,
        well_list: Any = None,
        reference: Any = None,
        param_bounds: Optional[Dict[str, Tuple[float, float]]] = None,
        base_options: Optional[Dict[str, Any]] = None,
        misfit_fn: Optional[Callable] = None,
    ):
        self._well_source = well_file or well_list
        self._ref_source = reference_file or reference

        self.param_bounds = dict(param_bounds or DEFAULT_PARAM_BOUNDS)
        self.base_options = dict(base_options or {})
        self.misfit_fn = misfit_fn or marker_offset_misfit

        # Loaded objects (lazy)
        self._well_list = well_list
        self._reference = reference

        # History
        self.history: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    #  Lazy loading
    # ------------------------------------------------------------------

    def _load_wells(self):
        """Load well data if not already loaded."""
        if self._well_list is not None:
            return self._well_list
        from weco.data import WellList
        if isinstance(self._well_source, str):
            self._well_list = WellList(self._well_source)
        else:
            self._well_list = self._well_source
        return self._well_list

    def _load_reference(self):
        """Load reference correlation if not already loaded."""
        if self._reference is not None:
            return self._reference
        from weco.data import ResFile
        if isinstance(self._ref_source, str):
            self._reference = ResFile(self._ref_source)
        else:
            self._reference = self._ref_source
        return self._reference

    # ------------------------------------------------------------------
    #  Engine runner
    # ------------------------------------------------------------------

    def _run_engine(self, params: Dict[str, float]):
        """Run WeCo with the given parameters and return the ResFile."""
        from weco.ext import ProjectExt

        proj = ProjectExt()

        # Apply fixed base options
        for key, val in self.base_options.items():
            proj.set_option_ext(key, val)

        # Apply tunable parameters
        for key, val in params.items():
            proj.set_option_ext(key, val)

        well_list = self._load_wells()
        proj.run(well_list)
        return proj.get_res_file()

    # ------------------------------------------------------------------
    #  Objective
    # ------------------------------------------------------------------

    def _objective(self, param_vector: np.ndarray) -> float:
        """Evaluate the misfit for a parameter vector."""
        names = list(self.param_bounds.keys())
        params = {n: float(v) for n, v in zip(names, param_vector)}

        try:
            result = self._run_engine(params)
        except Exception:
            return float("inf")

        reference = self._load_reference()
        misfit = self.misfit_fn(result, reference)

        self.history.append({"params": params, "misfit": misfit})
        return misfit

    # ------------------------------------------------------------------
    #  Differential Evolution
    # ------------------------------------------------------------------

    def optimise(
        self,
        max_iter: int = 50,
        method: str = "de",
        seed: int = 42,
        **kwargs,
    ) -> Dict[str, float]:
        """Run parameter optimisation.

        Parameters
        ----------
        max_iter : int
            Maximum number of iterations / generations.
        method : str
            ``"de"`` — differential evolution (robust, population-based).
            ``"nelder"`` — Nelder-Mead simplex (fast, local).
            ``"bayes"`` — Bayesian optimisation (if scikit-optimize available).
        seed : int
            Random seed.
        **kwargs
            Passed through to the underlying scipy / skopt optimiser.

        Returns
        -------
        dict
            Optimal parameter values: ``{param_name: value, …}``.
        """
        from scipy.optimize import differential_evolution, minimize

        self.history.clear()
        bounds = [self.param_bounds[k] for k in self.param_bounds]
        names = list(self.param_bounds.keys())

        if method == "de":
            result = differential_evolution(
                self._objective,
                bounds,
                maxiter=max_iter,
                seed=seed,
                **kwargs,
            )
        elif method == "nelder":
            x0 = np.array([(lo + hi) / 2 for lo, hi in bounds])
            result = minimize(
                self._objective,
                x0,
                method="Nelder-Mead",
                options={"maxiter": max_iter, **kwargs},
            )
        elif method == "bayes":
            return self._bayesian_optimise(max_iter=max_iter, seed=seed, **kwargs)
        else:
            raise ValueError(f"Unknown method '{method}'. Use 'de', 'nelder', or 'bayes'.")

        return {n: float(v) for n, v in zip(names, result.x)}

    def _bayesian_optimise(
        self,
        max_iter: int = 50,
        seed: int = 42,
        **kwargs,
    ) -> Dict[str, float]:
        """Bayesian optimisation with a Gaussian Process surrogate.

        Requires ``scikit-optimize``.  Falls back to differential
        evolution if not available.
        """
        try:
            from skopt import gp_minimize
            from skopt.space import Real
        except ImportError:
            import warnings
            warnings.warn(
                "scikit-optimize not installed — falling back to "
                "differential evolution.  Install with: pip install scikit-optimize",
                stacklevel=2,
            )
            return self.optimise(max_iter=max_iter, method="de", seed=seed)

        names = list(self.param_bounds.keys())
        dimensions = [Real(lo, hi, name=n) for n, (lo, hi) in self.param_bounds.items()]

        self.history.clear()

        result = gp_minimize(
            self._objective,
            dimensions,
            n_calls=max_iter,
            random_state=seed,
            **kwargs,
        )

        return {n: float(v) for n, v in zip(names, result.x)}

    # ------------------------------------------------------------------
    #  Analysis helpers
    # ------------------------------------------------------------------

    def best_result(self) -> Optional[Dict[str, Any]]:
        """Return the best (lowest misfit) entry from history."""
        if not self.history:
            return None
        return min(self.history, key=lambda h: h["misfit"])

    def convergence_curve(self) -> Tuple[np.ndarray, np.ndarray]:
        """Return (iteration, cumulative_best_misfit) arrays.

        Useful for plotting convergence.
        """
        if not self.history:
            return np.array([]), np.array([])

        misfits = [h["misfit"] for h in self.history]
        cum_best = np.minimum.accumulate(misfits)
        iters = np.arange(1, len(misfits) + 1)
        return iters, cum_best

    def parameter_sensitivity(self) -> Dict[str, float]:
        """Estimate per-parameter sensitivity from the optimisation history.

        Computes the Spearman rank correlation between each parameter
        and the misfit across all evaluated points.

        Returns
        -------
        dict
            ``{param_name: |correlation|}``.  Higher = more sensitive.
        """
        if len(self.history) < 5:
            return {}

        from scipy.stats import spearmanr

        names = list(self.param_bounds.keys())
        misfits = np.array([h["misfit"] for h in self.history])

        sensitivity = {}
        for name in names:
            values = np.array([h["params"].get(name, 0.0) for h in self.history])
            corr, _pval = spearmanr(values, misfits)
            sensitivity[name] = abs(float(corr)) if not math.isnan(corr) else 0.0

        return sensitivity

    def summary(self) -> str:
        """Human-readable summary of the optimisation."""
        best = self.best_result()
        if best is None:
            return "No optimisation has been run."

        lines = [
            f"AutoTuner summary  ({len(self.history)} evaluations)",
            f"  Best misfit: {best['misfit']:.6f}",
            "  Best parameters:",
        ]
        for k, v in best["params"].items():
            lines.append(f"    {k}: {v:.4f}")

        sens = self.parameter_sensitivity()
        if sens:
            lines.append("  Parameter sensitivity (|Spearman ρ|):")
            for k in sorted(sens, key=sens.get, reverse=True):
                lines.append(f"    {k}: {sens[k]:.3f}")

        return "\n".join(lines)
