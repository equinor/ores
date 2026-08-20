#!/usr/bin/env python3
"""
generate_payloads.py - Generate RESQML JSON payloads for RDDMS ingestion
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
    """Build a WellboreTrajectoryRepresentation for RDDMS v2."""
    depth = well.data.get("DEPTH") or well.data.get("Depth") or []
    n = len(depth)

    # Get XYZ - use header coords if no per-point data
    xs = well.data.get("X") or well.data.get("x") or [well.x] * n
    ys = well.data.get("Y") or well.data.get("y") or [well.y] * n

    # MD = depth channel
    md_values = [float(v) for v in depth]

    # Build 3D control points (X, Y, Z=MD for vertical wells)
    control_points = []
    for i in range(n):
        control_points.extend([
            float(list(xs)[i]) if i < len(list(xs)) else well.x,
            float(list(ys)[i]) if i < len(list(ys)) else well.y,
            md_values[i] if i < len(md_values) else 0.0,
        ])

    return {
        "$type": "resqml20.obj_WellboreTrajectoryRepresentation",
        "SchemaVersion": "2.0",
        "Uuid": _uuid(),
        "Citation": {
            "$type": "eml20.Citation",
            "Title": well.name,
            "Originator": "WeCo Demo Ingestion",
            "Creation": _now_iso(),
            "Format": "WeCo RESQML Payload Generator",
        },
        "MdUom": "m",
        "StartMd": md_values[0] if md_values else 0.0,
        "FinishMd": md_values[-1] if md_values else 0.0,
        "Geometry": {
            "$type": "resqml20.ParametricLineGeometry",
            "controlPointParameters": md_values,
            "controlPoints": control_points,
        },
    }


def build_wellbore_frame(well, traj_uuid: str, md_values: list) -> dict:
    """Build a WellboreFrameRepresentation (log sample grid) for RDDMS v2."""
    return {
        "$type": "resqml20.obj_WellboreFrameRepresentation",
        "SchemaVersion": "2.0",
        "Uuid": _uuid(),
        "Citation": {
            "$type": "eml20.Citation",
            "Title": f"{well.name}_Logs",
            "Originator": "WeCo Demo Ingestion",
            "Creation": _now_iso(),
            "Format": "WeCo RESQML Payload Generator",
        },
        "NodeMd": {
            "Values": md_values,
            "UOM": "m",
        },
        "RepresentedInterpretation": {
            "$type": "eml20.DataObjectReference",
            "ContentType": "application/x-resqml+xml;version=2.0;type=obj_WellboreTrajectoryRepresentation",
            "UUID": traj_uuid,
            "Title": well.name,
        },
    }


def build_continuous_property(well, log_name: str, values: list,
                              frame_uuid: str) -> dict:
    """Build a ContinuousProperty for RDDMS v2."""
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
        "$type": "resqml20.obj_ContinuousProperty",
        "SchemaVersion": "2.0",
        "Uuid": _uuid(),
        "Citation": {
            "$type": "eml20.Citation",
            "Title": f"{well.name}_{log_name}",
            "Originator": "WeCo Demo Ingestion",
            "Creation": _now_iso(),
            "Format": "WeCo RESQML Payload Generator",
        },
        "PropertyKind": {
            "$type": "eml20.DataObjectReference",
            "Title": log_name,
        },
        "UOM": uom,
        "Count": 1,
        "IndexableElement": "nodes",
        "PatchOfValues": {
            "Values": [float(v) for v in values],
        },
        "SupportingRepresentation": {
            "$type": "eml20.DataObjectReference",
            "ContentType": "application/x-resqml+xml;version=2.0;type=obj_WellboreFrameRepresentation",
            "UUID": frame_uuid,
            "Title": f"{well.name}_{log_name}",
        },
    }


def build_discrete_property(well, region_name: str, values: list,
                            frame_uuid: str, code_table: dict = None) -> dict:
    """Build a DiscreteProperty for RDDMS v2."""
    int_values = [int(v) for v in values]
    obj = {
        "$type": "resqml20.obj_DiscreteProperty",
        "SchemaVersion": "2.0",
        "Uuid": _uuid(),
        "Citation": {
            "$type": "eml20.Citation",
            "Title": f"{well.name}_{region_name}",
            "Originator": "WeCo Demo Ingestion",
            "Creation": _now_iso(),
            "Format": "WeCo RESQML Payload Generator",
        },
        "PropertyKind": {
            "$type": "eml20.DataObjectReference",
            "Title": region_name,
        },
        "Count": 1,
        "IndexableElement": "cells",
        "PatchOfValues": {
            "Values": int_values,
        },
        "SupportingRepresentation": {
            "$type": "eml20.DataObjectReference",
            "ContentType": "application/x-resqml+xml;version=2.0;type=obj_WellboreFrameRepresentation",
            "UUID": frame_uuid,
            "Title": f"{well.name}_{region_name}",
        },
    }
    if code_table:
        obj["Lookup"] = code_table
    return obj


def build_marker_frame(well, markers: dict, traj_uuid: str) -> dict:
    """Build a WellboreMarkerFrameRepresentation for RDDMS v2."""
    marker_list = []
    for name, depth in markers.items():
        marker_list.append({
            "Uuid": _uuid(),
            "GeologicBoundaryKind": "horizon",
            "Label": name,
        })

    return {
        "$type": "resqml20.obj_WellboreMarkerFrameRepresentation",
        "SchemaVersion": "2.0",
        "Uuid": _uuid(),
        "Citation": {
            "$type": "eml20.Citation",
            "Title": f"{well.name}_markers",
            "Originator": "WeCo Demo Ingestion",
            "Creation": _now_iso(),
            "Format": "WeCo RESQML Payload Generator",
        },
        "WellboreMarker": marker_list,
        "NodeMd": {
            "Values": [depth for _, depth in markers.items()],
            "UOM": "m",
        },
        "RepresentedInterpretation": {
            "$type": "eml20.DataObjectReference",
            "ContentType": "application/x-resqml+xml;version=2.0;type=obj_WellboreTrajectoryRepresentation",
            "UUID": traj_uuid,
            "Title": well.name,
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
    "distality": {
        "path": "demo/data/data_set_distality/wells.txt",
        "title": "Distality Cost (Walther's Law)",
        "logs": ["DISTAL"],
        "regions": ["FACIES_1", "FACIES_2", "FACIES_3", "FACIES_4", "BIOZONES"],
    },
    "biozone_distality": {
        "path": "demo/data/data_set_biozone_distality/wells.txt",
        "title": "Biozone No-Crossing + Distality",
        "logs": ["DISTAL"],
        "regions": ["FACIES_1", "FACIES_2", "FACIES_3", "FACIES_4", "BIOZONES"],
    },
    "bryson": {
        "path": "demo/data/data_set_bryson/wells.txt",
        "title": "Bryson – Appalachian Basin",
        "logs": ["MD"],
        "regions": ["FACIES", "ZONE", "DISTALITY", "SEQSTRAT"],
    },
    "fluvial": {
        "path": "demo/data/data_set_fluvial/wells.txt",
        "title": "Fluvial – Channel Belt",
        "logs": ["GR"],
        "regions": ["FACIES"],
    },
    "delta": {
        "path": "demo/data/data_set_delta/wells.txt",
        "title": "Delta – Deltaic System",
        "logs": ["GR", "DEN", "NPHI"],
        "regions": ["FACIES", "SEQSTRAT"],
    },
    "sigrun": {
        "path": "demo/data/data_set_sigrun/wells.txt",
        "title": "Sigrun – North Sea",
        "logs": ["GR", "NPHI"],
        "regions": ["FACIES", "BIOZONE", "DISTALITY", "SEQUENCE"],
    },
    "troll": {
        "path": "demo/data/data_set_troll/wells.txt",
        "title": "Troll – North Sea",
        "logs": ["MD"],
        "regions": ["FACIES", "BIOZONE", "DISTALITY", "SEQUENCE"],
    },
    "hugin_tidal": {
        "path": "demo/data/data_set_hugin_tidal/facies.wells.txt",
        "title": "Hugin Fm – Tidal Distality (Real Wells)",
        "logs": ["DISTALITY"],
        "regions": ["FACIES_1", "FACIES_2", "FACIES1", "FACIES2", "BIOZONES"],
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
    frames = []
    all_logs = []
    all_regions = []
    all_markers = []

    skip_channels = {"DEPTH", "MD", "X", "Y", "Z", "x", "y", "z",
                     "XCOOR", "YCOOR", "Xcoor", "Ycoor"}

    for w in wl.wells:
        traj = build_wellbore_trajectory(w, dataset_name)
        trajectories.append(traj)
        traj_uuid = traj["Uuid"]

        # Build sample grid (frame) - needed for log properties
        depth = w.data.get("DEPTH") or w.data.get("Depth") or []
        md_values = [float(v) for v in depth]
        frame = build_wellbore_frame(w, traj_uuid, md_values)
        frames.append(frame)
        frame_uuid = frame["Uuid"]

        # Continuous logs
        for dname, dvals in w.data.items():
            if dname.upper() in skip_channels or dname.startswith("_"):
                continue
            if dname in w.region:
                continue  # discrete - handled below
            values = [float(v) for v in dvals]
            if values:
                prop = build_continuous_property(w, dname, values, frame_uuid)
                all_logs.append(prop)

        # Discrete regions
        for rname in w.region:
            if rname in w.data:
                values = list(w.data[rname])
                code_table = w.data.get(f"_code_table_{rname}")
                prop = build_discrete_property(
                    w, rname, values, frame_uuid,
                    code_table=code_table if isinstance(code_table, dict) else None,
                )
                all_regions.append(prop)

    # Write JSON payloads
    summary = {"dataset": dataset_name, "wells": len(trajectories)}

    _write_json(out_dir / "wells.json", trajectories + frames)
    summary["well_objects"] = len(trajectories) + len(frames)
    print(f"    → {len(trajectories)} trajectories + {len(frames)} frames → wells.json")

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
