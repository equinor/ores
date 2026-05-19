"""
weco.workflow — End-to-end correlation workflow for geomodelling
================================================================

A high-level orchestrator that connects every step of the WeCo pipeline:

1. **Import** — LAS / RESQML / WeCo / CSV  (continuous + discrete logs)
2. **Condition** — Vshale, normalisation, electrofacies, biozones
3. **Configure** — cost function, gap penalty, well order, constraints
4. **Correlate** — run the WeCo engine (n-best graph-DTW)
5. **Validate** — quality scoring, sensitivity, reference comparison
6. **Export** — RMS-ready well picks, zonation logs, summary report

Designed for the key use case:

    *Low-NTG shallow marine reservoir correlation in Norway*
    *at subseismic / well-log scale for chronostratigraphic modelling*
    *(Hugin Formation, Gudrun–Sigrun field analogue)*

The workflow tracks provenance (every parameter, every step) and
produces a self-documenting output package.

Usage — quick start::

    from weco.workflow import CorrelationWorkflow

    wf = CorrelationWorkflow("Hugin_Study")
    wf.import_las("wells/*.las")
    wf.condition(vshale=True, normalize=True, biozones="biozones.csv")
    wf.configure(preset="shallow_marine")
    wf.run()
    wf.export_rms("tmp/rms_package/")

Usage — full control::

    wf = CorrelationWorkflow("Study_1")
    wf.import_las(["W1.las", "W2.las", "W3.las"],
                  curves={"GR": "GR", "RT": "RESD"}, 
                  discrete={"FACIES": "LITH_CODE"})
    wf.condition(
        vshale=True, gr_min=20, gr_max=120,
        normalize=["GR", "RT"],
        electrofacies=4,
        biozones="biozones.csv")
    wf.configure(
        cost_logs=["GR", "RT"],
        cost_weights=[2.0, 1.0],
        gap_cost=5.0,
        order="distality",
        n_best=10,
        regions={"FACIES": 3.0})
    wf.run()
    quality = wf.validate(reference="ref_picks.csv")
    wf.export_rms("tmp/", include_script=True)
    wf.save_report("tmp/report.json")
"""

from __future__ import annotations

import glob
import json
import logging
import os
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from .data import Well, WellList, ResFile

logger = logging.getLogger("weco.workflow")


# ---------------------------------------------------------------------------
# Geological presets
# ---------------------------------------------------------------------------

PRESETS: Dict[str, Dict[str, Any]] = {
    "shallow_marine": {
        "description": (
            "Low-NTG shallow marine deltaic / shoreface.  "
            "Focus on GR pattern matching for parasequence-scale "
            "chronostratigraphy.  Facies-constrained if available."
        ),
        "cost_logs": ["GR"],
        "cost_weights": [1.0],
        "nbest": 10,
        "order": "pyramidal",
        "options": {
            "cost-function": "composite",
            "nbr-cor": "10",
            "max-cor": "50",
        },
    },
    "shallow_marine_multi": {
        "description": (
            "Multi-log shallow marine.  GR + resistivity + density "
            "for better discrimination of thin beds and cemented "
            "intervals."
        ),
        "cost_logs": ["GR", "RT", "RHOB"],
        "cost_weights": [2.0, 1.0, 1.0],
        "nbest": 10,
        "order": "pyramidal",
        "options": {
            "cost-function": "composite",
            "nbr-cor": "10",
            "max-cor": "50",
        },
    },
    "deep_marine": {
        "description": (
            "Deep marine turbidite / channel–levee system.  Often "
            "high NTG with laterally variable sand bodies."
        ),
        "cost_logs": ["GR"],
        "cost_weights": [1.0],
        "nbest": 15,
        "order": "pyramidal",
        "options": {
            "cost-function": "composite",
            "nbr-cor": "15",
            "max-cor": "100",
        },
    },
    "fluvial": {
        "description": (
            "Fluvial / alluvial system.  Highly variable laterally, "
            "stacked channel bodies.  Many n-best to capture ambiguity."
        ),
        "cost_logs": ["GR"],
        "cost_weights": [1.0],
        "nbest": 20,
        "order": "pyramidal",
        "options": {
            "cost-function": "composite",
            "nbr-cor": "20",
            "max-cor": "100",
        },
    },
    "carbonate": {
        "description": (
            "Carbonate platform / reef.  Porosity + sonic are key "
            "discriminators alongside GR.  Strong same-region "
            "constraint for facies associations."
        ),
        "cost_logs": ["GR", "NPHI", "DT"],
        "cost_weights": [1.0, 1.5, 1.0],
        "nbest": 10,
        "order": "pyramidal",
        "options": {
            "cost-function": "composite",
            "nbr-cor": "10",
            "max-cor": "50",
        },
    },
    "default": {
        "description": "Balanced default settings for general use.",
        "cost_logs": ["GR"],
        "cost_weights": [1.0],
        "nbest": 10,
        "order": "pyramidal",
        "options": {
            "cost-function": "composite",
            "nbr-cor": "10",
            "max-cor": "50",
        },
    },
}


# ---------------------------------------------------------------------------
# Workflow class
# ---------------------------------------------------------------------------

class CorrelationWorkflow:
    """
    End-to-end well correlation workflow for geomodelling.

    Orchestrates data import → conditioning → correlation → export
    with full provenance tracking and geological presets.

    Parameters
    ----------
    name : str
        Study / project name (used for output labelling).
    working_dir : str, optional
        Working directory for intermediate files.  Default: current dir.
    """

    def __init__(self, name: str = "WeCo_Study", working_dir: str = "."):
        self.name = name
        self.working_dir = os.path.abspath(working_dir)
        os.makedirs(self.working_dir, exist_ok=True)

        # State
        self.well_list: Optional[WellList] = None
        self.res_file: Optional[ResFile] = None
        self.preset_name: Optional[str] = None
        self.options: Dict[str, str] = {}
        self.code_tables: Dict[str, Dict[int, str]] = {}  # region_name → {id: label}

        # Provenance log
        self._log: List[Dict[str, Any]] = []
        self._step_count = 0

    def _record(self, step: str, **details):
        """Record a workflow step for provenance."""
        self._step_count += 1
        entry = {
            "step": self._step_count,
            "action": step,
            "time": datetime.now().isoformat(),
            **details,
        }
        self._log.append(entry)
        logger.info(f"[{self._step_count}] {step}: {details}")

    # ------------------------------------------------------------------
    # Step 1: Import
    # ------------------------------------------------------------------

    def import_wells(
        self,
        path: str,
        fmt: str = None,
        **kwargs,
    ) -> "CorrelationWorkflow":
        """Import wells from any supported format (auto-detected).

        Parameters
        ----------
        path : str
            Path to well data file.  For LAS, can be a glob pattern.
        fmt : str, optional
            Force format.  ``None`` = auto-detect.
        **kwargs
            Format-specific options passed to the reader.

        Returns
        -------
        self
            For method chaining.
        """
        from .formats import read_wells, detect_format

        if "*" in path or "?" in path:
            return self.import_las(glob.glob(path), **kwargs)

        wl = read_wells(path, fmt=fmt, **kwargs)
        if self.well_list is None:
            self.well_list = wl
        else:
            self.well_list.wells.extend(wl.wells)

        self._record("import_wells", path=path, fmt=fmt or detect_format(path),
                      n_wells=len(wl.wells),
                      wells=[w.name for w in wl.wells])
        return self

    def import_las(
        self,
        paths: Union[str, List[str]],
        *,
        curves: Optional[Dict[str, str]] = None,
        discrete: Optional[Dict[str, str]] = None,
        filter_expr: Optional[str] = None,
    ) -> "CorrelationWorkflow":
        """Import one or more LAS files with continuous + discrete log handling.

        Parameters
        ----------
        paths : str or list[str]
            LAS file path(s) or glob pattern.
        curves : dict[str, str], optional
            ``{weco_name: las_name}`` mapping for continuous curves.
            ``None`` = import all curves found in LAS file.
        discrete : dict[str, str], optional
            ``{region_name: las_curve_name}`` for discrete logs.
            These are imported as continuous data first, then automatically
            converted to WeCo regions via :meth:`Well.add_region_from_data`.
            A code table mapping is preserved.
        filter_expr : str, optional
            Row filter expression (e.g., ``"DEPTH > 1500"``).

        Returns
        -------
        self
        """
        from .lasfile import LASFile
        from .las2welllist import las2well

        if isinstance(paths, str):
            if "*" in paths or "?" in paths:
                paths = sorted(glob.glob(paths))
            else:
                paths = [paths]

        if not paths:
            raise FileNotFoundError(f"No LAS files found matching pattern")

        # Build curve list for las2well
        curve_list = None
        all_curve_names = {}  # track weco_name → las_name
        if curves or discrete:
            curve_list = []
            if curves:
                for wname, lname in curves.items():
                    curve_list.append((wname, lname))
                    all_curve_names[wname] = lname
            if discrete:
                for rname, lname in discrete.items():
                    curve_list.append((rname, lname))
                    all_curve_names[rname] = lname

        if self.well_list is None:
            self.well_list = WellList.__new__(WellList)
            self.well_list.wells = []

        imported = []
        for p in paths:
            las = LASFile()
            las.read(str(p))
            well = las2well(las, curves=curve_list, filter=filter_expr)
            if well is None:
                logger.warning(f"Skipped {p}: could not convert")
                continue

            # Convert discrete curves to regions
            if discrete:
                for rname, lname in discrete.items():
                    if rname in well.data:
                        # Build code table from unique values
                        values = np.array(well.data[rname], dtype=float)
                        valid = values[~np.isnan(values)]
                        unique_codes = sorted(set(int(v) for v in valid
                                                  if v == v))  # exclude NaN
                        code_table = {c: f"{rname}_{c}" for c in unique_codes}
                        self.code_tables[rname] = code_table

                        # Convert to region
                        well.add_region_from_data(rname)
                        logger.info(
                            f"{well.name}: discrete '{rname}' → "
                            f"{len(well.region.get(rname, []))} intervals, "
                            f"codes={unique_codes}"
                        )

            self.well_list.wells.append(well)
            imported.append(well.name)

        self._record("import_las", n_files=len(paths),
                      curves=curves, discrete=discrete,
                      wells=imported)
        return self

    def import_resqml(
        self,
        epc_path: str,
        *,
        include_discrete: bool = True,
    ) -> "CorrelationWorkflow":
        """Import wells from a RESQML .epc + .h5 file pair.

        Parameters
        ----------
        epc_path : str
            Path to the .epc file.
        include_discrete : bool
            Whether to import DiscreteProperty objects as regions.

        Returns
        -------
        self
        """
        from .resqml import ResqmlFile
        from .data import Well

        rf = ResqmlFile(str(epc_path))

        if self.well_list is None:
            self.well_list = WellList.__new__(WellList)
            self.well_list.wells = []

        imported = []
        for wbf in rf.get_objects_by_type("WellboreFrameRepresentation"):
            name = wbf.title or f"Well_{len(self.well_list.wells)}"
            md_data = wbf.get_md_data(rf)
            if md_data is None:
                continue

            w = Well()
            w.name = name
            w.size = len(md_data)
            w.data["Depth"] = list(md_data)

            # Continuous properties
            for prop in rf.get_properties_on(wbf.uuid):
                ptype = type(prop).__name__
                pname = prop.title or "unnamed"
                try:
                    values = prop.get_values(rf)
                    if values is None or len(values) < w.size:
                        continue

                    if ptype == "DiscreteProperty" and include_discrete:
                        # Store as data first, then convert to region
                        w.data[pname] = [int(v) for v in values[:w.size]]
                        w.add_region_from_data(pname)
                        unique = sorted(set(int(v) for v in values[:w.size]))
                        self.code_tables[pname] = {
                            c: f"{pname}_{c}" for c in unique
                        }
                    else:
                        w.data[pname] = list(values[:w.size])
                except Exception as e:
                    logger.warning(f"  {name}/{pname}: {e}")

            # Trajectory for position
            for traj in rf.get_objects_by_type(
                    "WellboreTrajectoryRepresentation"):
                if hasattr(traj, 'wellbore_interpretation'):
                    # Try to match well
                    pass

            self.well_list.wells.append(w)
            imported.append(name)

        self._record("import_resqml", epc_path=epc_path,
                      n_wells=len(imported), wells=imported,
                      include_discrete=include_discrete)
        return self

    def import_rddms(
        self,
        url: str,
        token: str,
        dataspace: str,
        *,
        partition: str = "",
        uuid_filter: Optional[set] = None,
    ) -> "CorrelationWorkflow":
        """Import wells from an RDDMS v2 dataspace.

        Requires the GOCAD RESQML package and ``requests``.

        Parameters
        ----------
        url : str
            RDDMS REST endpoint URL.
        token : str
            Bearer access token.
        dataspace : str
            Dataspace identifier.
        partition : str, optional
            Data partition ID.
        uuid_filter : set[str], optional
            Restrict to these well UUIDs.

        Returns
        -------
        self
        """
        from .rddms import rddms_import_wells

        wl = rddms_import_wells(
            url, token, dataspace,
            partition=partition,
            uuid_filter=uuid_filter,
        )
        if self.well_list is None:
            self.well_list = wl
        else:
            self.well_list.wells.extend(wl.wells)

        self._record("import_rddms", url=url, dataspace=dataspace,
                      n_wells=len(wl.wells),
                      wells=[w.name for w in wl.wells])
        return self

    def import_epc(
        self,
        epc_path: str,
    ) -> "CorrelationWorkflow":
        """Import wells from a RESQML EPC file via the GOCAD bridge.

        Unlike :meth:`import_resqml` (which uses WeCo's built-in reader),
        this uses the full GOCAD RESQML package for richer property and
        marker support.

        Parameters
        ----------
        epc_path : str
            Path to the .epc file (with companion .h5).

        Returns
        -------
        self
        """
        from .rddms import epc_import_wells

        wl = epc_import_wells(epc_path)
        if self.well_list is None:
            self.well_list = wl
        else:
            self.well_list.wells.extend(wl.wells)

        self._record("import_epc", epc_path=epc_path,
                      n_wells=len(wl.wells),
                      wells=[w.name for w in wl.wells])
        return self

    def import_gocad(
        self,
        path: str,
    ) -> "CorrelationWorkflow":
        """Import wells from a GOCAD ASCII well file.

        Parameters
        ----------
        path : str
            Path to GOCAD .wl file.

        Returns
        -------
        self
        """
        from .rddms import gocad_import_wells

        wl = gocad_import_wells(path)
        if self.well_list is None:
            self.well_list = wl
        else:
            self.well_list.wells.extend(wl.wells)

        self._record("import_gocad", path=path,
                      n_wells=len(wl.wells),
                      wells=[w.name for w in wl.wells])
        return self

    def import_csv(
        self,
        path: str,
        *,
        well_column: str = "Well",
        depth_column: str = "Depth",
        x_column: Optional[str] = "X",
        y_column: Optional[str] = "Y",
        discrete_columns: Optional[List[str]] = None,
        separator: str = ",",
    ) -> "CorrelationWorkflow":
        """Import wells from a CSV file.

        Parameters
        ----------
        path : str
            CSV file path.
        well_column, depth_column : str
            Column names.
        x_column, y_column : str, optional
            Coordinate column names.
        discrete_columns : list[str], optional
            Columns to convert to regions.
        separator : str
            Column separator.

        Returns
        -------
        self
        """
        from .rddms import csv_import_wells

        wl = csv_import_wells(
            path,
            well_column=well_column,
            depth_column=depth_column,
            x_column=x_column,
            y_column=y_column,
            discrete_columns=discrete_columns,
            separator=separator,
        )
        if self.well_list is None:
            self.well_list = wl
        else:
            self.well_list.wells.extend(wl.wells)

        self._record("import_csv", path=path,
                      n_wells=len(wl.wells),
                      wells=[w.name for w in wl.wells])
        return self

    def add_discrete_log(
        self,
        csv_path: str,
        region_name: str,
        *,
        well_column: str = "Well",
        depth_column: str = "Depth",
        value_column: str = "Code",
        name_column: Optional[str] = "Name",
    ) -> "CorrelationWorkflow":
        """Add discrete log data (facies, lithology, biostrat) from CSV.

        CSV format::

            Well,Depth,Code,Name
            Well_A,1500.0,1,Sand
            Well_A,1500.5,2,Shale
            ...

        Parameters
        ----------
        csv_path : str
            Path to CSV file.
        region_name : str
            Name for the region in the WeCo data model.
        well_column, depth_column, value_column : str
            Column names.
        name_column : str, optional
            Column with label names.  If present, builds a code table.

        Returns
        -------
        self
        """
        import csv as csvmod

        if self.well_list is None:
            raise RuntimeError("Import wells before adding discrete logs")

        # Read CSV
        with open(csv_path) as f:
            reader = csvmod.DictReader(f)
            rows = list(reader)

        # Build code table from name column
        code_table = {}
        for row in rows:
            code = int(row[value_column])
            if name_column and name_column in row:
                code_table[code] = row[name_column]
            elif code not in code_table:
                code_table[code] = f"{region_name}_{code}"

        if code_table:
            self.code_tables[region_name] = code_table

        # Group by well
        well_data = {}
        for row in rows:
            wn = row[well_column]
            well_data.setdefault(wn, []).append(
                (float(row[depth_column]), int(row[value_column]))
            )

        # Assign to wells
        well_lookup = {w.name: w for w in self.well_list.wells}
        assigned = 0
        for wn, samples in well_data.items():
            if wn not in well_lookup:
                logger.warning(f"Well '{wn}' not found, skipping")
                continue
            w = well_lookup[wn]

            # Match depths to nearest markers
            if "Depth" in w.data:
                wdepths = np.array(w.data["Depth"])
            else:
                wdepths = np.linspace(0, w.h or w.size, w.size)

            # Build per-marker code array
            codes = np.zeros(w.size, dtype=int)
            for depth, code in samples:
                idx = np.argmin(np.abs(wdepths - depth))
                codes[idx] = code

            # Convert to intervals
            from .preprocessing import _labels_to_intervals
            w.region[region_name] = _labels_to_intervals(codes)
            assigned += 1

        self._record("add_discrete_log", csv_path=csv_path,
                      region_name=region_name,
                      n_wells_assigned=assigned,
                      n_codes=len(code_table))
        return self

    # ------------------------------------------------------------------
    # Step 2: Condition
    # ------------------------------------------------------------------

    def condition(
        self,
        *,
        vshale: bool = True,
        gr_name: str = "GR",
        gr_min: Optional[float] = None,
        gr_max: Optional[float] = None,
        normalize: Union[bool, List[str]] = True,
        electrofacies: Optional[int] = None,
        electrofacies_logs: Optional[List[str]] = None,
        biozones: Optional[str] = None,
        stacking_pattern: bool = False,
    ) -> "CorrelationWorkflow":
        """Apply data conditioning transforms.

        Parameters
        ----------
        vshale : bool
            Compute Vshale from GR.
        gr_name : str
            GR curve name.
        gr_min, gr_max : float, optional
            Manual GR clean/dirty endpoints.  ``None`` = auto.
        normalize : bool or list[str]
            Normalise GR (``True``) or list of curve names to normalise.
        electrofacies : int, optional
            Number of electrofacies clusters.  ``None`` = skip.
        electrofacies_logs : list[str], optional
            Logs for electrofacies.  Default: ``[gr_name]``.
        biozones : str, optional
            Path to biozone CSV file.
        stacking_pattern : bool
            Compute stacking pattern (CU/FU) from GR.

        Returns
        -------
        self
        """
        if self.well_list is None:
            raise RuntimeError("Import wells before conditioning")

        from .preprocessing import (
            compute_vshale, compute_stacking_pattern,
            normalise_log, compute_electrofacies,
            read_biozone_csv,
        )

        steps_done = []

        # Vshale
        if vshale and gr_name:
            kwargs = {"gr_name": gr_name}
            if gr_min is not None:
                kwargs["gr_min"] = gr_min
            if gr_max is not None:
                kwargs["gr_max"] = gr_max
            ok = True
            for w in self.well_list.wells:
                if gr_name in w.data:
                    ok &= compute_vshale(w, **kwargs)
            if ok:
                steps_done.append("vshale")

        # Stacking pattern
        if stacking_pattern and gr_name:
            for w in self.well_list.wells:
                if gr_name in w.data:
                    compute_stacking_pattern(w, gr_name=gr_name)
            steps_done.append("stacking_pattern")

        # Normalisation
        if normalize:
            if isinstance(normalize, bool):
                logs_to_norm = [gr_name] if gr_name else []
            else:
                logs_to_norm = list(normalize)
            for log_name in logs_to_norm:
                normalise_log(self.well_list, log_name,
                              output_name=f"{log_name}_norm")
                steps_done.append(f"normalise_{log_name}")

        # Electrofacies
        if electrofacies and electrofacies > 0:
            ef_logs = electrofacies_logs or [gr_name]
            compute_electrofacies(self.well_list, log_names=ef_logs,
                                  n_clusters=electrofacies)
            steps_done.append(f"electrofacies_k{electrofacies}")
            self.code_tables.setdefault("EF", {
                i: f"EF_{i}" for i in range(electrofacies)
            })

        # Biozones
        if biozones:
            read_biozone_csv(biozones, self.well_list)
            steps_done.append("biozones")

        self._record("condition", steps=steps_done)
        return self

    # ------------------------------------------------------------------
    # Step 3: Configure
    # ------------------------------------------------------------------

    def configure(
        self,
        *,
        preset: Optional[str] = None,
        depenv: Optional[str] = None,
        cost_logs: Optional[List[str]] = None,
        cost_weights: Optional[List[float]] = None,
        nbest: Optional[int] = None,
        order: Optional[str] = None,
        max_cor: Optional[int] = None,
        same_region: Optional[str] = None,
        no_crossing: Optional[str] = None,
        # §6 — Performance options (forwarded to C++ engine if supported)
        sakoe_chiba_band: Optional[int] = None,
        beam_width: Optional[int] = None,
        threads: Optional[int] = None,
        # §11 — Algorithm options
        cost_combination: Optional[str] = None,
        gap_cost_mode: Optional[str] = None,
        b3d_normalize: Optional[bool] = None,
        well_order: Optional[str] = None,
        dist_facies_groups: Optional[str] = None,
        # §12 — Hierarchical options
        var_window_size: Optional[int] = None,
        min_bed_thickness: Optional[float] = None,
        cost_floor: Optional[float] = None,
        custom_options: Optional[Dict[str, str]] = None,
    ) -> "CorrelationWorkflow":
        """Configure correlation parameters.

        Parameters
        ----------
        preset : str, optional
            One of: ``"shallow_marine"``, ``"shallow_marine_multi"``,
            ``"deep_marine"``, ``"fluvial"``, ``"carbonate"``, ``"default"``.
            Sets sensible defaults for the depositional environment.
        cost_logs : list[str], optional
            Data channels to use in cost function (max 5).
        cost_weights : list[float], optional
            Weights for each cost log.
        nbest : int, optional
            Number of n-best solutions (``nbr-cor``).
        order : str, optional
            Well order strategy: ``"pyramidal"``, ``"linear"``,
            ``"position"``, ``"distality"``, ``"inverse"``.
        max_cor : int, optional
            Maximum correlation graph size (``max-cor``).
        same_region : str, optional
            Region name for same-region constraint (e.g., ``"FACIES"``).
        no_crossing : str, optional
            Region name for no-crossing constraint.
        depenv : str, optional
            Depositional environment key or OSDU name (e.g.,
            ``"shallow_marine"``, ``"Turbidite"``).  Loads options from
            ``weco.depenv.DEPENV_PRESETS`` and substitutes logs based on
            available data.  Overridden by explicit parameters.
        custom_options : dict[str, str], optional
            Raw WeCo engine options (passed directly to ``set_option_ext``).

        Returns
        -------
        self
        """
        # Start from depositional environment preset (lowest priority)
        if depenv and not preset:
            try:
                from weco.depenv import suggest_options, normalise_depenv
                env_key = normalise_depenv(depenv) or depenv
                data_names = (list(self.well_list.get_data_names())
                              if self.well_list else None)
                env_opts = suggest_options(env_key, data_names)
                if env_opts:
                    self.preset_name = env_key
                    self.options = {}
                    for k, v in env_opts.items():
                        self.options[k.replace("_", "-")] = str(v)
                    self._record("depenv_preset", environment=env_key)
            except ImportError:
                logger.warning("weco.depenv not available — skipping depenv preset")

        # Start from preset if specified (overrides depenv)
        if preset:
            if preset not in PRESETS:
                raise ValueError(
                    f"Unknown preset '{preset}'. "
                    f"Available: {sorted(PRESETS.keys())}"
                )
            p = PRESETS[preset]
            self.preset_name = preset
            self.options = dict(p.get("options", {}))
            # Store logs/weights from preset as defaults
            if cost_logs is None:
                cost_logs = p.get("cost_logs")
            if cost_weights is None:
                cost_weights = p.get("cost_weights")
            if nbest is None:
                nbest = p.get("nbest")
            if order is None:
                order = p.get("order")

        # Override with explicit params
        if nbest is not None:
            self.options["nbr-cor"] = str(nbest)
        if max_cor is not None:
            self.options["max-cor"] = str(max_cor)
        if order is not None:
            self.options["order"] = order
        if same_region is not None:
            self.options["same-region"] = same_region
        if no_crossing is not None:
            self.options["no-crossing"] = no_crossing

        # §6 — Performance options
        if sakoe_chiba_band is not None:
            self.options["sakoe-chiba-band"] = str(sakoe_chiba_band)
        if beam_width is not None:
            self.options["beam-width"] = str(beam_width)
        if threads is not None:
            self.options["thread"] = str(threads)

        # §11 — Algorithm options
        if cost_combination is not None:
            self.options["cost-combination"] = cost_combination
        if gap_cost_mode is not None:
            self.options["gap-cost-mode"] = gap_cost_mode
        if b3d_normalize is not None:
            self.options["b3d-normalize"] = "true" if b3d_normalize else "false"
        if well_order is not None:
            self.options["well-order"] = well_order
        if dist_facies_groups is not None:
            self.options["dist-facies-groups"] = dist_facies_groups

        # §12 — Hierarchical options
        if var_window_size is not None:
            self.options["var-window-size"] = str(var_window_size)
        if min_bed_thickness is not None:
            self.options["min-bed-thickness"] = str(min_bed_thickness)
        if cost_floor is not None:
            self.options["cost-floor"] = str(cost_floor)

        # Store cost log configuration
        self._cost_logs = cost_logs or ["GR"]
        self._cost_weights = cost_weights or [1.0] * len(self._cost_logs)

        # Custom overrides
        if custom_options:
            self.options.update(custom_options)

        self._record("configure", preset=preset,
                      cost_logs=self._cost_logs,
                      cost_weights=self._cost_weights,
                      options=self.options)
        return self

    # ------------------------------------------------------------------
    # Step 3b: Apply Strat Column
    # ------------------------------------------------------------------

    def apply_strat_column(
        self,
        column,
        picks_per_well: Optional[Dict[str, list]] = None,
        *,
        add_no_crossing: bool = True,
    ) -> "CorrelationWorkflow":
        """Apply a stratigraphic column to loaded wells.

        Parameters
        ----------
        column : StratColumn or str or dict
            A :class:`weco.strat_column.StratColumn` instance, or a path
            to a JSON file, or a plain dict.
        picks_per_well : dict, optional
            ``{well_name: [{"unit_name": str, "top_md": float, "base_md": float}]}``
            If omitted, no rank regions are created but the column is stored.
        add_no_crossing : bool
            If True, horizon boundaries become no-crossing regions.

        Returns
        -------
        self
        """
        from weco.strat_column import StratColumn

        if isinstance(column, str):
            column = StratColumn.from_json(column)
        elif isinstance(column, dict):
            column = StratColumn.from_dict(column)

        self._strat_column = column

        if picks_per_well and self.well_list:
            result = column.apply_to_well_list(
                self.well_list, picks_per_well,
                add_no_crossing=add_no_crossing,
            )
            self._record("apply_strat_column",
                          column=column.name,
                          wells_applied=list(result.keys()))

            # Auto-set no-crossing option if horizons were added
            if add_no_crossing:
                self.options["no-crossing"] = "StratHorizons"
        else:
            self._record("apply_strat_column",
                          column=column.name,
                          wells_applied=[])

        return self

    # ------------------------------------------------------------------
    # Step 3c: Detect and Configure from Environment
    # ------------------------------------------------------------------

    def detect_and_configure(
        self,
        strat_column=None,
    ) -> "CorrelationWorkflow":
        """Auto-detect depositional environment and configure.

        If a strat column is provided (or was previously applied via
        ``apply_strat_column``), scans unit metadata for depositional
        environment fields and applies the matching preset.

        Parameters
        ----------
        strat_column : StratColumn, optional
            If None, uses the previously-applied column.

        Returns
        -------
        self
        """
        col = strat_column or getattr(self, "_strat_column", None)
        if col is None:
            logger.warning("No strat column available for environment detection")
            return self

        try:
            from weco.depenv import detect_environment
            env = detect_environment(col)
            if env:
                logger.info(f"Detected depositional environment: {env}")
                return self.configure(depenv=env)
            else:
                logger.info("No depositional environment detected in strat column")
        except ImportError:
            logger.warning("weco.depenv not available")

        return self

    # ------------------------------------------------------------------
    # Step 4: Run
    # ------------------------------------------------------------------

    def run(
        self,
        *,
        sensitivity_check: bool = False,
        options_file: Optional[str] = None,
    ) -> "CorrelationWorkflow":
        """Run the WeCo correlation engine.

        Parameters
        ----------
        sensitivity_check : bool
            If True, also runs a quick forward/reverse sensitivity check.
        options_file : str, optional
            Path to a WeCo options file.  Overrides all other config.

        Returns
        -------
        self
        """
        if self.well_list is None:
            raise RuntimeError("Import wells before running")

        from .ext import ProjectExt

        t0 = time.time()
        engine = ProjectExt()
        engine.reset_options()

        # Load options file if provided (must use absolute path)
        if options_file:
            abs_path = os.path.abspath(options_file)
            engine.option_load(abs_path)

        # Apply configured options (override file settings)
        for key, val in self.options.items():
            try:
                engine.set_option_ext(key, val)
            except ValueError as e:
                logger.warning(f"Option '{key}={val}': {e}")

        # Set cost logs using WeCo naming: var-data, var-data2, ..., var-data5
        # and var-weight, var-weight2, ..., var-weight5
        # Skip if an options file was loaded (it already defines data channels)
        if not options_file and hasattr(self, '_cost_logs') and self._cost_logs:
            for i, (log_name, weight) in enumerate(
                    zip(self._cost_logs, self._cost_weights)):
                suffix = "" if i == 0 else str(i + 1)
                try:
                    engine.set_option_ext(f"var-data{suffix}", log_name)
                    engine.set_option_ext(f"var-weight{suffix}", str(weight))
                except ValueError:
                    pass

        # Run
        success = engine.run(self.well_list)
        elapsed = time.time() - t0

        if success:
            self.res_file = engine.get_res_file()

        self._record("run", success=success, elapsed_s=round(elapsed, 2),
                      n_results=self.res_file.get_nbr_results()
                      if self.res_file else 0)

        # Optional sensitivity check
        if sensitivity_check and success:
            from .sensitivity import quick_order_check
            sens = quick_order_check(self.well_list, self.options)
            self._record("sensitivity_check", result=sens)

        return self

    # ------------------------------------------------------------------
    # Step 5: Validate
    # ------------------------------------------------------------------

    def validate(
        self,
        *,
        reference: Optional[str] = None,
        n_best_compare: int = 5,
    ) -> dict:
        """Validate and score the correlation result.

        Parameters
        ----------
        reference : str, optional
            Path to reference picks CSV for comparison.
        n_best_compare : int
            How many n-best paths to compare.

        Returns
        -------
        dict
            Quality assessment with scores.
        """
        if self.res_file is None:
            raise RuntimeError("Run correlation before validating")

        from .validate import (
            score_correlation_quality,
            compare_n_best,
        )
        from .export import correlation_summary

        # Quality scoring
        quality = score_correlation_quality(
            self.res_file, self.well_list,
            reference_file=reference,
        )

        # N-best comparison
        nbest_stats = compare_n_best(
            self.res_file, self.well_list,
            n_paths=n_best_compare,
        )

        # Correlation summary
        summary = correlation_summary(
            self.res_file, self.well_list,
            n_best=n_best_compare,
        )

        result = {
            "quality": quality,
            "n_best_comparison": nbest_stats,
            "summary": summary,
        }

        self._record("validate",
                      quality_score=quality.get("total_score"),
                      n_best_paths=len(nbest_stats))
        return result

    # ------------------------------------------------------------------
    # Step 6: Export
    # ------------------------------------------------------------------

    def export_rms(
        self,
        output_dir: str,
        *,
        cor_num: int = 0,
        depth_prop: Optional[str] = None,
        zone_names: Optional[dict[int, str]] = None,
        include_script: bool = True,
        include_points: bool = True,
    ) -> dict:
        """Export correlation results as an RMS-ready package.

        Creates a complete directory with well picks, zonation logs,
        horizon points, summary, and an RMS Python import script.

        Parameters
        ----------
        output_dir : str
            Output directory.
        cor_num : int
            Which n-best path to export.
        depth_prop : str, optional
            Depth data channel name.
        zone_names : dict[int, str], optional
            Custom zone name mapping.
        include_script : bool
            Generate RMS Python import script.
        include_points : bool
            Generate horizon XYZ point files.

        Returns
        -------
        dict
            Manifest of exported files.
        """
        if self.res_file is None:
            raise RuntimeError("Run correlation before exporting")

        from .rms_export import export_rms_package

        manifest = export_rms_package(
            self.res_file, self.well_list, output_dir,
            cor_num=cor_num,
            depth_prop=depth_prop,
            zone_names=zone_names,
            include_script=include_script,
            include_points=include_points,
        )

        # Also export code tables if we have them
        if self.code_tables:
            from .rms_export import export_rms_code_table
            ct_dir = os.path.join(output_dir, "code_tables")
            os.makedirs(ct_dir, exist_ok=True)
            for rname, table in self.code_tables.items():
                ct_path = os.path.join(ct_dir, f"{rname}_codes.txt")
                export_rms_code_table(table, ct_path, table_name=rname)
            manifest["code_tables"] = ct_dir

        self._record("export_rms", output_dir=output_dir,
                      cor_num=cor_num, files=manifest)
        return manifest

    def export_csv(
        self,
        output_dir: str,
        *,
        cor_num: int = 0,
        depth_prop: Optional[str] = None,
    ) -> dict:
        """Export correlation results as CSV files.

        Parameters
        ----------
        output_dir : str
            Output directory.
        cor_num : int
            Which n-best path.
        depth_prop : str, optional
            Depth channel.

        Returns
        -------
        dict
            Paths of created files.
        """
        if self.res_file is None:
            raise RuntimeError("Run correlation before exporting")

        from .export import (
            res_to_zonation_log, res_to_horizon_picks,
            export_zonation_csv, export_horizon_picks_csv,
            export_horizon_picks_json,
        )

        os.makedirs(output_dir, exist_ok=True)

        zonation = res_to_zonation_log(self.res_file, self.well_list,
                                       cor_num=cor_num, depth_prop=depth_prop)
        picks = res_to_horizon_picks(self.res_file, self.well_list,
                                     cor_num=cor_num, depth_prop=depth_prop)

        z_path = export_zonation_csv(zonation,
                                     os.path.join(output_dir, "zonation.csv"))
        p_path = export_horizon_picks_csv(picks,
                                          os.path.join(output_dir, "picks.csv"))
        j_path = export_horizon_picks_json(picks,
                                           os.path.join(output_dir, "picks.json"))

        paths = {
            "zonation_csv": z_path,
            "picks_csv": p_path,
            "picks_json": j_path,
        }
        self._record("export_csv", output_dir=output_dir, files=paths)
        return paths

    def export_rddms(
        self,
        url: str,
        token: str,
        dataspace: str,
        *,
        cor_num: int = 0,
        depth_prop: Optional[str] = None,
        max_horizons: int = 0,
        include_strat_column: bool = True,
        zone_names: Optional[dict[int, str]] = None,
        partition: str = "",
        crs=None,
    ) -> int:
        """Export correlation results to RDDMS as markers + strat column.

        Parameters
        ----------
        url, token, dataspace : RDDMS connection
        cor_num : int
            N-best path to export.
        include_strat_column : bool
            Also upload a StratigraphicColumn object.
        zone_names : dict[int, str], optional
            Custom zone names.

        Returns
        -------
        int
            Number of objects written.
        """
        if self.res_file is None:
            raise RuntimeError("Run correlation before exporting")

        from .rddms import rddms_export_results

        n = rddms_export_results(
            url, token, dataspace,
            self.res_file, self.well_list,
            cor_num=cor_num,
            depth_prop=depth_prop,
            max_horizons=max_horizons,
            include_strat_column=include_strat_column,
            zone_names=zone_names,
            partition=partition,
            crs=crs,
        )
        self._record("export_rddms", url=url, dataspace=dataspace,
                      n_objects=n, cor_num=cor_num)
        return n

    def export_epc(
        self,
        epc_path: str,
        *,
        cor_num: int = 0,
        depth_prop: Optional[str] = None,
        max_horizons: int = 0,
        include_strat_column: bool = True,
        zone_names: Optional[dict[int, str]] = None,
    ) -> str:
        """Export correlation results to a RESQML EPC file.

        Uses the GOCAD RESQML bridge for full marker + strat column
        support.

        Parameters
        ----------
        epc_path : str
            Output .epc file.
        cor_num : int
            N-best path index.
        include_strat_column : bool
            Include StratigraphicColumn.
        zone_names : dict[int, str], optional
            Custom zone names.

        Returns
        -------
        str
            Output EPC path.
        """
        if self.res_file is None:
            raise RuntimeError("Run correlation before exporting")

        from .rddms import epc_export_results

        path = epc_export_results(
            epc_path,
            self.res_file, self.well_list,
            cor_num=cor_num,
            depth_prop=depth_prop,
            max_horizons=max_horizons,
            include_strat_column=include_strat_column,
            zone_names=zone_names,
        )
        self._record("export_epc", epc_path=path, cor_num=cor_num)
        return path

    def export_gocad(
        self,
        path: str,
    ) -> str:
        """Export wells to GOCAD ASCII well format.

        Parameters
        ----------
        path : str
            Output .wl file.

        Returns
        -------
        str
            Output path.
        """
        if self.well_list is None:
            raise RuntimeError("Import wells before exporting")

        from .rddms import gocad_export_wells

        gocad_export_wells(self.well_list, path)
        self._record("export_gocad", path=path,
                      n_wells=len(self.well_list.wells))
        return path

    def export_las(
        self,
        output_dir: str,
        *,
        depth_name: str = "Depth",
        include_discrete: bool = True,
    ) -> list[str]:
        """Export wells to individual LAS 2.0 files.

        Parameters
        ----------
        output_dir : str
            Output directory.
        depth_name : str
            Depth data channel name.
        include_discrete : bool
            Include discrete logs.

        Returns
        -------
        list[str]
            Paths of created LAS files.
        """
        if self.well_list is None:
            raise RuntimeError("Import wells before exporting")

        from .rddms import las_export_wells

        paths = las_export_wells(
            self.well_list, output_dir,
            depth_name=depth_name,
            include_discrete=include_discrete,
        )
        self._record("export_las", output_dir=output_dir,
                      n_files=len(paths))
        return paths

    def export_marker_set(
        self,
        output_path: str,
        *,
        fmt: str = "csv",
        cor_num: int = 0,
        depth_prop: Optional[str] = None,
        include_xy: bool = True,
    ) -> str:
        """Export correlation markers in the specified format.

        Parameters
        ----------
        fmt : str
            ``"csv"``, ``"json"``, ``"gocad"``, ``"rms"``.

        Returns
        -------
        str
            Path to written file.
        """
        if self.res_file is None:
            raise RuntimeError("Run correlation before exporting")
        from .export import export_marker_set
        path = export_marker_set(
            self.res_file, self.well_list, output_path,
            fmt=fmt, cor_num=cor_num,
            depth_prop=depth_prop,
            include_xy=include_xy,
        )
        self._record("export_marker_set", path=path, fmt=fmt)
        return path

    def export_zone_thickness(
        self,
        output_path: str,
        *,
        cor_num: int = 0,
        depth_prop: Optional[str] = None,
        zone_names: list[str] | None = None,
        fmt: str = "csv",
    ) -> str:
        """Export per-well zone thickness table.

        Parameters
        ----------
        fmt : str
            ``"csv"`` or ``"rms"``.
        """
        if self.res_file is None:
            raise RuntimeError("Run correlation before exporting")
        from .export import export_zone_thickness_table
        path = export_zone_thickness_table(
            self.res_file, self.well_list, output_path,
            cor_num=cor_num,
            depth_prop=depth_prop,
            zone_names=zone_names,
            fmt=fmt,
        )
        self._record("export_zone_thickness", path=path, fmt=fmt)
        return path

    def export_ensemble(
        self,
        output_dir: str,
        *,
        n_best: int = 0,
        depth_prop: Optional[str] = None,
        fmt: str = "csv",
    ) -> list[str]:
        """Export top-N results as separate realisations.

        Returns
        -------
        list[str]
            Paths to realisation directories.
        """
        if self.res_file is None:
            raise RuntimeError("Run correlation before exporting")
        from .export import export_n_best_ensemble
        paths = export_n_best_ensemble(
            self.res_file, self.well_list, output_dir,
            n_best=n_best,
            depth_prop=depth_prop,
            fmt=fmt,
        )
        self._record("export_ensemble", n=len(paths), fmt=fmt)
        return paths

    def export_correlation_polylines(
        self,
        output_path: str,
        *,
        cor_num: int = 0,
        depth_prop: Optional[str] = None,
    ) -> str:
        """Export correlation horizons as GOCAD polylines (.pl)."""
        if self.res_file is None:
            raise RuntimeError("Run correlation before exporting")
        from .export import export_correlation_polylines
        path = export_correlation_polylines(
            self.res_file, self.well_list, output_path,
            cor_num=cor_num,
            depth_prop=depth_prop,
        )
        self._record("export_correlation_polylines", path=path)
        return path

    # ------------------------------------------------------------------
    # Report & provenance
    # ------------------------------------------------------------------

    def save_report(self, output_path: str) -> str:
        """Save a full provenance report as JSON.

        The report contains every step, parameter, and timing
        information — producing a fully reproducible record.

        Parameters
        ----------
        output_path : str
            Output JSON path.

        Returns
        -------
        str
            The output path.
        """
        report = {
            "study_name": self.name,
            "generated": datetime.now().isoformat(),
            "n_wells": len(self.well_list.wells) if self.well_list else 0,
            "well_names": [w.name for w in self.well_list.wells]
                          if self.well_list else [],
            "preset": self.preset_name,
            "options": self.options,
            "code_tables": self.code_tables,
            "steps": self._log,
            "data_channels": self._summarise_channels(),
        }

        os.makedirs(os.path.dirname(os.path.abspath(output_path)),
                     exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

        self._record("save_report", path=output_path)
        return output_path

    def _summarise_channels(self) -> dict:
        """Summarise available data/region channels across all wells."""
        if not self.well_list:
            return {}
        all_data = set()
        all_regions = set()
        per_well = {}
        for w in self.well_list.wells:
            all_data.update(w.data.keys())
            all_regions.update(w.region.keys())
            per_well[w.name] = {
                "size": w.size,
                "data": sorted(w.data.keys()),
                "regions": sorted(w.region.keys()),
                "x": w.x, "y": w.y,
            }
        return {
            "all_continuous": sorted(all_data),
            "all_discrete": sorted(all_regions),
            "per_well": per_well,
        }

    # ------------------------------------------------------------------
    # Convenience: presets info
    # ------------------------------------------------------------------

    @staticmethod
    def list_presets() -> Dict[str, str]:
        """Return available geological presets with descriptions."""
        return {k: v["description"] for k, v in PRESETS.items()}

    def __repr__(self) -> str:
        nw = len(self.well_list.wells) if self.well_list else 0
        has_res = self.res_file is not None
        return (f"CorrelationWorkflow('{self.name}', "
                f"wells={nw}, "
                f"correlated={'yes' if has_res else 'no'}, "
                f"steps={self._step_count})")

    # ------------------------------------------------------------------
    # JSON format I/O
    # ------------------------------------------------------------------

    def export_json(self, output_path: str, *, max_paths: int = 10) -> str:
        """Export the full project as WeCo JSON (OSDU-style schema).

        Parameters
        ----------
        output_path : str
            Output .weco.json path.
        max_paths : int
            Maximum number of result paths to include.

        Returns
        -------
        str
            The output path.
        """
        from .json_format import project_to_json, save_json

        if self.well_list is None:
            raise RuntimeError("Load wells before exporting")

        doc = project_to_json(
            self.well_list, self.options, self.res_file, max_paths=max_paths,
        )
        # Enrich with workflow provenance
        doc["meta"]["studyName"] = self.name
        doc["meta"]["preset"] = self.preset_name
        doc["meta"]["steps"] = len(self._log)

        save_json(doc, output_path)
        self._record("export_json", path=output_path)
        return output_path

    @classmethod
    def from_json(cls, path: str) -> "CorrelationWorkflow":
        """Load a workflow from a WeCo JSON project file.

        Parameters
        ----------
        path : str
            Path to a .weco.json file.

        Returns
        -------
        CorrelationWorkflow
            Workflow with wells and options loaded (results NOT re-run).
        """
        from .json_format import load_json, json_to_project

        doc = load_json(path)
        wl, opts, res = json_to_project(doc)

        name = doc.get("meta", {}).get("studyName", "imported")
        wf = cls(name=name)
        wf.well_list = wl
        wf.options = opts
        if res:
            wf.res_file = res
        return wf


# ---------------------------------------------------------------------------
# Quick-run functions (for scripting / CLI)
# ---------------------------------------------------------------------------

def quick_correlate(
    well_path: str,
    output_dir: str = "weco_output",
    *,
    preset: str = "shallow_marine",
    options_file: Optional[str] = None,
    **kwargs,
) -> dict:
    """One-call correlation from data file to RMS export.

    Parameters
    ----------
    well_path : str
        Path to well data file (LAS, WeCo, RESQML, CSV).
    output_dir : str
        Output directory for results.
    preset : str
        Geological preset name.
    options_file : str, optional
        WeCo options file (overrides preset).
    **kwargs
        Extra options for :meth:`CorrelationWorkflow.configure`.

    Returns
    -------
    dict
        Manifest of exported files.
    """
    wf = CorrelationWorkflow("Quick_Correlation")
    wf.import_wells(well_path)
    wf.condition()
    wf.configure(preset=preset, **kwargs)
    wf.run(options_file=options_file)
    manifest = wf.export_rms(output_dir)
    wf.save_report(os.path.join(output_dir, "report.json"))
    return manifest


# ---------------------------------------------------------------------------
# §11.9.4 — Transport Direction Sweep
# ---------------------------------------------------------------------------

def sweep_transport_direction(
    well_path: str,
    directions: Optional[List[float]] = None,
    preset: str = "default",
    **kwargs,
) -> List[dict]:
    """
    Run correlations at multiple transport direction angles and compare.

    Parameters
    ----------
    well_path : str
    directions : list of float, optional
        Angles in degrees. Defaults to [0, 45, 90, 135].
    preset : str
    **kwargs
        Passed to configure().

    Returns
    -------
    list of dict
        One entry per direction with cost, direction, n_results.
    """
    if directions is None:
        directions = [0.0, 45.0, 90.0, 135.0]

    results = []
    for angle in directions:
        wf = CorrelationWorkflow(f"sweep_{angle:.0f}")
        wf.import_wells(well_path)
        wf.condition()
        kw = dict(kwargs)
        kw["custom_options"] = kw.get("custom_options", {})
        kw["custom_options"]["transport-direction"] = str(angle)
        wf.configure(preset=preset, **kw)
        wf.run()

        cost = float("inf")
        n_res = 0
        if wf.res_file is not None:
            n_res = wf.res_file.get_nbr_results()
            if n_res > 0:
                cost = wf.res_file.get_result_cost(0)

        results.append({
            "direction": angle,
            "best_cost": cost,
            "n_results": n_res,
        })

    return results


# ---------------------------------------------------------------------------
# §11.10.3-11.10.4 — Posterior Analysis Utilities
# ---------------------------------------------------------------------------

def layer_geometry_check(
    res_file,
    well_list,
    cor_num: int = 0,
) -> dict:
    """
    §11.10.3 — Check layer geometry consistency (thickness variation).

    Returns
    -------
    dict
        thickness_cv (coefficient of variation) per horizon.
    """
    from weco.resfile import ResFile
    from weco.data import WellList
    import numpy as np

    if isinstance(res_file, str):
        rf = ResFile(res_file)
    else:
        rf = res_file
    if isinstance(well_list, str):
        wl = WellList(well_list)
    else:
        wl = well_list

    path = rf.get_result_full_path(cor_num) if rf.get_nbr_results() > cor_num else []
    if len(path) < 2:
        return {"horizons": []}

    horizons = []
    for hi in range(1, len(path)):
        thicknesses = []
        for w in range(rf.nbr_well()):
            s0 = path[hi - 1][w]
            s1 = path[hi][w]
            if s0 < 0 or s1 < 0:
                continue
            well = wl.wells[w] if w < len(wl.wells) else None
            if well is None:
                continue
            for dk in ("Depth", "DEPTH", "MD"):
                if dk in well.data:
                    d0 = well.data[dk][s0] if s0 < len(well.data[dk]) else 0
                    d1 = well.data[dk][s1] if s1 < len(well.data[dk]) else 0
                    thicknesses.append(abs(d1 - d0))
                    break

        if thicknesses:
            arr = np.array(thicknesses)
            cv = float(np.std(arr) / max(np.mean(arr), 1e-10))
            horizons.append({
                "horizon": hi,
                "mean_thickness": float(np.mean(arr)),
                "cv": cv,
                "n_wells": len(thicknesses),
            })

    return {"horizons": horizons}


def connectivity_analysis(
    res_file,
    well_list,
    cor_num: int = 0,
) -> dict:
    """
    §11.10.4 — Connectivity analysis: count connected components per layer.

    Returns
    -------
    dict
        n_components per horizon, total_connected fraction.
    """
    from weco.resfile import ResFile
    from weco.data import WellList

    if isinstance(res_file, str):
        rf = ResFile(res_file)
    else:
        rf = res_file
    if isinstance(well_list, str):
        wl = WellList(well_list)
    else:
        wl = well_list

    path = rf.get_result_full_path(cor_num) if rf.get_nbr_results() > cor_num else []
    if not path:
        return {"layers": [], "connected_fraction": 0.0}

    layers = []
    total_connected = 0
    total_pairs = 0

    for hi, node in enumerate(path):
        # Count wells that participate (non-gap)
        active = [w for w in range(len(node)) if node[w] >= 0]
        n_active = len(active)
        # Simple connectivity: all active wells are "connected" at this horizon
        n_components = 1 if n_active > 0 else 0
        layers.append({
            "horizon": hi,
            "n_active_wells": n_active,
            "n_components": n_components,
        })
        if n_active >= 2:
            total_connected += n_active * (n_active - 1) // 2
            total_pairs += rf.nbr_well() * (rf.nbr_well() - 1) // 2

    frac = total_connected / max(total_pairs, 1)

    return {
        "layers": layers,
        "connected_fraction": frac,
    }


# ---------------------------------------------------------------------------
# Exported API
# ---------------------------------------------------------------------------

__all__ = [
    "CorrelationWorkflow",
    "PRESETS",
    "quick_correlate",
    "sweep_transport_direction",
    "layer_geometry_check",
    "connectivity_analysis",
]
