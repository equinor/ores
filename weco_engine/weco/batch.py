#!/usr/bin/env python3
"""
weco_batch — Run WeCo correlation workflows from a JSON config file.
=====================================================================

Usage::

    python -m weco.batch config.json
    # or via shell wrapper:
    bin/weco_batch.sh config.json

JSON config format::

    {
        "wells": "path/to/wells.dat",
        "format": "weco",
        "options": {
            "cost_function": "composite",
            "var_data": "GR",
            "var_weight": 0.50,
            ...
        },
        "preset": "shallow_marine",
        "condition": true,
        "output_dir": "tmp/",
        "exports": ["csv", "las", "rms"],
        "multi_run": false,
        "runs": [
            {
                "name": "run_01",
                "wells": "path/to/wells_01.dat",
                "options": {"var_data": "GR"}
            }
        ]
    }

Supported ``format`` values: ``weco``, ``las``, ``csv``, ``resqml``, ``epc``.

Supported ``exports``: ``csv``, ``las``, ``rms``, ``epc``, ``gocad``,
``rddms``, ``marker_set``, ``zone_thickness``, ``ensemble``.

If ``preset`` is specified, it overrides matching keys in ``options``
(individual ``options`` keys take precedence over preset defaults).

If ``multi_run`` is true, each entry in ``runs`` is executed independently.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("weco.batch")


def _load_config(path: str) -> dict:
    """Load and validate a batch config JSON file."""
    with open(path) as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise ValueError(f"Config must be a JSON object, got {type(cfg).__name__}")
    return cfg


def _resolve_options(cfg: dict) -> dict:
    """Merge preset defaults with explicit options."""
    opts = {}

    # Apply preset first (lower priority)
    preset_key = cfg.get("preset")
    if preset_key:
        try:
            from weco.depenv import DEPENV_PRESETS
            preset = DEPENV_PRESETS.get(preset_key, {})
            opts.update(preset.get("recommended_opts", {}))
        except ImportError:
            logger.warning(f"Cannot load preset {preset_key} — depenv not available")

    # Explicit options override preset
    opts.update(cfg.get("options", {}))
    return opts


def _run_single(cfg: dict, output_dir: str, run_name: str = "") -> dict:
    """Execute a single correlation workflow from config."""
    from weco.workflow import CorrelationWorkflow

    wf = CorrelationWorkflow()

    # --- Import ---
    wells_path = cfg.get("wells", "")
    fmt = cfg.get("format", "weco").lower()

    if not wells_path:
        raise ValueError("Config must specify 'wells' path.")

    if fmt == "las":
        wf.import_las(wells_path)
    elif fmt == "csv":
        wf.import_csv(wells_path)
    elif fmt in ("resqml", "epc"):
        wf.import_resqml(wells_path)
    else:
        wf.import_wells(wells_path)

    # --- Condition ---
    if cfg.get("condition", True):
        wf.condition()

    # --- Configure ---
    opts = _resolve_options(cfg)
    if opts:
        wf.configure(**opts)

    # --- Run ---
    t0 = time.time()
    wf.run()
    elapsed = time.time() - t0

    # --- Export ---
    os.makedirs(output_dir, exist_ok=True)
    exports = cfg.get("exports", ["csv"])
    export_results = {}

    for exp in exports:
        try:
            exp_path = os.path.join(output_dir, run_name) if run_name else output_dir
            os.makedirs(exp_path, exist_ok=True)

            if exp == "csv":
                wf.export_csv(os.path.join(exp_path, "result.csv"))
                export_results["csv"] = True
            elif exp == "las":
                wf.export_las(exp_path)
                export_results["las"] = True
            elif exp == "rms":
                wf.export_rms(os.path.join(exp_path, "rms_picks.txt"))
                export_results["rms"] = True
            elif exp == "epc":
                wf.export_epc(os.path.join(exp_path, "result.epc"))
                export_results["epc"] = True
            elif exp == "gocad":
                wf.export_gocad(exp_path)
                export_results["gocad"] = True
            elif exp == "marker_set":
                wf.export_marker_set(os.path.join(exp_path, "markers.json"))
                export_results["marker_set"] = True
            elif exp == "zone_thickness":
                wf.export_zone_thickness(os.path.join(exp_path, "zones.csv"))
                export_results["zone_thickness"] = True
            elif exp == "ensemble":
                wf.export_ensemble(exp_path)
                export_results["ensemble"] = True
            else:
                logger.warning(f"Unknown export format: {exp}")
                export_results[exp] = False
        except Exception as e:
            logger.error(f"Export '{exp}' failed: {e}")
            export_results[exp] = False

    return {
        "run_name": run_name or "default",
        "wells": wells_path,
        "format": fmt,
        "n_wells": wf.well_list.nbr_wells() if wf.well_list else 0,
        "elapsed_s": round(elapsed, 2),
        "exports": export_results,
        "output_dir": output_dir,
    }


def run_batch(config_path: str) -> List[dict]:
    """Execute a batch workflow from a JSON config file.

    Returns a list of result dicts (one per run).
    """
    cfg = _load_config(config_path)
    output_dir = cfg.get("output_dir", "weco_output")
    results = []

    if cfg.get("multi_run") and "runs" in cfg:
        for i, run_cfg in enumerate(cfg["runs"]):
            merged = {**cfg, **run_cfg}
            merged.pop("runs", None)
            merged.pop("multi_run", None)
            name = run_cfg.get("name", f"run_{i:03d}")
            logger.info(f"=== Batch run: {name} ===")
            try:
                r = _run_single(merged, output_dir, run_name=name)
                results.append(r)
            except Exception as e:
                logger.error(f"Run {name} failed: {e}")
                results.append({"run_name": name, "error": str(e)})
    else:
        r = _run_single(cfg, output_dir)
        results.append(r)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="WeCo batch correlation workflow runner.",
    )
    parser.add_argument(
        "config", help="Path to JSON config file.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable verbose logging.",
    )
    parser.add_argument(
        "-o", "--output", default=None,
        help="Override output directory.",
    )
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if not os.path.isfile(args.config):
        logger.error(f"Config file not found: {args.config}")
        sys.exit(1)

    # Override output dir if provided
    if args.output:
        cfg = _load_config(args.config)
        cfg["output_dir"] = args.output
        # Write temp modified config
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(cfg, f)
            tmp_path = f.name
        try:
            results = run_batch(tmp_path)
        finally:
            os.unlink(tmp_path)
    else:
        results = run_batch(args.config)

    # Print summary
    print("\n" + "=" * 60)
    print("WeCo Batch — Summary")
    print("=" * 60)
    for r in results:
        if "error" in r:
            print(f"  FAIL  {r['run_name']}: {r['error']}")
        else:
            print(
                f"  OK    {r['run_name']}: "
                f"{r['n_wells']} wells, {r['elapsed_s']}s, "
                f"exports={list(r.get('exports', {}).keys())}"
            )
    print("=" * 60)

    # Exit with error if any run failed
    if any("error" in r for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
