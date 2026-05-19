#!/usr/bin/env python3
"""
generate_payloads.py — Generate RESQML JSON payloads for RDDMS ingestion
=========================================================================

Reads WeCo demo datasets (shallow marine, coal, quaternary) and produces
RDDMS-compatible RESQML JSON files for well trajectories, logs, and markers.

These payloads can be ingested into any RDDMS instance (eqndev, preship,
interop) using the ``ingest_wells.py`` script.

Output structure::

    demo/resqml/payloads/
        shallow_marine/
            wells.json          ← array of WellboreTrajectoryRepresentation
            logs.json           ← array of ContinuousProperty per well
            markers.json        ← WellboreMarkerFrameRepresentation (biozones)
        coal/
            wells.json
            logs.json
        quaternary/
            wells.json
            logs.json

Usage::

    python demo/resqml/generate_payloads.py
    python demo/resqml/generate_payloads.py --dataset shallow_marine
    python demo/resqml/generate_payloads.py --output-dir /tmp/payloads
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ═══════════════════════════════════════════════════════════════════════════
#  RESQML JSON builders
# ═══════════════════════════════════════════════════════════════════════════

def _uuid() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_wellbore_trajectory(well, dataset_name: str) -> dict:
    """Build a WellboreTrajectoryRepresentation JSON object."""
    depth = well.data.get("DEPTH") or well.data.get("Depth") or []
    n = len(depth)

    # Get XYZ — use header coords if no per-point data
    xs = well.data.get("X") or well.data.get("x") or [well.x] * n
    ys = well.data.get("Y") or well.data.get("y") or [well.y] * n

    # MD = depth channel
    md_values = list(depth)

    # TVD — for vertical wells, TVD ≈ MD
    tvd_values = md_values.copy()

    return {
        "schemaVersion": "1.0.0",
        "kind": "resqml20:obj_WellboreTrajectoryRepresentation",
        "uuid": _uuid(),
        "title": well.name,
        "citation": {
            "title": well.name,
            "creation": _now_iso(),
            "originator": "WeCo Demo Ingestion",
            "format": "WeCo RESQML Payload Generator",
        },
        "data": {
            "Name": well.name,
            "Description": f"WeCo demo well — {dataset_name}",
            "WellboreName": well.name,
            "DatasetName": dataset_name,
            "MdUom": "m",
            "StartMd": md_values[0] if md_values else 0.0,
            "FinishMd": md_values[-1] if md_values else 0.0,
            "MeasuredDepths": md_values,
            "Tvds": tvd_values,
            "Eastings": list(xs)[:n],
            "Northings": list(ys)[:n],
            "SpatialLocation": {
                "Wgs84Coordinates": {
                    "x": well.x,
                    "y": well.y,
                },
            },
            "KbElevation": abs(well.z) if well.z else 0.0,
        },
        "meta": {
            "dataspace": f"maap/weco",
            "dataset": dataset_name,
            "wellCount": 1,
        },
    }


def build_continuous_property(well, log_name: str, values: list,
                              traj_uuid: str) -> dict:
    """Build a ContinuousProperty JSON object for a well log."""
    # Determine UOM from log name
    uom_map = {
        "GR": "gAPI",
        "RT": "ohm.m",
        "RHOB": "g/cm3",
        "NPHI": "v/v",
        "DT": "us/ft",
        "DEPTH": "m",
    }
    uom = uom_map.get(log_name.upper(), "unitless")

    return {
        "schemaVersion": "1.0.0",
        "kind": "resqml20:obj_ContinuousProperty",
        "uuid": _uuid(),
        "title": f"{well.name}_{log_name}",
        "citation": {
            "title": f"{log_name} for {well.name}",
            "creation": _now_iso(),
            "originator": "WeCo Demo Ingestion",
        },
        "data": {
            "Name": log_name,
            "WellboreName": well.name,
            "Uom": uom,
            "IndexableElement": "nodes",
            "Count": len(values),
            "Values": values,
            "MinimumValue": min(values) if values else 0.0,
            "MaximumValue": max(values) if values else 0.0,
            "SupportingRepresentationUuid": traj_uuid,
        },
    }


def build_discrete_property(well, region_name: str, values: list,
                            traj_uuid: str, code_table: dict = None) -> dict:
    """Build a DiscreteProperty JSON object for a well region."""
    int_values = [int(v) for v in values]
    obj = {
        "schemaVersion": "1.0.0",
        "kind": "resqml20:obj_DiscreteProperty",
        "uuid": _uuid(),
        "title": f"{well.name}_{region_name}",
        "citation": {
            "title": f"{region_name} for {well.name}",
            "creation": _now_iso(),
            "originator": "WeCo Demo Ingestion",
        },
        "data": {
            "Name": region_name,
            "WellboreName": well.name,
            "IndexableElement": "intervals",
            "Count": len(int_values),
            "Values": int_values,
            "SupportingRepresentationUuid": traj_uuid,
        },
    }
    if code_table:
        obj["data"]["Lookup"] = code_table
    return obj


def build_marker_frame(well, markers: dict, traj_uuid: str) -> dict:
    """Build a WellboreMarkerFrameRepresentation from biozone markers."""
    marker_list = []
    for name, depth in markers.items():
        marker_list.append({
            "uuid": _uuid(),
            "title": name,
            "MarkerMd": depth,
            "GeologicBoundaryKind": "horizon",
        })

    return {
        "schemaVersion": "1.0.0",
        "kind": "resqml20:obj_WellboreMarkerFrameRepresentation",
        "uuid": _uuid(),
        "title": f"{well.name}_markers",
        "citation": {
            "title": f"Markers for {well.name}",
            "creation": _now_iso(),
            "originator": "WeCo Demo Ingestion",
        },
        "data": {
            "WellboreName": well.name,
            "WellboreTrajectoryUuid": traj_uuid,
            "Markers": marker_list,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Dataset processing
# ═══════════════════════════════════════════════════════════════════════════

DATASETS = {
    "shallow_marine": {
        "path": "demo/data/data_set_shallow_marine/wells.txt",
        "title": "Shallow Marine (Hugin Fm analogue)",
        "logs": ["GR", "RT", "RHOB", "NPHI", "DT"],
        "regions": ["FACIES", "BIOZONE"],
    },
    "coal": {
        "path": "demo/data/data_set_coal/wells_10.txt",
        "title": "Coal Basin Seam Correlation",
        "logs": ["GR", "RT", "RHOB"],
        "regions": [],
    },
    "quaternary": {
        "path": "demo/data/data_set_quaternary/wells_20.txt",
        "title": "Quaternary Hydrogeology",
        "logs": ["GR", "RT"],
        "regions": [],
    },
}


def process_dataset(dataset_name: str, output_dir: Path) -> dict:
    """Process one demo dataset and write RESQML JSON payloads."""
    from weco.data import WellList

    ds = DATASETS[dataset_name]
    wells_path = PROJECT_ROOT / ds["path"]

    if not wells_path.exists():
        # Try generating if generator exists
        gen_path = wells_path.parent / f"generate_{dataset_name}.py"
        if gen_path.exists():
            print(f"  Generating {dataset_name} data...")
            import importlib.util
            spec = importlib.util.spec_from_file_location("gen", str(gen_path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "main"):
                mod.main(output_dir=str(wells_path.parent))

    if not wells_path.exists():
        print(f"  SKIP: {wells_path} not found")
        return {}

    wl = WellList(str(wells_path))
    print(f"  Loaded {wl.nbr_wells()} wells from {wells_path.name}")

    out_dir = output_dir / dataset_name
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build trajectory payloads
    trajectories = []
    all_logs = []
    all_regions = []
    all_markers = []

    skip_channels = {"DEPTH", "MD", "X", "Y", "Z", "x", "y", "z",
                     "XCOOR", "YCOOR", "Xcoor", "Ycoor"}

    for w in wl.wells:
        traj = build_wellbore_trajectory(w, dataset_name)
        trajectories.append(traj)
        traj_uuid = traj["uuid"]

        # Continuous logs
        for dname, dvals in w.data.items():
            if dname.upper() in skip_channels or dname.startswith("_"):
                continue
            if dname in w.region:
                continue  # discrete — handled below
            values = [float(v) for v in dvals]
            if values:
                prop = build_continuous_property(w, dname, values, traj_uuid)
                all_logs.append(prop)

        # Discrete regions
        for rname in w.region:
            if rname in w.data:
                values = list(w.data[rname])
                code_table = w.data.get(f"_code_table_{rname}")
                prop = build_discrete_property(
                    w, rname, values, traj_uuid,
                    code_table=code_table if isinstance(code_table, dict) else None,
                )
                all_regions.append(prop)

    # Write JSON payloads
    summary = {"dataset": dataset_name, "wells": len(trajectories)}

    _write_json(out_dir / "wells.json", trajectories)
    summary["well_objects"] = len(trajectories)
    print(f"    → {len(trajectories)} trajectory objects → wells.json")

    if all_logs:
        _write_json(out_dir / "logs.json", all_logs)
        summary["log_objects"] = len(all_logs)
        print(f"    → {len(all_logs)} log property objects → logs.json")

    if all_regions:
        _write_json(out_dir / "regions.json", all_regions)
        summary["region_objects"] = len(all_regions)
        print(f"    → {len(all_regions)} region property objects → regions.json")

    if all_markers:
        _write_json(out_dir / "markers.json", all_markers)
        summary["marker_objects"] = len(all_markers)
        print(f"    → {len(all_markers)} marker objects → markers.json")

    return summary


def _write_json(path: Path, data: list):
    """Write JSON array to file (compact but readable)."""
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Generate RESQML JSON payloads from WeCo demo datasets",
    )
    parser.add_argument(
        "--dataset", choices=list(DATASETS.keys()),
        help="Process only one dataset (default: all)",
    )
    parser.add_argument(
        "--output-dir", default=str(Path(__file__).parent / "payloads"),
        help="Output directory for JSON payloads",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  WeCo RESQML Payload Generator")
    print("=" * 60)

    datasets = [args.dataset] if args.dataset else list(DATASETS.keys())
    summaries = {}

    for ds_name in datasets:
        print(f"\n[{ds_name}] Processing...")
        summary = process_dataset(ds_name, output_dir)
        if summary:
            summaries[ds_name] = summary

    # Write manifest
    manifest = {
        "generated": _now_iso(),
        "generator": "demo/resqml/generate_payloads.py",
        "target_dataspace": "maap/weco",
        "datasets": summaries,
    }
    _write_json(output_dir / "manifest.json", [manifest])
    print(f"\n✓ Manifest written to {output_dir / 'manifest.json'}")
    print(f"  Target dataspace: maap/weco")
    print(f"  Datasets: {list(summaries.keys())}")


if __name__ == "__main__":
    main()
