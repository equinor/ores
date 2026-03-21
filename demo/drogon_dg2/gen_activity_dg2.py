#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_activity_dg2.py — Generate OSDU ActivityTemplate + Activity manifest
for the Drogon / Valysar DG2 volumetrics workflow.

Similar to the DG1 activity but:
  - References DG2 WPC IDs (params, raw, stat — all with ×0.8 porosity)
  - 50 realisations (design matrix expanded from DG1's 3)
  - PHIT variables base values ×0.8 to match the DG2 revised interpretation
  - New stable UUIDs (uuid5 with DG2 seeds)
  - Shares the same ETPDataspace (same geomodel)

Reads:
  ../drogon/manifest_masterwp_drogon.json   — Reservoir + WP IDs, acl, legal
  manifest_wpcparams_dg2.json               — DG2 ColumnBasedTable WPC ID
  manifest_wpcraw_dg2.json                  — DG2 RAW REV WPC ID
  manifest_wpcstat_dg2.json                 — DG2 Statistics REV WPC ID

Output:
  manifest_activity_dg2.json

Usage:
  py demo/drogon_dg2/gen_activity_dg2.py
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent        # demo/drogon_dg2
DG1_DIR    = SCRIPT_DIR.parent / "drogon"            # demo/drogon

# ── Stable deterministic UUIDs for DG2 (different seeds from DG1) ────
_NS = uuid.UUID("a0000000-d509-4e00-8000-000000000000")
TEMPLATE_UUID_DG2 = str(uuid.uuid5(_NS, "dg2-volumetrics-template"))
ACTIVITY_UUID_DG2 = str(uuid.uuid5(_NS, "dg2-volumetrics-activity"))

# ETP Dataspace — shared with DG1 (same geomodel)
DATASPACE_NAME = "maap/drogon_dg"
DATASPACE_ID_SUFFIX = DATASPACE_NAME.replace("/", "-")

POROSITY_FACTOR = 0.8  # DG2 downward revision

DEFAULT_ACL = {
    "owners":  ["data.default.owners@dev.dataservices.energy"],
    "viewers": ["data.office.global.viewers@dev.dataservices.energy"],
}
DEFAULT_LEGAL = {
    "legaltags": ["dev-equinor-private-default"],
    "otherRelevantDataCountries": ["NO"],
}

# ── Scenario data — DG2 revised PHIT (×0.8), OWC unchanged ──────────
VARIABLES_DG2 = [
    {"Name": "ModTable, Oil/water contact OWC 1",  "QuantityType": "Low/Base/High",
     "Low": 1650.0,  "Base": 1660.0, "High": 1670.0, "Group": "Skirt"},
    {"Name": "ModTable, Oil/water contact OWC 2",  "QuantityType": "Low/Base/High",
     "Low": 1667.0,  "Base": 1677.0, "High": 1687.0, "Group": "Centre"},
    {"Name": "ModTable, Oil/water contact OWC 3",  "QuantityType": "Low/Base/High",
     "Low": 1667.0,  "Base": 1677.0, "High": 1687.0, "Group": "Centre"},
    {"Name": "ModTable, Oil/water contact OWC 4",  "QuantityType": "Low/Base/High",
     "Low": 1650.0,  "Base": 1660.0, "High": 1670.0, "Group": "Skirt"},
    {"Name": "ModTable, Oil/water contact OWC 5",  "QuantityType": "Low/Base/High",
     "Low": 1667.0,  "Base": 1677.0, "High": 1687.0, "Group": "Centre"},
    {"Name": "ModTable, Oil/water contact OWC 6",  "QuantityType": "Low/Base/High",
     "Low": 1667.0,  "Base": 1677.0, "High": 1687.0, "Group": "Centre"},
    {"Name": "ModTable, Oil/water contact OWC 7",  "QuantityType": "Low/Base/High",
     "Low": 1650.0,  "Base": 1660.0, "High": 1670.0, "Group": "Skirt"},
    # PHIT values scaled ×0.8
    {"Name": "std_valysar, Floodplain, PHIT, expected mean", "QuantityType": "Low/Base/High",
     "Low":  round(0.09000000357627869 * POROSITY_FACTOR, 8),
     "Base": round(0.10300000011920929 * POROSITY_FACTOR, 8),
     "High": round(0.11299999803304672 * POROSITY_FACTOR, 8), "Group": "Centre"},
    {"Name": "std_valysar, Channel, PHIT, expected mean",    "QuantityType": "Low/Base/High",
     "Low":  round(0.2653200030326843  * POROSITY_FACTOR, 8),
     "Base": round(0.27532124519348145 * POROSITY_FACTOR, 8),
     "High": round(0.2853200137615204  * POROSITY_FACTOR, 8), "Group": "Centre"},
    {"Name": "std_valysar, Crevasse, PHIT, expected mean",   "QuantityType": "Low/Base/High",
     "Low":  round(0.19869999587535858 * POROSITY_FACTOR, 8),
     "Base": round(0.20869815349578857 * POROSITY_FACTOR, 8),
     "High": round(0.21870000660419464 * POROSITY_FACTOR, 8), "Group": "Centre"},
]

# DG2 design matrix — 50 realisations using Latin Hypercube Sampling
# We define representative matrix: first 3 same as DG1 (Base/Low/High),
# then 47 Monte Carlo draws represented as "MonteCarlo-N" strings.
DESIGN_MATRIX_DG2: List[Dict[str, Any]] = [
    {"Realization": 1, "Scenario": "Base"},
    {"Realization": 2, "Scenario": "Low"},
    {"Realization": 3, "Scenario": "High"},
]
for i in range(4, 51):
    DESIGN_MATRIX_DG2.append({"Realization": i, "Scenario": f"MonteCarlo-{i}"})


import sys
if str(DG1_DIR) not in sys.path:
    sys.path.insert(0, str(DG1_DIR))
from _shared import load_json  # noqa: E402


def _find_id(manifest: Dict[str, Any], kind_fragment: str) -> str:
    for rec in manifest.get("MasterData", []):
        if kind_fragment in rec.get("kind", ""):
            return rec["id"]
    data = manifest.get("Data", {})
    for rec in data.get("WorkProductComponents", []):
        if kind_fragment in rec.get("kind", ""):
            return rec["id"]
    for rec in data.get("WorkProducts", []):
        if kind_fragment in rec.get("kind", ""):
            return rec["id"]
    wp = data.get("WorkProduct")
    if isinstance(wp, dict) and kind_fragment in wp.get("kind", ""):
        return wp["id"]
    return ""


def _make_param(title, kind, role, description,
                is_input=True, is_output=False,
                min_occurs=0, max_occurs=1, allowed_kind="DataObject"):
    return {
        "Title": title,
        "Description": description,
        "IsInput": is_input,
        "IsOutput": is_output,
        "MinOccurs": min_occurs,
        "MaxOccurs": max_occurs,
        "DefaultParameterKind": allowed_kind,
    }


def build_template(prefix, acl, legal):
    template_id = f"{prefix}:work-product-component--ActivityTemplate:{TEMPLATE_UUID_DG2}:1"
    return {
        "id": template_id,
        "kind": "osdu:wks:work-product-component--ActivityTemplate:1.0.0",
        "acl": acl,
        "legal": legal,
        "data": {
            "Name": "Drogon Valysar — DG2 Volumetrics Workflow Template (porosity ×0.8)",
            "Description": (
                "ActivityTemplate for the Drogon / Valysar DG2 volumetrics ensemble workflow. "
                "Identical three-step structure to DG1 but with revised porosity (×0.8 factor) "
                "and expanded to 50 Latin Hypercube realisations. "
                "Step 1: generate input parameter table (OWC + revised PHIT). "
                "Step 2: run RMS DecisionExample with 50 realisations. "
                "Step 3: aggregate into P10/P50/P90 statistics."
            ),
            "Originator": "markuslund.vevle@emerson.com",
            "ParameterTemplates": [
                _make_param("InputParameters", "string", "in",
                    "Input parameter table (ColumnBasedTable WPC) with revised porosity.",
                    is_input=True, is_output=False, allowed_kind="DataObject"),
                _make_param("Process", "string", "in",
                    "Name of the RMS reservoir model / workflow.",
                    is_input=True, is_output=False, allowed_kind="string", min_occurs=1),
                _make_param("NumberOfRealizations", "string", "in",
                    "Total number of realisations executed (50 for DG2).",
                    is_input=True, is_output=False, allowed_kind="integer", min_occurs=1),
                _make_param("Workflow", "string", "in",
                    "Workflow label within the RMS project.",
                    is_input=True, is_output=False, allowed_kind="string"),
                _make_param("Method", "string", "in",
                    "Uncertainty sampling method (Latin Hypercube for DG2).",
                    is_input=True, is_output=False, allowed_kind="string"),
                _make_param("Variables", "string", "in",
                    "Serialised JSON list of uncertainty variable definitions (DG2 revised PHIT).",
                    is_input=True, is_output=False, allowed_kind="string"),
                _make_param("DesignMatrix", "string", "in",
                    "Serialised JSON design matrix (50 realisations).",
                    is_input=True, is_output=False, allowed_kind="string"),
                _make_param("OutputParameters", "string", "out",
                    "Generated per-realisation input parameter table (ColumnBasedTable WPC).",
                    is_input=False, is_output=True, allowed_kind="DataObject"),
                _make_param("OutputVolumes", "string", "out",
                    "Per-realisation reservoir estimated volumes (RAW REV WPC).",
                    is_input=False, is_output=True, allowed_kind="DataObject", min_occurs=1),
                _make_param("ReportTable", "string", "out",
                    "Statistical aggregation of realisations (STAT REV WPC: P10/P50/P90).",
                    is_input=False, is_output=True, allowed_kind="DataObject", min_occurs=1),
            ],
        },
    }


def build_dataspace(prefix, acl, legal):
    """Build ETPDataspace record — shared with DG1 (same geomodel)."""
    return {
        "id":    f"{prefix}:dataset--ETPDataspace:{DATASPACE_ID_SUFFIX}:1",
        "kind":  "osdu:wks:dataset--ETPDataspace:1.0.0",
        "acl":   acl,
        "legal": legal,
        "data": {
            "Name": f"Drogon DG Geomodel Dataspace ({DATASPACE_NAME})",
            "Description": (
                "RDDMS dataspace holding the Drogon geomodel EPC files exported from RMS "
                "(drogon_activity.epc, drogon_tables.epc). "
                "Shared between DG1 and DG2 — same structural model."
            ),
            "DatasetProperties": {
                "URI": f"eml:///dataspace({DATASPACE_NAME})",
                "ServerURL": "wss://equinorswedev.energy.azure.com/api/reservoir-ddms-etp/v2/",
            },
        },
    }


def build_activity(
    prefix, acl, legal,
    template_id, reservoir_id, workproduct_id,
    params_wpc_id, raw_wpc_id, stat_wpc_id,
    dataspace_id="",
):
    activity_id = f"{prefix}:work-product-component--Activity:{ACTIVITY_UUID_DG2}:1"

    parameters = [
        {
            "Title": "InputParameters",
            "Description": "DG2 per-realisation OWC depth and revised PHIT input parameter table (porosity ×0.8)",
            "ParameterKindID": f"{prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{prefix}:reference-data--ParameterRole:Input:1",
            "DataObjectParameter": params_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ColumnBasedTable-params"}],
        },
        {
            "Title": "Process",
            "Description": "RMS reservoir model workflow that executes the DG2 realisations",
            "ParameterKindID": f"{prefix}:reference-data--ParameterKind:String:1",
            "ParameterRoleID": f"{prefix}:reference-data--ParameterRole:Input:1",
            "StringParameter": "RMS DecisionExample — Drogon Valysar (DG2, revised PHIT)",
        },
        {
            "Title": "NumberOfRealizations",
            "Description": "Number of realisations executed in the DG2 ensemble",
            "ParameterKindID": f"{prefix}:reference-data--ParameterKind:Integer:1",
            "ParameterRoleID": f"{prefix}:reference-data--ParameterRole:Input:1",
            "IntegerParameter": 50,
        },
        {
            "Title": "Workflow",
            "Description": "Workflow label within the RMS project",
            "ParameterKindID": f"{prefix}:reference-data--ParameterKind:String:1",
            "ParameterRoleID": f"{prefix}:reference-data--ParameterRole:Input:1",
            "StringParameter": "DecisionExample",
        },
        {
            "Title": "Method",
            "Description": "Uncertainty sampling method — upgraded to Latin Hypercube at DG2",
            "ParameterKindID": f"{prefix}:reference-data--ParameterKind:String:1",
            "ParameterRoleID": f"{prefix}:reference-data--ParameterRole:Input:1",
            "StringParameter": "Latin_Hypercube",
        },
        {
            "Title": "Variables",
            "Description": (
                "Uncertainty variable configuration: OWC contacts (7 segments, unchanged) "
                "and PHIT per facies (Floodplain, Channel, Crevasse) revised ×0.8."
            ),
            "ParameterKindID": f"{prefix}:reference-data--ParameterKind:String:1",
            "ParameterRoleID": f"{prefix}:reference-data--ParameterRole:Input:1",
            "StringParameter": json.dumps(VARIABLES_DG2, separators=(",", ":")),
        },
        {
            "Title": "DesignMatrix",
            "Description": (
                "Design matrix for 50 realisations: 3 anchored (Base/Low/High) + "
                "47 Latin Hypercube draws."
            ),
            "ParameterKindID": f"{prefix}:reference-data--ParameterKind:String:1",
            "ParameterRoleID": f"{prefix}:reference-data--ParameterRole:Input:1",
            "StringParameter": json.dumps(DESIGN_MATRIX_DG2, separators=(",", ":")),
        },
        # ── outputs ─────
        {
            "Title": "OutputParameters",
            "Description": "Generated DG2 per-realisation input parameter table (porosity ×0.8)",
            "ParameterKindID": f"{prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{prefix}:reference-data--ParameterRole:Output:1",
            "DataObjectParameter": params_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ColumnBasedTable-params"}],
        },
        {
            "Title": "OutputVolumes",
            "Description": "DG2 per-realisation estimated volumes (RAW REV WPC, ×0.8)",
            "ParameterKindID": f"{prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{prefix}:reference-data--ParameterRole:Output:1",
            "DataObjectParameter": raw_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "REV-raw"}],
        },
        {
            "Title": "ReportTable",
            "Description": "DG2 statistical aggregation of realisations (STAT REV WPC: P10/P50/P90)",
            "ParameterKindID": f"{prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{prefix}:reference-data--ParameterRole:Output:1",
            "DataObjectParameter": stat_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "REV-stats"}],
        },
    ]

    if dataspace_id:
        parameters.append({
            "Title": "GeoModelDataspace",
            "Description": (
                "RDDMS ETP dataspace containing the Drogon geomodel EPC files. "
                "Shared structural model — same dataspace as DG1."
            ),
            "ParameterKindID": f"{prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{prefix}:reference-data--ParameterRole:InputReference:1",
            "DataObjectParameter": dataspace_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ETPDataspace"}],
        })

    return {
        "id": activity_id,
        "kind": "osdu:wks:work-product-component--Activity:1.0.0",
        "acl": acl,
        "legal": legal,
        "data": {
            "Name": "Drogon Valysar — DG2 Volumetrics Workflow Run (porosity ×0.8, 50 realisations)",
            "Description": (
                "DG2 volumetrics workflow for the Valysar formation of the Drogon field. "
                "Same three-step structure as DG1 but with revised petrophysical interpretation: "
                "porosity reduced by factor 0.8 based on additional core data and thin-section "
                "analysis. Ensemble expanded from 3 to 50 Latin Hypercube realisations for "
                "improved uncertainty quantification. "
                "Pore-dependent volumes (Oil, Gas, etc.) correspondingly reduced by ~20%. "
                "OWC depths and structural model unchanged from DG1."
            ),
            "Originator": "markuslund.vevle@emerson.com",
            "CreationDateTime": "2026-03-01T09:00:00.000Z",
            "ActivityTemplateID": template_id,
            "WorkflowStatus": "Completed",
            "ParentObjectID": reservoir_id,
            "ParentWorkProductID": workproduct_id,
            "Parameters": parameters,
            "ancestry": {
                "parents": [reservoir_id],
                "children": [params_wpc_id, raw_wpc_id, stat_wpc_id],
            },
        },
    }


def main():
    ap = argparse.ArgumentParser(description="Generate Drogon DG2 activity manifest")
    ap.add_argument("--masterwp",  default=str(DG1_DIR / "manifest_masterwp_drogon.json"))
    ap.add_argument("--params",    default=str(SCRIPT_DIR / "manifest_wpcparams_dg2.json"))
    ap.add_argument("--rawvol",    default=str(SCRIPT_DIR / "manifest_wpcraw_dg2.json"))
    ap.add_argument("--statvol",   default=str(SCRIPT_DIR / "manifest_wpcstat_dg2.json"))
    ap.add_argument("--manifest",  default=str(SCRIPT_DIR / "manifest_activity_dg2.json"))
    ap.add_argument("--id-prefix", default="dev")
    args = ap.parse_args()

    masterwp = load_json(args.masterwp)
    params   = load_json(args.params)
    rawvol   = load_json(args.rawvol)
    statvol  = load_json(args.statvol)

    reservoir_id   = _find_id(masterwp, "master-data--Reservoir:")
    workproduct_id = _find_id(masterwp, "work-product:")
    params_wpc_id  = _find_id(params,  "ColumnBasedTable")
    raw_wpc_id     = _find_id(rawvol,  "ReservoirEstimatedVolumes")
    stat_wpc_id    = _find_id(statvol, "ReservoirEstimatedVolumes")

    for label, val in [("reservoir_id", reservoir_id),
                       ("workproduct_id", workproduct_id),
                       ("params_wpc_id", params_wpc_id),
                       ("raw_wpc_id", raw_wpc_id),
                       ("stat_wpc_id", stat_wpc_id)]:
        if not val:
            raise SystemExit(f"ERROR: could not find {label}")

    acl = legal = None
    for rec in masterwp.get("MasterData", []):
        if "master-data--Reservoir:" in rec.get("kind", ""):
            acl   = rec.get("acl",   DEFAULT_ACL)
            legal = rec.get("legal", DEFAULT_LEGAL)
            break
    acl   = acl   or DEFAULT_ACL
    legal = legal or DEFAULT_LEGAL

    prefix = args.id_prefix
    template_id  = f"{prefix}:work-product-component--ActivityTemplate:{TEMPLATE_UUID_DG2}:1"
    dataspace_id = f"{prefix}:dataset--ETPDataspace:{DATASPACE_ID_SUFFIX}:1"

    dataspace = build_dataspace(prefix, acl, legal)
    template  = build_template(prefix, acl, legal)
    activity  = build_activity(
        prefix, acl, legal,
        template_id=template_id,
        reservoir_id=reservoir_id,
        workproduct_id=workproduct_id,
        params_wpc_id=params_wpc_id,
        raw_wpc_id=raw_wpc_id,
        stat_wpc_id=stat_wpc_id,
        dataspace_id=dataspace_id,
    )

    manifest = {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "Datasets": [dataspace],
            "WorkProductComponents": [template, activity],
            "WorkProducts": [],
        },
    }

    out = Path(args.manifest)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Written: {out}")
    print(f"  ETPDataspace     : {dataspace['id']}")
    print(f"  ActivityTemplate : {template['id']}")
    print(f"  Activity         : {activity['id']}")
    print(f"  Inputs:  params={params_wpc_id}")
    print(f"  Outputs: raw={raw_wpc_id}")
    print(f"           stat={stat_wpc_id}")
    print(f"  Realisations: 50  |  Porosity factor: {POROSITY_FACTOR}")


if __name__ == "__main__":
    main()
