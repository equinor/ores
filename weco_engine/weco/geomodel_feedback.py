"""
weco.geomodel_feedback — 3D structural model feedback loop (§6.3)
==================================================================

Use geomodel thickness maps to update correlation priors.  After an
initial correlation, compare predicted vs observed layer thicknesses
from a 3D structural model and feed residuals back as updated costs.

Usage::

    from weco.geomodel_feedback import GeomodelFeedback

    fb = GeomodelFeedback(geomodel_grid, well_list, res_file)
    updated_weights = fb.compute_feedback()
    # Re-run WeCo with updated weights
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class GeomodelFeedback:
    """
    Iterative feedback between WeCo correlations and a 3D geomodel.

    Workflow:
    1. Run initial WeCo correlation.
    2. Build geomodel from correlation (e.g. via petrel/GOCAD).
    3. Extract layer-thickness maps from geomodel.
    4. Compare predicted thicknesses at well locations with observed.
    5. Generate updated cost weights that penalise inconsistencies.
    6. Re-run WeCo with updated weights.
    """

    def __init__(
        self,
        thickness_maps: Dict[str, np.ndarray],
        well_positions: Dict[str, Tuple[float, float]],
        observed_thicknesses: Dict[str, Dict[str, float]],
    ):
        """
        Parameters
        ----------
        thickness_maps : dict
            ``{layer_name: ndarray}`` — modelled thickness at each grid cell.
            Shape ``(ny, nx)`` with geographic coordinates.
        well_positions : dict
            ``{well_name: (x, y)}`` — well head positions.
        observed_thicknesses : dict
            ``{well_name: {layer_name: thickness}}`` — measured thicknesses.
        """
        self.thickness_maps = thickness_maps
        self.well_positions = well_positions
        self.observed_thicknesses = observed_thicknesses

    def compute_residuals(
        self,
        grid_origin: Tuple[float, float] = (0.0, 0.0),
        grid_spacing: Tuple[float, float] = (1.0, 1.0),
    ) -> Dict[str, Dict[str, float]]:
        """
        Compute thickness residuals (observed - modelled) at each well.

        Returns
        -------
        dict
            ``{well_name: {layer_name: residual}}``
        """
        residuals = {}
        for well, (wx, wy) in self.well_positions.items():
            if well not in self.observed_thicknesses:
                continue
            residuals[well] = {}
            # Grid indices from coordinates
            ix = int((wx - grid_origin[0]) / grid_spacing[0])
            iy = int((wy - grid_origin[1]) / grid_spacing[1])
            for layer, obs_thick in self.observed_thicknesses[well].items():
                if layer not in self.thickness_maps:
                    continue
                tmap = self.thickness_maps[layer]
                iy_c = np.clip(iy, 0, tmap.shape[0] - 1)
                ix_c = np.clip(ix, 0, tmap.shape[1] - 1)
                mod_thick = float(tmap[iy_c, ix_c])
                residuals[well][layer] = obs_thick - mod_thick
        return residuals

    def compute_feedback(
        self,
        grid_origin: Tuple[float, float] = (0.0, 0.0),
        grid_spacing: Tuple[float, float] = (1.0, 1.0),
        base_weight: float = 1.0,
        sensitivity: float = 2.0,
    ) -> Dict[str, float]:
        """
        Generate updated cost weights from geomodel residuals.

        Layers with large residuals get higher weights, encouraging WeCo
        to revise correlations where the geomodel is inconsistent.

        Parameters
        ----------
        base_weight : float
            Default weight for layers with zero residual.
        sensitivity : float
            Scaling factor: ``weight = base + sensitivity × |residual/thickness|``.

        Returns
        -------
        dict
            ``{layer_name: updated_weight}``
        """
        residuals = self.compute_residuals(grid_origin, grid_spacing)

        # Aggregate residuals per layer across wells
        layer_residuals: Dict[str, List[float]] = {}
        layer_thicknesses: Dict[str, List[float]] = {}
        for well, layers in residuals.items():
            for layer, res in layers.items():
                layer_residuals.setdefault(layer, []).append(res)
                obs = self.observed_thicknesses.get(well, {}).get(layer, 1.0)
                layer_thicknesses.setdefault(layer, []).append(max(abs(obs), 1e-6))

        weights = {}
        for layer in layer_residuals:
            mean_res = np.mean(np.abs(layer_residuals[layer]))
            mean_thick = np.mean(layer_thicknesses[layer])
            norm_res = mean_res / mean_thick
            weights[layer] = base_weight + sensitivity * norm_res

        logger.info(f"Feedback weights for {len(weights)} layers: "
                     f"range [{min(weights.values()):.2f}, {max(weights.values()):.2f}]")
        return weights

    def iterate(
        self,
        run_weco_fn,
        build_geomodel_fn,
        max_iterations: int = 5,
        convergence_threshold: float = 0.01,
        **kwargs,
    ) -> List[Dict[str, float]]:
        """
        Run the full feedback loop iteratively.

        Parameters
        ----------
        run_weco_fn : callable
            ``run_weco_fn(weights) -> (res_file, observed_thicknesses)``
        build_geomodel_fn : callable
            ``build_geomodel_fn(res_file) -> thickness_maps``
        max_iterations : int
            Maximum number of feedback cycles.
        convergence_threshold : float
            Stop when max weight change < threshold.

        Returns
        -------
        list of dict
            Weight history for each iteration.
        """
        weight_history = []
        current_weights = {layer: 1.0 for layer in self.thickness_maps}

        for iteration in range(max_iterations):
            logger.info(f"Feedback iteration {iteration + 1}/{max_iterations}")

            res_file, obs_thick = run_weco_fn(current_weights)
            self.observed_thicknesses = obs_thick

            thickness_maps = build_geomodel_fn(res_file)
            self.thickness_maps = thickness_maps

            new_weights = self.compute_feedback(**kwargs)
            weight_history.append(new_weights)

            # Check convergence
            if current_weights and new_weights:
                max_change = max(
                    abs(new_weights.get(k, 1.0) - current_weights.get(k, 1.0))
                    for k in set(new_weights) | set(current_weights)
                )
                if max_change < convergence_threshold:
                    logger.info(f"Converged after {iteration + 1} iterations "
                                f"(max change {max_change:.4f})")
                    break

            current_weights = new_weights

        return weight_history
