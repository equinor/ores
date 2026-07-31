"""
gen_geolabelset.py - Generic GeoLabelSet from stat volumes.

Reads a STAT ReservoirEstimatedVolumes manifest and builds a GeoLabelSet
with per-segment volume labels (P10/P50/P90 for a chosen property).

Spec format:
{
  "generator": "geolabelset",
  "project": "Drogon",
  "stat_manifest": "manifest_wpcstat.json",
  "label_property": "Oil",
  "label_uom": "MSm3",
  "scale_divisor": 1e6,
  "masterwp_manifest": "..."
}
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from ._common import (
    load_ref,
    load_json, det_uuid,
    resolve_acl_legal, resolve_reservoir_id,
)
from ._registry import register


@register("geolabelset")
def generate(
    spec: Dict[str, Any],
    pfx: str,
    base_dir: Path,
    refs: Dict[str, Any],
) -> List[Dict[str, Any]]:
    stat_manifest = load_ref(spec, refs, "stat_manifest", "volumes_stat", base_dir)
    if not stat_manifest:
        raise ValueError("geolabelset needs 'stat_manifest' path or 'volumes_stat' in refs")

    masterwp = load_ref(spec, refs, "masterwp_manifest", "masterwp", base_dir)
    acl, legal = resolve_acl_legal(spec, pfx, masterwp)
    reservoir_id = resolve_reservoir_id(masterwp)

    project = spec.get("project", "")
    label_prop = spec.get("label_property", "Oil")
    label_uom = spec.get("label_uom", "MSm3")
    scale_div = spec.get("scale_divisor", 1e6)

    # Extract stat data
    wpc_list = stat_manifest["Data"]["WorkProductComponents"]
    stat_wpc = next(w for w in wpc_list if "ReservoirEstimatedVolumes" in w.get("kind", ""))
    volumes = stat_wpc["data"]["Volumes"]
    colvals = volumes["ColumnValues"]

    n = len(colvals.get("SegmentID", colvals.get("Zone", [])))
    rows = [{k: colvals[k][i] for k in colvals} for i in range(n)]

    # Find per-segment TOTAL rows
    labels: List[Dict[str, Any]] = []
    for row in rows:
        seg = row.get("SegmentID", "")
        zone = row.get("Zone", "")
        if zone != "TOTAL" or seg == "TOTAL":
            continue

        p50_key = f"{label_prop}.P50"
        p10_key = f"{label_prop}.P10"
        p90_key = f"{label_prop}.P90"

        p50 = row.get(p50_key, 0) or 0
        p10 = row.get(p10_key, 0) or 0
        p90 = row.get(p90_key, 0) or 0

        labels.append({
            "SegmentName": seg,
            "P50": round(p50 / scale_div, 2),
            "P10": round(p10 / scale_div, 2),
            "P90": round(p90 / scale_div, 2),
            "UnitOfMeasure": label_uom,
            "PropertyName": label_prop,
        })

    uid_pfx = spec.get("uuid_prefix", "geolabel")
    wpc_id = f"{pfx}:work-product-component--GeoLabelSet:{det_uuid(f'{uid_pfx}-gls')}:1"

    data: Dict[str, Any] = {
        "Name": f"{project} - GeoLabelSet ({label_prop} volumes)" if project else f"GeoLabelSet ({label_prop})",
        "Description": f"Per-segment volume labels ({label_prop} P10/P50/P90) derived from stat volumes",
        "Labels": labels,
    }
    if reservoir_id:
        data["ReservoirID"] = reservoir_id

    return [{
        "id": wpc_id,
        "kind": "osdu:wks:work-product-component--GeoLabelSet:1.0.0",
        "acl": acl, "legal": legal, "data": data,
    }]


