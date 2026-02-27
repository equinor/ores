#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_activity_drogon.py — Generate OSDU ActivityTemplate + Activity manifest
for the Drogon / Valysar DG1 volumetrics workflow.

The Activity record consolidates the three-step execution formerly split as:
  1. Generate input parameter table (OWC depths + PHIT per realisation)
  2. Run RMS reservoir model (DecisionExample workflow, 3 realisations)
  3. Aggregate per-realisation volumes into P10/P50/P90 statistics

All scenario configuration is taken from obj_Activity_MISSING.xml (design
matrix, OWC variables, PHIT variables, number of realisations).

Canonical IDs (Reservoir, Segments, WPCs) are sourced from the existing
Drogon manifests — no hard-coding here.

Reads:
  manifest_masterwp_drogon.json    — Reservoir + WP IDs, acl, legal
  manifest_wpcparams_drogon.json   — ColumnBasedTable WPC ID (input parameters)
  manifest_wpcraw_drogon.json      — RAW REV WPC ID
  manifest_wpcstat_drogon.json     — Statistics REV WPC ID

Output:
  manifest_activity_drogon.json

Stable UUIDs (uuid5 from namespace a0000000-d509-4e00-8000-000000000000):
  ActivityTemplate : aa2791c8-e2ea-5aa5-871d-25db294aad8a
  Activity         : ead6e342-fa77-5485-b13b-7b3b2030c6e6

Usage:
  py demo/drogon/gen_activity_drogon.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent  # demo/drogon

# ── Stable deterministic UUIDs ───────────────────────────────────────────
# uuid5(UUID("a0000000-d509-4e00-8000-000000000000"), "<seed>")
TEMPLATE_UUID = "aa2791c8-e2ea-5aa5-871d-25db294aad8a"
ACTIVITY_UUID = "ead6e342-fa77-5485-b13b-7b3b2030c6e6"

# ── Reservoir DDMS / ETP dataspace for the Drogon RESQML artefacts ─────────
# URI format confirmed from live OSDU records: no quotes around dataspace path
DATASPACE_NAME = "maap/drogon_dg"  # dataspace path in Reservoir DDMS
DATASPACE_ID_SUFFIX = DATASPACE_NAME.replace("/", "-")  # maap-drogon_dg

DEFAULT_ACL = {
    "owners":  ["data.default.owners@dev.dataservices.energy"],
    "viewers": ["data.office.global.viewers@dev.dataservices.energy"],
}
DEFAULT_LEGAL = {
    "legaltags": ["dev-equinor-private-default"],
    "otherRelevantDataCountries": ["NO"],
}

# ── Scenario data from obj_Activity_MISSING.xml ───────────────────────
# (verbatim from the RESQML source)
VARIABLES = [
    {"Name": "ModTable, Oil/water contact OWC 1",  "QuantityType": "Low/Base/High",
     "Low": 1650.0,                  "Base": 1660.0,               "High": 1670.0, "Group": "Skirt"},
    {"Name": "ModTable, Oil/water contact OWC 2",  "QuantityType": "Low/Base/High",
     "Low": 1667.0,                  "Base": 1677.0,               "High": 1687.0, "Group": "Centre"},
    {"Name": "ModTable, Oil/water contact OWC 3",  "QuantityType": "Low/Base/High",
     "Low": 1667.0,                  "Base": 1677.0,               "High": 1687.0, "Group": "Centre"},
    {"Name": "ModTable, Oil/water contact OWC 4",  "QuantityType": "Low/Base/High",
     "Low": 1650.0,                  "Base": 1660.0,               "High": 1670.0, "Group": "Skirt"},
    {"Name": "ModTable, Oil/water contact OWC 5",  "QuantityType": "Low/Base/High",
     "Low": 1667.0,                  "Base": 1677.0,               "High": 1687.0, "Group": "Centre"},
    {"Name": "ModTable, Oil/water contact OWC 6",  "QuantityType": "Low/Base/High",
     "Low": 1667.0,                  "Base": 1677.0,               "High": 1687.0, "Group": "Centre"},
    {"Name": "ModTable, Oil/water contact OWC 7",  "QuantityType": "Low/Base/High",
     "Low": 1650.0,                  "Base": 1660.0,               "High": 1670.0, "Group": "Skirt"},
    {"Name": "std_valysar, Floodplain, PHIT, expected mean", "QuantityType": "Low/Base/High",
     "Low": 0.09000000357627869,      "Base": 0.10300000011920929,  "High": 0.11299999803304672, "Group": "Centre"},
    {"Name": "std_valysar, Channel, PHIT, expected mean",    "QuantityType": "Low/Base/High",
     "Low": 0.2653200030326843,       "Base": 0.27532124519348145,  "High": 0.2853200137615204,  "Group": "Centre"},
    {"Name": "std_valysar, Crevasse, PHIT, expected mean",   "QuantityType": "Low/Base/High",
     "Low": 0.19869999587535858,      "Base": 0.20869815349578857,  "High": 0.21870000660419464, "Group": "Centre"},
]

DESIGN_MATRIX = [
    {"Realization": 1, "Floodplain, PHIT, expected mean": "Base",
     "Channel, PHIT, expected mean": "Base", "Crevasse, PHIT, expected mean": "Base",
     "Skirt": "Base", "Center": "Base"},
    {"Realization": 2, "Floodplain, PHIT, expected mean": "Low",
     "Channel, PHIT, expected mean": "Low",  "Crevasse, PHIT, expected mean": "Low",
     "Skirt": "Low",  "Center": "Low"},
    {"Realization": 3, "Floodplain, PHIT, expected mean": "High",
     "Channel, PHIT, expected mean": "High", "Crevasse, PHIT, expected mean": "High",
     "Skirt": "High", "Center": "High"},
]


# ── Helpers ──────────────────────────────────────────────────────────────
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


def _make_param(title: str, kind: str, role: str, description: str,
                is_input: bool = True, is_output: bool = False,
                min_occurs: int = 0, max_occurs: int = 1,
                allowed_kind: str = "DataObject") -> Dict[str, Any]:
    return {
        "Title": title,
        "Description": description,
        "IsInput": is_input,
        "IsOutput": is_output,
        "MinOccurs": min_occurs,
        "MaxOccurs": max_occurs,
        "DefaultParameterKind": allowed_kind,
    }


def build_template(prefix: str, acl: dict, legal: dict) -> Dict[str, Any]:
    """Build an OSDU ActivityTemplate work-product-component record."""
    template_id = f"{prefix}:work-product-component--ActivityTemplate:{TEMPLATE_UUID}:1"
    return {
        "id": template_id,
        "kind": "osdu:wks:work-product-component--ActivityTemplate:1.0.0",
        "acl": acl,
        "legal": legal,
        "data": {
            "Name": "Drogon Valysar — Volumetrics Workflow Template",
            "Description": (
                "ActivityTemplate for the Drogon / Valysar DG1 volumetrics ensemble workflow. "
                "Covers three sequential steps: (1) generate per-realisation input parameters "
                "(OWC depths + PHIT), (2) run the RMS DecisionExample reservoir model workflow "
                "producing per-realisation volumes, (3) aggregate realisations into "
                "P10/P50/P90 statistics. "
                "All steps are captured as a single merged activity linked from "
                "the parent BusinessDecision record."
            ),
            "Originator": "markuslund.vevle@emerson.com",
            "ParameterTemplates": [
                _make_param(
                    "InputParameters", "string", "in",
                    "Input parameter table (ColumnBasedTable WPC) containing per-realisation OWC "
                    "depth and PHIT values for each segment and facies.",
                    is_input=True, is_output=False, allowed_kind="DataObject",
                ),
                _make_param(
                    "Process", "string", "in",
                    "Name of the RMS reservoir model / workflow that consumes the parameter table.",
                    is_input=True, is_output=False, allowed_kind="string",
                    min_occurs=1,
                ),
                _make_param(
                    "NumberOfRealizations", "string", "in",
                    "Total number of Monte Carlo / design-matrix realisations executed.",
                    is_input=True, is_output=False, allowed_kind="integer",
                    min_occurs=1,
                ),
                _make_param(
                    "Workflow", "string", "in",
                    "Workflow label within the RMS project.",
                    is_input=True, is_output=False, allowed_kind="string",
                ),
                _make_param(
                    "Method", "string", "in",
                    "Uncertainty sampling method (e.g. User_Defined, Monte_Carlo).",
                    is_input=True, is_output=False, allowed_kind="string",
                ),
                _make_param(
                    "ReportTableName", "string", "in",
                    "Name of the output statistics report table in RMS (e.g. DecisionExample_report).",
                    is_input=True, is_output=False, allowed_kind="string",
                ),
                _make_param(
                    "Variables", "string", "in",
                    "Serialised JSON list of uncertainty variable definitions "
                    "(Low/Base/High per OWC contact and PHIT per facies).",
                    is_input=True, is_output=False, allowed_kind="string",
                ),
                _make_param(
                    "DesignMatrix", "string", "in",
                    "Serialised JSON design matrix assigning a Low/Base/High scenario "
                    "to each realisation for every variable.",
                    is_input=True, is_output=False, allowed_kind="string",
                ),
                _make_param(
                    "OutputParameters", "string", "out",
                    "Generated per-realisation input parameter table (ColumnBasedTable WPC).",
                    is_input=False, is_output=True, allowed_kind="DataObject",
                ),
                _make_param(
                    "OutputVolumes", "string", "out",
                    "Per-realisation reservoir estimated volumes (RAW REV WPC).",
                    is_input=False, is_output=True, allowed_kind="DataObject",
                    min_occurs=1,
                ),
                _make_param(
                    "ReportTable", "string", "out",
                    "Statistical aggregation of realisations (STAT REV WPC: P10/P50/P90).",
                    is_input=False, is_output=True, allowed_kind="DataObject",
                    min_occurs=1,
                ),
            ],
        },
    }


def build_dataspace(prefix: str, acl: dict, legal: dict) -> Dict[str, Any]:
    """Build an OSDU dataset--ETPDataspace record for the Drogon RDDMS dataspace."""
    return {
        "id":    f"{prefix}:dataset--ETPDataspace:{DATASPACE_ID_SUFFIX}:1",
        "kind":  "osdu:wks:dataset--ETPDataspace:1.0.0",
        "acl":   acl,
        "legal": legal,
        "data": {
            "Name": f"Drogon DG2 Geomodel Dataspace ({DATASPACE_NAME})",
            "Description": (
                "RDDMS dataspace holding the Drogon DG2 geomodel EPC files exported from RMS "
                "(drogon_activity.epc, drogon_tables.epc)."
            ),
            "DatasetProperties": {
                "URI": f"eml:///dataspace({DATASPACE_NAME})",
                "ServerURL": "wss://equinorswedev.energy.azure.com/api/reservoir-ddms-etp/v2/",
            },
        },
    }


def build_activity(
    prefix: str,
    acl: dict,
    legal: dict,
    template_id: str,
    reservoir_id: str,
    workproduct_id: str,
    params_wpc_id: str,
    raw_wpc_id: str,
    stat_wpc_id: str,
    dataspace_id: str = "",
) -> Dict[str, Any]:
    """Build a single merged OSDU Activity WPC record."""
    activity_id = f"{prefix}:work-product-component--Activity:{ACTIVITY_UUID}:1"

    parameters: List[Dict[str, Any]] = [
        # ── inputs / process ────────────────────────────────────────
        {
            "Title": "InputParameters",
            "Description": "Per-realisation OWC depth and PHIT input parameter table",
            "ParameterKindID": f"{prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{prefix}:reference-data--ParameterRole:Input:1",
            "DataObjectParameter": params_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ColumnBasedTable-params"}],
        },
        {
            "Title": "Process",
            "Description": "RMS reservoir model workflow that executes the realisations",
            "ParameterKindID": f"{prefix}:reference-data--ParameterKind:String:1",
            "ParameterRoleID": f"{prefix}:reference-data--ParameterRole:Input:1",
            "StringParameter": "RMS DecisionExample — Drogon Valysar",
        },
        {
            "Title": "NumberOfRealizations",
            "Description": "Number of realisations executed",
            "ParameterKindID": f"{prefix}:reference-data--ParameterKind:Integer:1",
            "ParameterRoleID": f"{prefix}:reference-data--ParameterRole:Input:1",
            "IntegerParameter": 3,
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
            "Description": "Uncertainty sampling method",
            "ParameterKindID": f"{prefix}:reference-data--ParameterKind:String:1",
            "ParameterRoleID": f"{prefix}:reference-data--ParameterRole:Input:1",
            "StringParameter": "User_Defined",
        },
        {
            "Title": "ReportTableName",
            "Description": "Name of the output statistics report table in RMS",
            "ParameterKindID": f"{prefix}:reference-data--ParameterKind:String:1",
            "ParameterRoleID": f"{prefix}:reference-data--ParameterRole:Input:1",
            "StringParameter": "DecisionExample_report",
        },
        {
            "Title": "Variables",
            "Description": (
                "Uncertainty variable configuration: OWC contacts (7 segments, Low/Base/High) "
                "and PHIT per facies (Floodplain, Channel, Crevasse), all Low/Base/High."
            ),
            "ParameterKindID": f"{prefix}:reference-data--ParameterKind:String:1",
            "ParameterRoleID": f"{prefix}:reference-data--ParameterRole:Input:1",
            "StringParameter": json.dumps(VARIABLES, separators=(",", ":")),
        },
        {
            "Title": "DesignMatrix",
            "Description": (
                "Design matrix assigning Low/Base/High scenario per variable per realisation. "
                "Realisation 1 = Base, 2 = Low, 3 = High (all variables correlated)."
            ),
            "ParameterKindID": f"{prefix}:reference-data--ParameterKind:String:1",
            "ParameterRoleID": f"{prefix}:reference-data--ParameterRole:Input:1",
            "StringParameter": json.dumps(DESIGN_MATRIX, separators=(",", ":")),
        },
        # ── outputs ─────────────────────────────────────────────────
        {
            "Title": "OutputParameters",
            "Description": "Generated per-realisation input parameter table (ColumnBasedTable WPC)",
            "ParameterKindID": f"{prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{prefix}:reference-data--ParameterRole:Output:1",
            "DataObjectParameter": params_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ColumnBasedTable-params"}],
        },
        {
            "Title": "OutputVolumes",
            "Description": "Per-realisation estimated volumes (RAW REV WPC)",
            "ParameterKindID": f"{prefix}:reference-data--ParameterKind:DataObject:1",
            "ParameterRoleID": f"{prefix}:reference-data--ParameterRole:Output:1",
            "DataObjectParameter": raw_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "REV-raw"}],
        },
        {
            "Title": "ReportTable",
            "Description": "Statistical aggregation of realisations (STAT REV WPC: P10/P50/P90)",
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
                "RDDMS ETP dataspace containing the Drogon DG2 geomodel EPC files "
                "(drogon_activity.epc, drogon_tables.epc) exported from RMS."
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
            "Name": "Drogon Valysar — DG1 Volumetrics Workflow Run",
            "Description": (
                "Single merged activity capturing the full three-step DG1 volumetrics "
                "workflow for the Valysar formation of the Drogon field. "
                "Step 1: generate per-realisation input parameters (OWC depths for 7 "
                "fault blocks, PHIT for Floodplain/Channel/Crevasse). "
                "Step 2: run the RMS DecisionExample workflow producing 3 realisations "
                "of reservoir estimated volumes. "
                "Step 3: aggregate realisations into P10/P50/P90 statistical volumes. "
                "Scenario configuration (design matrix + variables) is taken verbatim "
                "from the RESQML obj_Activity document (obj_Activity_MISSING.xml → "
                "drogon_activity.epc)."
            ),
            "Originator": "markuslund.vevle@emerson.com",
            "CreationDateTime": "2026-02-13T10:21:57.365Z",
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


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate Drogon activity manifest")
    ap.add_argument("--masterwp",  default=str(SCRIPT_DIR / "manifest_masterwp_drogon.json"))
    ap.add_argument("--params",    default=str(SCRIPT_DIR / "manifest_wpcparams_drogon.json"))
    ap.add_argument("--rawvol",    default=str(SCRIPT_DIR / "manifest_wpcraw_drogon.json"))
    ap.add_argument("--statvol",   default=str(SCRIPT_DIR / "manifest_wpcstat_drogon.json"))
    ap.add_argument("--manifest",  default=str(SCRIPT_DIR / "manifest_activity_drogon.json"))
    ap.add_argument("--id-prefix", default="dev")
    args = ap.parse_args()

    masterwp = load_json(args.masterwp)
    params   = load_json(args.params)
    rawvol   = load_json(args.rawvol)
    statvol  = load_json(args.statvol)

    # ── Extract canonical IDs ────────────────────────────────────────
    reservoir_id = _find_id(masterwp, "master-data--Reservoir:")
    if not reservoir_id:
        raise SystemExit("ERROR: could not find Reservoir ID in masterwp manifest")

    # Work product (may be in Data.WorkProducts list or Data.WorkProduct dict)
    workproduct_id = _find_id(masterwp, "work-product:")
    if not workproduct_id:
        raise SystemExit("ERROR: could not find WorkProduct ID in masterwp manifest")

    params_wpc_id = _find_id(params,  "ColumnBasedTable")
    raw_wpc_id    = _find_id(rawvol,  "ReservoirEstimatedVolumes")
    stat_wpc_id   = _find_id(statvol, "ReservoirEstimatedVolumes")

    for label, val in [("params_wpc_id", params_wpc_id),
                       ("raw_wpc_id", raw_wpc_id),
                       ("stat_wpc_id", stat_wpc_id)]:
        if not val:
            raise SystemExit(f"ERROR: could not find {label}")

    # ── Use ACL / legal from Reservoir record ───────────────────────
    acl = legal = None
    for rec in masterwp.get("MasterData", []):
        if "master-data--Reservoir:" in rec.get("kind", ""):
            acl   = rec.get("acl",   DEFAULT_ACL)
            legal = rec.get("legal", DEFAULT_LEGAL)
            break
    acl   = acl   or DEFAULT_ACL
    legal = legal or DEFAULT_LEGAL

    prefix = args.id_prefix
    template_id = f"{prefix}:work-product-component--ActivityTemplate:{TEMPLATE_UUID}:1"
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


if __name__ == "__main__":
    main()
