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
    masterwp = load_ref(spec, refs, "masterwp_manifest", "masterwp", base_dir)
    acl, legal = resolve_acl_legal(spec, pfx, masterwp)
    reservoir_id = resolve_reservoir_id(masterwp) or spec.get("reservoir_id", "")

    project = spec.get("project", "")
    label_prop = spec.get("label_property", "Oil")
    label_uom = spec.get("label_uom", "MSm3")
    scale_div = spec.get("scale_divisor", 1e6)

    # ── Source A: inline labels (no manifest needed) ──
    if spec.get("labels"):
        labels = []
        for seg in spec["labels"]:
            labels.append({
                "SegmentName": seg["segment"],
                "P50": seg.get("P50", 0),
                "P10": seg.get("P10", 0),
                "P90": seg.get("P90", 0),
                "UnitOfMeasure": seg.get("uom", label_uom),
                "PropertyName": seg.get("property", label_prop),
            })
    else:
        # ── Source B: from stat REV manifest ──
        stat_manifest = load_ref(spec, refs, "stat_manifest", "volumes_stat", base_dir)
        if not stat_manifest:
            raise ValueError("geolabelset needs 'labels' (inline) or 'stat_manifest' / 'volumes_stat' ref")

        wpc_list = stat_manifest["Data"]["WorkProductComponents"]
        stat_wpc = next(w for w in wpc_list if "ReservoirEstimatedVolumes" in w.get("kind", ""))
        volumes = stat_wpc["data"]["Volumes"]
        colvals = volumes["ColumnValues"]

        n = len(colvals.get("SegmentID", colvals.get("Zone", [])))
        rows = [{k: colvals[k][i] for k in colvals} for i in range(n)]

        labels = []
        for row in rows:
            seg = row.get("SegmentID", "")
            zone = row.get("Zone", "")
            if zone != "TOTAL" or seg == "TOTAL":
                continue

            p50 = row.get(f"{label_prop}.P50", 0) or 0
            p10 = row.get(f"{label_prop}.P10", 0) or 0
            p90 = row.get(f"{label_prop}.P90", 0) or 0

            labels.append({
                "SegmentName": seg,
                "P50": round(p50 / scale_div, 2),
                "P10": round(p10 / scale_div, 2),
                "P90": round(p90 / scale_div, 2),
                "UnitOfMeasure": label_uom,
                "PropertyName": label_prop,
            })

    uid_pfx = spec.get("uuid_prefix", "geolabel")
    # Prefer explicit id; fall back to deterministic UUID
    if spec.get("id"):
        wpc_id = spec["id"]
    else:
        wpc_id = f"{pfx}:work-product-component--GeoLabelSet:{det_uuid(f'{uid_pfx}-gls')}:1"

    # Build GeoLabels.ColumnValues (tabular format expected by _normalize_geolabel)
    seg_ids = [lb["SegmentName"] for lb in labels]
    col_vals: Dict[str, List[Any]] = {"SegmentID": seg_ids}
    for lb in labels:
        prop = lb.get("PropertyName", label_prop)
        col_vals.setdefault(f"{prop}.P90", []).append(lb["P90"])
        col_vals.setdefault(f"{prop}.P50", []).append(lb["P50"])
        col_vals.setdefault(f"{prop}.P10", []).append(lb["P10"])

    # Add a TOTAL row (always — enrichment expects it for headline volumes)
    if len(labels) >= 1:
        col_vals["SegmentID"].append("TOTAL")
        for k in list(col_vals.keys()):
            if k == "SegmentID":
                continue
            col_vals[k].append(round(sum(col_vals[k]), 4))

    data: Dict[str, Any] = {
        "Name": f"{project} - GeoLabelSet ({label_prop} volumes)" if project else f"GeoLabelSet ({label_prop})",
        "Description": f"Per-segment volume labels ({label_prop} P10/P50/P90) derived from stat volumes",
        "GeoLabels": {
            "KeyColumns": [{"ColumnName": "SegmentID"}],
            "ColumnValues": col_vals,
        },
    }
    if reservoir_id:
        data["ReservoirID"] = reservoir_id

    return [{
        "id": wpc_id,
        "kind": "osdu:wks:work-product-component--GeoLabelSet:1.0.0",
        "acl": acl, "legal": legal, "data": data,
    }]


