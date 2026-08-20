#!/usr/bin/env python3
"""
curate_manifest_dg2.py – Post-process the RDDMS-generated manifest for maap/drogon_dg
to fix names, descriptions, and add spatial metadata.

Issues in raw RDDMS manifest:
  1. StructureMap/GenericRepresentation Name = workflow step (DS_extract_geogrid)
     instead of meaningful name (TopTherys - depth surface extract from geogrid)
  2. No SpatialArea (WGS84 bounding box) on any record
  3. No BinWidth on Grid2d-backed StructureMaps
  4. No Description on most records

Fixes applied:
  - Name = "{InterpretationName} - {original_title}" (e.g. "TopTherys - DS_extract_geogrid")
  - SpatialArea = Drogon project WGS84 bounding box
  - BinWidth = 25m (from fmu-dataio sidecar metadata)
  - Description = human-readable description based on workflow step category

Usage:
  python demo/drogon_dg2/curate_manifest_dg2.py
  python demo/drogon_dg2/curate_manifest_dg2.py --input manifest_rddms_dg2_raw.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# ── Drogon project spatial metadata ────────────────────────────────────────
# CRS: WGS84 / UTM zone 37N (EPSG:32637) – synthetic model
# Grid: origin (456064, 5926551), 280×440 nodes at 25m spacing
DROGON_SPATIAL_AREA_WGS84 = {
    "Wgs84Coordinates": {
        "type": "Polygon",
        "coordinates": [[[38.3360, 53.4861], [38.5102, 53.4869],
                         [38.5089, 53.6029], [38.3360, 53.6020],
                         [38.3360, 53.4861]]]
    }
}
DROGON_CRS_META = {
    "kind": "CRS",
    "name": "WGS 84 / UTM zone 37N",
    "persistableReference": (
        '{"authCode":{"auth":"EPSG","code":"32637"},'
        '"type":"LBC","ver":"PE_10_9_1",'
        '"name":"WGS_1984_UTM_Zone_37N"}'
    ),
}
DROGON_CRS_ID = "dev:reference-data--CoordinateReferenceSystem:BoundCRS.SLB.32637.15851:"
BIN_WIDTH = 25.0  # metres

# ── Workflow step → human-readable descriptions ────────────────────────────
STEP_DESCRIPTIONS = {
    "DS_extract_geogrid":       "Depth surface extracted from geogrid (FMU workflow)",
    "DS_extract_postprocess":   "Depth surface from post-processed model",
    "DS_extract_simgrid":       "Depth surface extracted from simulation grid",
    "DS_interp":                "Interpreted depth surface",
    "DS_velmod":                "Velocity model depth surface",
    "DS_gf_hum_extracted":      "Depth surface from HUM geophysics extraction",
    "DS_gf_initial_extracted":  "Depth surface from initial geophysics extraction",
    "DS_hum_ert_ahm":           "Depth surface from ERT-AHM history matching",
    "DS_hum_postiterate_extracted": "Depth surface from HUM post-iteration extraction",
    "GS_velocity_dconv":        "Velocity depth-conversion surface",
    "TS_time_extracted":        "Time surface extraction",
    "TS_interp":                "Interpreted time surface",
    "TS_filter":                "Filtered time surface",
    # PointSet categories
    "DP_faults_hum_postiterate": "Fault points from HUM post-iteration",
    "DP_faults_hum":            "Fault points from HUM inversion",
    "DP_filter_from_time":      "Depth picks filtered from time",
    "DP_filter":                "Filtered depth picks",
    "DP_filter_post":           "Post-filtered depth picks",
    "DP_filter_post_hum_input": "Post-filtered HUM input depth picks",
    "DP_gf_hum_extracted":      "Depth picks from HUM geophysics extraction",
    "DP_hum_postiterate_extracted": "Depth picks from HUM post-iteration extraction",
    "DP_faultpoints_extra_from_truth": "Extra fault points from truth model",
    "DP_hum_ert_ahm":           "Depth picks from ERT-AHM history matching",
    "ExtractedFaultPoints":     "Extracted fault stick points",
    "TP_filter":                "Filtered time picks",
    "TP_filter_from_depth":     "Time picks filtered from depth",
}

# ── WPC kinds that should receive spatial metadata ─────────────────────────
SPATIAL_KINDS = {
    "StructureMap", "GenericRepresentation", "IjkGridRepresentation",
    "HorizonInterpretation", "FaultInterpretation", "LocalBoundaryFeature",
    "WellboreTrajectory", "WellboreMarkerSet", "WellLog",
}


def _kind_short(kind: str) -> str:
    """Extract short kind name from full kind string."""
    if "--" in kind:
        return kind.split("--")[-1].split(":")[0]
    return kind


def curate_name(data: dict, kind: str) -> str:
    """Build a human-readable Name from InterpretationName + original title."""
    original_name = data.get("Name", "")
    interp_name = data.get("InterpretationName", "")

    if not interp_name:
        return original_name

    # If the name already starts with the interpretation name, leave it
    if original_name.startswith(interp_name):
        return original_name

    # Build curated name: "TopTherys - DS_extract_geogrid"
    return f"{interp_name} \u2014 {original_name}"


def curate_description(data: dict) -> str:
    """Generate a description based on the workflow step name."""
    name = data.get("Name", "")
    interp = data.get("InterpretationName", "")

    # Look up step description
    desc = STEP_DESCRIPTIONS.get(name, "")
    if desc and interp:
        return f"{desc} for {interp}"
    if desc:
        return desc
    if interp:
        return f"Surface/point representation for {interp}"
    return ""


def curate_record(rec: dict) -> dict:
    """Apply all curation fixes to a single WPC record."""
    data = rec.get("data", {})
    kind = _kind_short(rec.get("kind", ""))

    # 1. Fix Name
    if kind in ("StructureMap", "GenericRepresentation"):
        data["Name"] = curate_name(data, kind)

    # 2. Fix Description
    if kind in ("StructureMap", "GenericRepresentation") and not data.get("Description"):
        desc = curate_description(data)
        if desc:
            data["Description"] = desc

    # 3. Add SpatialArea
    if kind in SPATIAL_KINDS and "SpatialArea" not in data:
        data["SpatialArea"] = DROGON_SPATIAL_AREA_WGS84

    # 4. Add BinWidth for StructureMaps (all are 25m grids)
    if kind == "StructureMap":
        if not data.get("BinWidthOnIaxis"):
            data["BinWidthOnIaxis"] = BIN_WIDTH
        if not data.get("BinWidthOnJaxis"):
            data["BinWidthOnJaxis"] = BIN_WIDTH

    # 5. Add CRS if missing
    if kind in SPATIAL_KINDS and "CoordinateReferenceSystemID" not in data:
        data["CoordinateReferenceSystemID"] = DROGON_CRS_ID

    # 6. Add/fix meta CRS
    if kind in SPATIAL_KINDS:
        meta = rec.get("meta")
        if not meta:
            rec["meta"] = [DROGON_CRS_META]
        elif isinstance(meta, list):
            has_crs = any(m.get("kind") == "CRS" and m.get("persistableReference") for m in meta)
            if not has_crs:
                rec["meta"].append(DROGON_CRS_META)

    rec["data"] = data
    return rec


def main():
    ap = argparse.ArgumentParser(description="Curate RDDMS manifest for Drogon DG2")
    ap.add_argument("--input", default=str(SCRIPT_DIR / "manifest_rddms_dg2_raw.json"))
    ap.add_argument("--output", default=str(SCRIPT_DIR / "manifest_rddms_dg2.json"))
    args = ap.parse_args()

    manifest = json.loads(Path(args.input).read_text())

    wpcs = manifest.get("Data", {}).get("WorkProductComponents", [])
    curated = 0
    for rec in wpcs:
        kind = _kind_short(rec.get("kind", ""))
        if kind in ("StructureMap", "GenericRepresentation", "IjkGridRepresentation",
                    "HorizonInterpretation", "FaultInterpretation", "LocalBoundaryFeature",
                    "WellLog", "WellboreMarkerSet"):
            curate_record(rec)
            curated += 1

    # Summary
    print(f"Curated {curated}/{len(wpcs)} WPC records")
    print(f"\nStructureMaps:")
    for w in wpcs:
        if "StructureMap" in w.get("kind", ""):
            d = w.get("data", {})
            print(f"  {d.get('Name', '?')}")
            print(f"    desc: {d.get('Description', '')[:70]}")

    print(f"\nGenericRepresentation (first 10):")
    gen = [w for w in wpcs if "GenericRepresentation" in w.get("kind", "")]
    for w in gen[:10]:
        d = w.get("data", {})
        print(f"  {d.get('Name', '?')}")

    # Save
    out = Path(args.output)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved to {out.name} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
