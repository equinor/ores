"""
gen_master.py - Generic Reservoir + ReservoirSegment + WorkProduct generator.

Spec format:
{
  "generator": "master",
  "reservoir_name": "Drogon",
  "reservoir_description": "Drogon field - Valysar formation",
  "segments": [
    {"key": "WestLowland", "name": "West Lowland", "description": "..."},
    ...
  ],
  // OR read segments from CSV:
  "csv_file": "valysar_volumes.csv",
  "csv_segment_column": "SegmentID"
}
"""
from __future__ import annotations

import csv
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._common import (
    default_acl, default_legal, det_uuid, md_id,
)
from ._registry import register


@register("master")
def generate(
    spec: Dict[str, Any],
    pfx: str,
    base_dir: Path,
    refs: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Generate Reservoir + ReservoirSegment + WorkProduct records."""
    reservoir_name = spec["reservoir_name"]
    reservoir_desc = spec.get("reservoir_description", f"Reservoir {reservoir_name}")
    acl = spec.get("acl") or default_acl(pfx)
    legal = spec.get("legal") or default_legal(pfx)
    uid_pfx = spec.get("uuid_prefix", reservoir_name)

    # Get segments from spec or CSV
    segments = _resolve_segments(spec, base_dir)

    reservoir_id = md_id(pfx, "Reservoir", det_uuid(f"{uid_pfx}-reservoir"))
    wp_id_val = f"{pfx}:work-product:{det_uuid(f'{uid_pfx}-wp')}:1"

    master_data: List[Dict] = []
    segment_ids: List[str] = []

    # Build segment records
    for seg in segments:
        seg_id = md_id(pfx, "ReservoirSegment", det_uuid(f"{uid_pfx}-seg-{seg.get('key', seg['name'])}"))
        segment_ids.append(seg_id)
        master_data.append({
            "id": seg_id,
            "kind": "osdu:wks:master-data--ReservoirSegment:2.0.0",
            "acl": acl,
            "legal": legal,
            "data": {
                "Name": seg["name"],
                "Description": seg.get("description", f"Reservoir segment {seg['name']} of {reservoir_name}"),
                "ancestry": {"parents": [reservoir_id], "children": []},
            },
        })

    # Build Reservoir record
    master_data.insert(0, {
        "id": reservoir_id,
        "kind": "osdu:wks:master-data--Reservoir:2.0.0",
        "acl": acl,
        "legal": legal,
        "data": {
            "Name": reservoir_name,
            "Description": reservoir_desc,
            "ancestry": {"parents": [], "children": segment_ids},
        },
    })

    # Build WorkProduct
    records = list(master_data)
    records.append({
        "id": wp_id_val,
        "kind": "osdu:wks:work-product:1.0.0",
        "acl": acl,
        "legal": legal,
        "data": {
            "Name": f"{reservoir_name} Reservoir Study",
            "Description": f"Parent WorkProduct for {reservoir_name} estimated volumes",
            "WorkflowStatus": "Active",
            "ancestry": {"parents": [reservoir_id], "children": []},
        },
    })

    return records


def _resolve_segments(spec: Dict, base_dir: Path) -> List[Dict[str, str]]:
    """Get segments from inline list or CSV file."""
    if "segments" in spec:
        return spec["segments"]

    csv_file = spec.get("csv_file")
    if csv_file:
        csv_path = base_dir / csv_file
        if not csv_path.exists():
            repo_root = Path(__file__).resolve().parent.parent.parent.parent
            alt = repo_root / csv_file
            if alt.exists():
                csv_path = alt
        segment_col = spec.get("csv_segment_column", "SegmentID")
        name_map = spec.get("segment_names", {})

        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        seen: OrderedDict = OrderedDict()
        for r in rows:
            seg = r.get(segment_col, "").strip()
            if seg and seg not in seen:
                seen[seg] = None

        return [
            {"key": s, "name": name_map.get(s, s)}
            for s in seen
        ]

    raise ValueError("master spec needs 'segments' list or 'csv_file'")
