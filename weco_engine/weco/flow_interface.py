"""
weco.flow_interface — Flow simulation interface via FloPy (§11.10.5)
=====================================================================

Convert WeCo correlation results to a FloPy-compatible MODFLOW grid
and run simple flow simulations for connectivity analysis.

Requires ``flopy`` as an optional dependency::

    pip install flopy

Usage::

    from weco.flow_interface import CorrelationToModflow
    converter = CorrelationToModflow(res_file, well_list)
    sim = converter.build_model(workspace="sim_output")
    converter.run()
    connectivity = converter.get_connectivity()
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import numpy as np

if TYPE_CHECKING:
    from weco.engine_data import ResFile, WellList

logger = logging.getLogger(__name__)


class CorrelationToModflow:
    """Convert WeCo correlation results to a MODFLOW model via FloPy.

    Parameters
    ----------
    res_file : ResFile
        Correlation result file.
    well_list : WellList
        Well list with depth/coordinate data.
    correlation_index : int
        Which correlation result to use (0 = best).
    """

    def __init__(self, res_file, well_list, correlation_index: int = 0):
        self.res_file = res_file
        self.well_list = well_list
        self.cor_idx = correlation_index
        self._sim = None
        self._model = None

    def _get_layer_elevations(self) -> Tuple[np.ndarray, np.ndarray]:
        """Extract layer top/bottom elevations from correlation horizons.

        Returns
        -------
        tops : ndarray of shape (n_layers, n_wells)
        bots : ndarray of shape (n_layers, n_wells)
        """
        path = self.res_file.get_result_full_path(self.cor_idx)
        n_wells = self.res_file.nbr_well()
        n_horizons = len(path)
        n_layers = max(n_horizons - 1, 1)

        tops = np.zeros((n_layers, n_wells))
        bots = np.zeros((n_layers, n_wells))

        for w in range(n_wells):
            well = self.well_list.wells[w] if w < len(self.well_list.wells) else None
            if well is None:
                continue
            depth_key = None
            for dk in ("Depth", "DEPTH", "MD", "depth"):
                if dk in well.data:
                    depth_key = dk
                    break
            if depth_key is None:
                continue
            depths = well.data[depth_key]
            for layer in range(n_layers):
                m_top = path[layer][w]
                m_bot = path[layer + 1][w] if layer + 1 < n_horizons else m_top
                if 0 <= m_top < len(depths) and 0 <= m_bot < len(depths):
                    tops[layer, w] = depths[m_top]
                    bots[layer, w] = depths[m_bot]

        return tops, bots

    def build_model(
        self,
        workspace: str = "weco_modflow",
        model_name: str = "weco_flow",
        nrow: int = 10,
        ncol: int = 10,
        cell_size: float = 100.0,
        kh: float = 1.0,
        kv: float = 0.1,
    ):
        """Build a simple MODFLOW 6 model from correlation layer data.

        Parameters
        ----------
        workspace : str
            Directory for simulation files.
        model_name : str
            Model name.
        nrow, ncol : int
            Grid rows/columns.
        cell_size : float
            Horizontal cell size in metres.
        kh, kv : float
            Horizontal/vertical hydraulic conductivity.

        Returns
        -------
        flopy.mf6.MFSimulation
        """
        try:
            import flopy
        except ImportError:
            raise ImportError(
                "FloPy is required for flow simulation. Install with: pip install flopy"
            )

        tops, bots = self._get_layer_elevations()
        n_layers = tops.shape[0]

        os.makedirs(workspace, exist_ok=True)

        sim = flopy.mf6.MFSimulation(
            sim_name=model_name, sim_ws=workspace, exe_name="mf6"
        )

        tdis = flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)])

        ims = flopy.mf6.ModflowIms(sim, complexity="SIMPLE")

        gwf = flopy.mf6.ModflowGwf(sim, modelname=model_name, save_flows=True)

        # Average tops/bots across wells for layer elevations
        mean_tops = np.mean(tops, axis=1)
        mean_bots = np.mean(bots, axis=1)

        top_elev = float(mean_tops[0]) if n_layers > 0 else 0.0
        botm = mean_bots.tolist()

        flopy.mf6.ModflowGwfdis(
            gwf,
            nlay=n_layers,
            nrow=nrow,
            ncol=ncol,
            delr=cell_size,
            delc=cell_size,
            top=top_elev,
            botm=botm,
        )

        flopy.mf6.ModflowGwfnpf(
            gwf, k=kh, k33=kv, save_specific_discharge=True
        )

        flopy.mf6.ModflowGwfic(gwf, strt=top_elev)

        # Simple constant head boundary on left and right
        chd_data = []
        for lay in range(n_layers):
            for row in range(nrow):
                chd_data.append(((lay, row, 0), top_elev))
                chd_data.append(((lay, row, ncol - 1), top_elev - 1.0))

        flopy.mf6.ModflowGwfchd(gwf, stress_period_data=chd_data)

        flopy.mf6.ModflowGwfoc(
            gwf,
            head_filerecord=f"{model_name}.hds",
            budget_filerecord=f"{model_name}.cbc",
            saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
        )

        self._sim = sim
        self._model = gwf
        return sim

    def run(self) -> bool:
        """Run the MODFLOW simulation.

        Returns
        -------
        bool
            True if the simulation succeeded.
        """
        if self._sim is None:
            raise RuntimeError("Call build_model() first")
        success, _ = self._sim.run_simulation(silent=True)
        if not success:
            logger.warning("MODFLOW simulation failed")
        return success

    def get_connectivity(self) -> Dict[str, float]:
        """Extract connectivity metrics from simulation results.

        Returns
        -------
        dict
            Keys: 'total_flow', 'max_head_diff', 'mean_head'.
        """
        try:
            import flopy.utils as fu
        except ImportError:
            return {}

        if self._sim is None or self._model is None:
            return {}

        ws = self._sim.sim_path
        model_name = self._model.name
        hds_path = os.path.join(ws, f"{model_name}.hds")

        if not os.path.exists(hds_path):
            return {}

        hds = fu.HeadFile(hds_path)
        heads = hds.get_data()

        return {
            "total_flow": float(np.sum(np.abs(np.diff(heads, axis=-1)))),
            "max_head_diff": float(np.max(heads) - np.min(heads)),
            "mean_head": float(np.mean(heads)),
        }
