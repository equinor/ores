#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gengeolabelset_drogon.py — Generate a GeoLabelSet record derived from the
statistics REV manifest.

Volumes are extracted from the per-segment TOTAL rows of the stat REV
and stored in m³ (consistent with REV).  Petro-physical properties are
synthetic but realistic for the Drogon model.

Reads:
  manifest_wpcstat_drogon.json   — stat REV manifest (corrected TOTALs)
  manifest_masterwp_drogon.json  — for Reservoir ID, ACL, legal

Output:
  Overwrites the existing GeoLabelSet record file in records/

Usage:
  python demo/drogon/gengeolabelset_drogon.py
  python demo/drogon/gengeolabelset_drogon.py --gate dg2 \
      --stat-manifest demo/drogon_dg2/manifest_wpcstat_dg2.json \
      --output demo/drogon_dg2/records/026_dev_work-product-component--GeoLabelSet_e4b7a1c3-5f28-4d9e-8a61-7c3d9e0f2b85_1.json \
      --record-id dev:work-product-component--GeoLabelSet:e4b7a1c3-5f28-4d9e-8a61-7c3d9e0f2b85:1 \
      --parent-wp dev:work-product:Drogon-DG2-ConceptSelect:1
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent

from _shared import load_json  # noqa: E402


def std_ref_id(prefix: str, entity: str, name: str) -> str:
    return f"{prefix}:reference-data--{entity}:{name}"


# ── Petro-physical constants (synthetic but realistic for Drogon) ──────
# These are field-wide averages; per-facies porosity is separate.
PETRO = {
    "NetToGross":            0.85,
    "Permeability":          450,     # mD
    "OilWaterContact":       1710,    # m TVDSS
    "Temperature":           72,      # °C
    "Pressure":              170,     # bar
    "Viscosity":             1.2,     # cP
    "FormationVolumeFactor": 1.12,    # Rm3/Sm3
    "GasOilRatio":           85,      # Sm3/Sm3
}

# Per-facies porosity (used in TOTAL/facies rows)
FACIES_POROSITY = {
    "Channel":    0.28,
    "Crevasse":   0.21,
    "Floodplain": 0.10,
}

# Recovery-factor P-values (fraction)
RF = {"P10": 0.39, "P50": 0.345, "P90": 0.30}


def build_geolabelset(
    stat_manifest: Dict,
    reservoir_id: str,
    parent_wp_id: str,
    record_id: str,
    acl: Dict,
    legal: Dict,
    id_prefix: str,
    gate_name: str = "DG1",
) -> Dict:
    """Build a GeoLabelSet record from the stat REV manifest."""

    wpc = next(
        w for w in stat_manifest["Data"]["WorkProductComponents"]
        if "ReservoirEstimatedVolumes" in w.get("kind", "")
    )
    cv = wpc["data"]["Volumes"]["ColumnValues"]
    zones = cv["Zone"]
    segs  = cv["SegmentID"]
    facs  = cv["Facies"]

    # ── Collect per-segment TOTAL Oil P10/P50/P90 ──────────────────────
    # These are rows where Zone=TOTAL AND Facies=TOTAL for each segment
    segment_vols: Dict[str, Dict[str, float]] = {}
    for i in range(len(zones)):
        if zones[i] == "TOTAL" and facs[i] == "TOTAL":
            seg = segs[i]
            segment_vols[seg] = {
                "Oil.P10": cv["Oil.P10"][i],
                "Oil.P50": cv["Oil.P50"][i],
                "Oil.P90": cv["Oil.P90"][i],
            }

    # Separate grand TOTAL from per-segment
    grand = segment_vols.pop("TOTAL", {})
    ordered_segs = sorted(segment_vols.keys())

    # ── Build ColumnValues ─────────────────────────────────────────────
    all_cols = [
        "SegmentID", "Facies",
        "Oil.P90", "Oil.P50", "Oil.P10",
        "Recoverable.P90", "Recoverable.P50", "Recoverable.P10",
        "RecoveryFactor.P90", "RecoveryFactor.P50", "RecoveryFactor.P10",
        "Porosity", "NetToGross", "Permeability",
        "OilWaterContact", "Temperature", "Pressure",
        "Viscosity", "FormationVolumeFactor", "GasOilRatio",
    ]
    colvals: Dict[str, List[Any]] = {c: [] for c in all_cols}

    def _add_row(seg: str, fac: str, vals: Dict[str, Any]):
        colvals["SegmentID"].append(seg)
        colvals["Facies"].append(fac)
        for c in all_cols[2:]:  # skip SegmentID, Facies
            colvals[c].append(vals.get(c))

    # Per-segment rows (volumes only)
    for seg in ordered_segs:
        sv = segment_vols[seg]
        _add_row(seg, "ALL", {
            "Oil.P90": round(sv["Oil.P90"], 1),
            "Oil.P50": round(sv["Oil.P50"], 1),
            "Oil.P10": round(sv["Oil.P10"], 1),
        })

    # Grand TOTAL row (volumes + recoverable + petro)
    total_vals: Dict[str, Any] = {
        "Oil.P90": round(grand.get("Oil.P90", 0), 1),
        "Oil.P50": round(grand.get("Oil.P50", 0), 1),
        "Oil.P10": round(grand.get("Oil.P10", 0), 1),
    }
    # Recoverable = Oil × RecoveryFactor
    for px in ("P90", "P50", "P10"):
        oil_val = grand.get(f"Oil.{px}", 0.0)
        rf_val  = RF[px]
        total_vals[f"Recoverable.{px}"] = round(oil_val * rf_val, 1)
        total_vals[f"RecoveryFactor.{px}"] = rf_val * 100  # percent
    total_vals.update(PETRO)
    _add_row("TOTAL", "ALL", total_vals)

    # Per-facies porosity rows
    for fac_name, poro in FACIES_POROSITY.items():
        _add_row("TOTAL", fac_name, {"Porosity": poro})

    # ── Column metadata (all volumes in m³) ────────────────────────────
    vol_uom   = std_ref_id(id_prefix, "UnitOfMeasure", "m3")
    pct_uom   = std_ref_id(id_prefix, "UnitOfMeasure", "%")
    frac_uom  = std_ref_id(id_prefix, "UnitOfMeasure", "fraction")

    col_meta_map = {
        "Oil.P90":                {"UoM": vol_uom},
        "Oil.P50":                {"UoM": vol_uom},
        "Oil.P10":                {"UoM": vol_uom},
        "Recoverable.P90":        {"UoM": vol_uom},
        "Recoverable.P50":        {"UoM": vol_uom},
        "Recoverable.P10":        {"UoM": vol_uom},
        "RecoveryFactor.P90":     {"UoM": pct_uom},
        "RecoveryFactor.P50":     {"UoM": pct_uom},
        "RecoveryFactor.P10":     {"UoM": pct_uom},
        "Porosity":               {"UoM": frac_uom},
        "NetToGross":             {"UoM": frac_uom},
        "Permeability":           {"UoM": std_ref_id(id_prefix, "UnitOfMeasure", "mD")},
        "OilWaterContact":        {"UoM": std_ref_id(id_prefix, "UnitOfMeasure", "m")},
        "Temperature":            {"UoM": std_ref_id(id_prefix, "UnitOfMeasure", "degC")},
        "Pressure":               {"UoM": std_ref_id(id_prefix, "UnitOfMeasure", "bar")},
        "Viscosity":              {"UoM": std_ref_id(id_prefix, "UnitOfMeasure", "cP")},
        "FormationVolumeFactor":  {"UoM": std_ref_id(id_prefix, "UnitOfMeasure", "Rm3/Sm3")},
        "GasOilRatio":            {"UoM": std_ref_id(id_prefix, "UnitOfMeasure", "Sm3/Sm3")},
    }

    columns = []
    for c in all_cols[2:]:  # skip key columns
        columns.append({
            "ColumnName":      c,
            "ColumnRole":      "Value",
            "ValueType":       "number",
            "UnitOfMeasureID": col_meta_map[c]["UoM"],
        })

    key_columns = [
        {"ColumnName": "SegmentID", "ColumnRole": "Key", "ValueType": "string",
         "KindID": "osdu:wks:master-data--ReservoirSegment:2.0.0"},
        {"ColumnName": "Facies",    "ColumnRole": "Key", "ValueType": "string"},
    ]

    return {
        "id":   record_id,
        "kind": "osdu:wks:work-product-component--GeoLabelSet:1.0.0",
        "acl":  acl,
        "legal": legal,
        "data": {
            "Name": f"Drogon Valysar — GeoLabelSet ({gate_name})",
            "Description": (
                f"GeoLabelSet for {gate_name}, derived from stat REV. "
                "All volumes in m³. Includes per-segment Oil P10/P50/P90, "
                "field-level recoverable volumes, and petro-physical properties."
            ),
            "ParentObjectID":      reservoir_id,
            "ParentWorkProductID": parent_wp_id,
            "LabelledEntityID":    reservoir_id,
            "ancestry": {"parents": [reservoir_id]},
            "GeoLabels": {
                "ColumnBasedTableTypeID": std_ref_id(
                    id_prefix, "ColumnBasedTableType", "AdHoc"
                ),
                "KeyColumns":   key_columns,
                "Columns":      columns,
                "ColumnValues": colvals,
            },
        },
    }


def main():
    ap = argparse.ArgumentParser(description="Generate Drogon GeoLabelSet from stat REV")
    ap.add_argument("--gate", default="DG1", help="Gate name (DG1 or DG2)")
    ap.add_argument("--stat-manifest", default=str(SCRIPT_DIR / "manifest_wpcstat_drogon.json"))
    ap.add_argument("--masterwp", default=str(SCRIPT_DIR / "manifest_masterwp_drogon.json"))
    ap.add_argument("--output", default=str(
        SCRIPT_DIR / "records" /
        "019_dev_work-product-component--GeoLabelSet_f5c8b2d4-6a39-4eaf-9b72-8d4eaf1a3c96_1.json"
    ))
    ap.add_argument("--record-id", default="dev:work-product-component--GeoLabelSet:f5c8b2d4-6a39-4eaf-9b72-8d4eaf1a3c96:1")
    ap.add_argument("--parent-wp", default="dev:work-product:Drogon-DG1-IdentifyAssess:1")
    ap.add_argument("--id-prefix", default="dev")
    args = ap.parse_args()

    stat_mani = load_json(args.stat_manifest)
    master    = load_json(args.masterwp)

    # Extract Reservoir ID and compliance from MasterWP
    reservoir_id = ""
    acl   = {"owners": ["data.default.owners@dev.dataservices.energy"],
             "viewers": ["data.office.global.viewers@dev.dataservices.energy"]}
    legal = {"legaltags": ["dev-equinor-private-default"],
             "otherRelevantDataCountries": ["NO"]}
    for md in master.get("MasterData", []):
        if "master-data--Reservoir:" in md.get("kind", ""):
            reservoir_id = md["id"]
            acl   = md.get("acl", acl)
            legal = md.get("legal", legal)
            break

    gls = build_geolabelset(
        stat_mani, reservoir_id, args.parent_wp, args.record_id,
        acl, legal, args.id_prefix, args.gate,
    )

    Path(args.output).write_text(json.dumps(gls, indent=2), encoding="utf-8")
    n_rows = len(gls["data"]["GeoLabels"]["ColumnValues"]["SegmentID"])
    print(f"GeoLabelSet ({args.gate}) written → {args.output}")
    print(f"  Rows: {n_rows}  Volumes in m³")

    # Summary
    cv = gls["data"]["GeoLabels"]["ColumnValues"]
    for i in range(n_rows):
        if cv["SegmentID"][i] == "TOTAL" and cv["Facies"][i] == "ALL":
            print(f"  TOTAL Oil: P10={cv['Oil.P10'][i]:,.1f}  "
                  f"P50={cv['Oil.P50'][i]:,.1f}  "
                  f"P90={cv['Oil.P90'][i]:,.1f} m³")
            break


if __name__ == "__main__":
    main()
