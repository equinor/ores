#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_activity_dg2.py - Generate comprehensive OSDU ActivityTemplate + Activity
manifest for the Drogon DG2 FMU workflow.

Designed to capture the **complete model reproduction** for one decision gate:
  INPUTS   → seismic, horizons, strat column, wells, reservoir properties
  WORKFLOW → ERT orchestration (DESIGN2PARAMS → RMS → OPM Flow → post‑processing)
  OUTPUTS  → volumes, production profiles, maps, grid properties

Based on the real Drogon FMU model (equinor/fmu-drogon, tutorial 24.3.1):
  - 250 realisations, one‑by‑one sensitivity design
  - Forward model chain: DESIGN2PARAMS → DESIGN_KW → RMS(MAIN) → ECLCOMPRESS
    → OPM_FLOW → export_tables → export_maps → export_ecl_roff → sim2seis
  - Uncertainty parameters from global_variables.dist
  - 7 fault segments (regions), 3 zones (Valysar, Therys, Volon)
  - Wells: 55_33‑1 (appraisal), A1..A4 (producers), A5..A6 (water injectors)
  - Production vectors: FOPR, FGPR, FWPR, FOPT, FGPT, FWPT, FPR, FWCT, FGOR

Reads:
  ../drogon/manifest_masterwp_drogon.json   - Reservoir + WP IDs, acl, legal
  manifest_wpcparams_dg2.json               - DG2 ColumnBasedTable WPC ID
  manifest_wpcraw_dg2.json                  - DG2 RAW REV WPC ID
  manifest_wpcstat_dg2.json                 - DG2 Statistics REV WPC ID
  manifest_wpc_production_dg2.json          - DG2 Production forecast WPC ID

Output:
  manifest_activity_dg2.json

Usage:
  python demo/drogon_dg2/gen_activity_dg2.py
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent        # demo/drogon_dg2
DG1_DIR    = SCRIPT_DIR.parent / "drogon"            # demo/drogon

# ── Stable deterministic UUIDs for DG2 ──────────────────────────────
# Keep original seeds so OSDU creates new versions (not new records)
_NS = uuid.UUID("a0000000-d509-4e00-8000-000000000000")
TEMPLATE_UUID_DG2 = str(uuid.uuid5(_NS, "dg2-volumetrics-template"))
ACTIVITY_UUID_DG2 = str(uuid.uuid5(_NS, "dg2-volumetrics-activity"))

# ETP Dataspace - shared with DG1 (same geomodel)
DATASPACE_NAME = "maap/drogon_dg"
DATASPACE_ID_SUFFIX = DATASPACE_NAME.replace("/", "-")

DEFAULT_ACL = {
    "owners":  ["data.default.owners@dev.dataservices.energy"],
    "viewers": ["data.default.viewers@dev.dataservices.energy"],
}
DEFAULT_LEGAL = {
    "legaltags": ["opendes-private-usa-default"],
    "otherRelevantDataCountries": ["NO"],
}

# ── Real Drogon FMU model reference data ─────────────────────────────

# Uncertainty parameters - from global_variables.dist (tutorial 24.3.1)
UNCERTAINTY_PARAMETERS = [
    # Permeability anisotropy (Kv/Kh ratios)
    {"Name": "KVKH_CHANNEL",   "Distribution": "UNIFORM", "Min": 0.4,  "Max": 0.8},
    {"Name": "KVKH_CREVASSE",  "Distribution": "UNIFORM", "Min": 0.1,  "Max": 0.5},
    {"Name": "KVKH_US",        "Distribution": "UNIFORM", "Min": 0.4,  "Max": 0.8},
    {"Name": "KVKH_LS",        "Distribution": "UNIFORM", "Min": 0.5,  "Max": 0.9},
    # Fluid contacts
    {"Name": "FWL_CENTRAL",    "Distribution": "UNIFORM", "Min": 1672, "Max": 1682},
    {"Name": "FWL_NORTH_HORST","Distribution": "UNIFORM", "Min": 1655, "Max": 1665},
    {"Name": "GOC_NORTH_HORST","Distribution": "UNIFORM", "Min": 1635, "Max": 1645},
    # Fault transmissibility
    {"Name": "FAULT_SEAL_SCALING", "Distribution": "LOGUNIF", "Min": 0.1, "Max": 10},
    # Relative permeability interpolation
    {"Name": "RELPERM_INT_WO", "Distribution": "UNIFORM", "Min": -1,   "Max": 1},
    {"Name": "RELPERM_INT_GO", "Distribution": "UNIFORM", "Min": -1,   "Max": 1},
    # Isocore trend contour uncertainty
    {"Name": "ISOTREND_ALT1W_VALYSAR", "Distribution": "UNIFORM", "Min": 0.8, "Max": 1.0},
    {"Name": "ISOTREND_ALT1W_THERYS",  "Distribution": "UNIFORM", "Min": 0.8, "Max": 1.0},
    {"Name": "ISOTREND_ALT1W_VOLON",   "Distribution": "UNIFORM", "Min": 0.4, "Max": 0.6},
    # APS facies probability
    {"Name": "VALYSAR_APS_PROB_CHANNEL",      "Distribution": "UNIFORM", "Min": 0.24, "Max": 0.44},
    {"Name": "THERYS_APS_PROB_LOWSHOREFACE",  "Distribution": "UNIFORM", "Min": 0.2,  "Max": 0.4},
    {"Name": "THERYS_APS_PROB_UPSHOREFACE",   "Distribution": "UNIFORM", "Min": 0.1,  "Max": 0.3},
    {"Name": "VOLON_APS_PROB_CHANNEL",        "Distribution": "UNIFORM", "Min": 0.52, "Max": 0.72},
]

# Model switches - from global_variables_switches.dist
MODEL_SWITCHES = {
    "DCONV_ALTERNATIVE": 2,         # 1: constant V overburden, 2: V=a*Tmap+b
    "HUM_MODEL_MODE": 1,            # 0: prediction, 1: simulation
    "PETROMODEL_ALTERNATIVE": 1,    # 0: simple const/facies, 1: standard MVA
    "FACIESMODEL_ALTERNATIVE": 1,   # 0: RMS algorithms, 1: APS in all zones
    "FACIES_VALYSAR_SEISCOND": 1,   # 0: no seismic conditioning, 1: with
    "FACIES_THERYS_ALT2": 1,        # 0: indicators, 1: belts
}

# Reference porosity per facies (from global_variables.yml)
REFERENCE_PROPERTIES = {
    "Valysar": {
        "PORO": {"Floodplain": 0.10, "Channel": 0.27, "Crevasse": 0.22, "Coal": 0.0},
        "PERMH": {"Floodplain": 1.0, "Channel": 1000.0, "Crevasse": 100.0, "Coal": 0.0},
    },
    "Therys": {
        "PORO": {"Offshore": 0.10, "Lowershoreface": 0.23, "Uppershoreface": 0.31, "Calcite": 0.0},
        "PERMH": {"Offshore": 2.0, "Lowershoreface": 40.0, "Uppershoreface": 1200.0, "Calcite": 0.0},
    },
    "Volon": {
        "PORO": {"Floodplain": 0.13, "Channel": 0.20, "Calcite": 0.0},
        "PERMH": {"Floodplain": 1.0, "Channel": 1100.0, "Calcite": 0.0},
    },
}

# Reservoir regions - 7 segments with fluid contacts
REGIONS = {
    "WestLowland":  {"NUM": 1, "OWC": 1660.0, "GOC": 1000.0},
    "CentralSouth": {"NUM": 2, "OWC": 1677.0, "GOC": 1000.0},
    "CentralNorth": {"NUM": 3, "OWC": 1677.0, "GOC": 1000.0},
    "NorthHorst":   {"NUM": 4, "OWC": 1660.0, "GOC": 1640.0},
    "CentralRamp":  {"NUM": 5, "OWC": 1677.0, "GOC": 1000.0},
    "CentralHorst": {"NUM": 6, "OWC": 1677.0, "GOC": 1000.0},
    "EastLowland":  {"NUM": 7, "OWC": 1660.0, "GOC": 1000.0},
}

# Wells in the Drogon model
WELLS = {
    "appraisal": ["55_33-1"],
    "producers": ["A1", "A2", "A3", "A4"],
    "injectors": ["A5", "A6"],
    "rft_wells": ["R_A2", "R_A3", "R_A4", "R_A5", "R_A6"],
}

# Stratigraphic horizons
HORIZONS = ["TopVolantis", "TopTherys", "TopVolon", "BaseVolantis"]
ZONES = ["Valysar", "Therys", "Volon"]

# Seismic data references (from global_variables.yml)
SEISMIC_DATA = {
    "static_3d": {
        "vintage": "2018-01-01",
        "near_amplitude": "owexport_ampl_near_time_2018.segy",
        "far_amplitude": "owexport_ampl_far_time_2018.segy",
        "near_relai": "owexport_rai_near_time_2018.segy",
        "far_relai": "owexport_rai_far_time_2018.segy",
    },
    "monitor_4d": [
        {"baseline": "2018-01-01", "monitor": "2018-07-01", "amplitude": "owexport_ampl_18h_18v.segy"},
        {"baseline": "2018-01-01", "monitor": "2019-07-01", "amplitude": "owexport_ampl_19h_18v.segy"},
        {"baseline": "2018-01-01", "monitor": "2020-07-01", "amplitude": "owexport_ampl_20h_18v.segy"},
    ],
}

# ERT forward model chain (the actual execution pipeline)
FORWARD_MODEL_CHAIN = [
    "DESIGN2PARAMS",        # Parse design matrix → parameters.txt
    "DESIGN_KW",            # Populate templates with parameter values
    "COPY_DIRECTORY",       # Copy RMS bin + input files
    "COPY_FILE",            # Copy Eclipse includes (PVT, RXVD, summary, schedule)
    "RMS",                  # Run RMS MAIN workflow (geomodel → grid → properties → wells)
    "ECLCOMPRESS",          # Compress Eclipse input files
    "OPM_FLOW",             # Run OPM Flow reservoir simulator
    "MAKE_SYMLINK",         # Symlink EGRID/INIT/UNRST for post-processing
    "PRTVOL2CSV",           # Extract volumes from Eclipse PRT → CSV
    "RES2CSV:summary",      # Summary vectors → Arrow (production profiles)
    "RES2CSV:satfunc",      # Saturation functions → CSV
    "RES2CSV:pvt",          # PVT tables → CSV
    "RES2CSV:vfp",          # VFP tables → Arrow
    "RES2CSV:gruptree",     # Group tree → CSV
    "RES2CSV:wellcompletiondata",  # Well completion data → Arrow
    "GRID3D_HC_THICKNESS",  # HC thickness maps (oil + gas)
    "GRID3D_AVERAGE_MAP",   # Average parameter maps from Eclipse
    "EXPORT_ECL_ROFF",      # Eclipse restart/init → ROFF (grid properties)
    "GEN_DATA_RFT_WELLS",   # RFT pressure data extraction
    "GEN_DATA_TRACER",      # Tracer breakthrough data
    "SIM2SEIS",             # Simulated seismic from simulation results
    "ERT_SUMMARY_PLOTTING", # ERT summary vector plotting
]

# Eclipse summary vectors tracked
SUMMARY_VECTORS = {
    "field_rates": ["FOPR", "FGPR", "FWPR", "FLPR", "FVPR", "FWIR", "FGIR"],
    "field_cumul": ["FOPT", "FGPT", "FWPT", "FWIT", "FGIT"],
    "field_ratios": ["FWCT", "FGOR", "FGLR"],
    "field_pressure": ["FPR"],
    "field_in_place": ["FOIP", "FGIP", "FWIP"],
    "well_rates": ["WOPR", "WGPR", "WWPR", "WLPR", "WWIR", "WGIR"],
    "well_cumul": ["WOPT", "WGPT", "WWPT", "WWIT", "WGIT"],
    "well_ratios": ["WWCT", "WGOR"],
    "well_perf": ["WBHP", "WTHP", "WPI"],
    "region_data": ["RPR", "ROIP", "ROE", "RGIP"],
    "tracers": ["WTPRWT1", "WTPRWT2", "WTPCWT1", "WTPCWT2"],
}

# Design matrix configuration
DESIGN_MATRIX_CONFIG = {
    "FileName": "design_matrix_one_by_one.xlsx",
    "DesignSheet": "DesignSheet01",
    "DefaultSheet": "DefaultValues",
    "NumRealizations": 250,
    "Type": "one-by-one sensitivity",
    "Description": (
        "One-by-one sensitivity design: each uncertainty parameter is varied "
        "individually while others are kept at base values. Allows tornado "
        "chart analysis of parameter impact on response."
    ),
}

# ERT configuration (from drogon_design.ert)
ERT_CONFIG = {
    "ConfigFile": "drogon_design.ert",
    "CaseDir": "01_drogon_design",
    "EclipseName": "DROGON",
    "RMSProject": "drogon.rms14.2.1",
    "RMSVersion": "14.2.1",
    "RMSWorkflow": "MAIN",
    "EclipseDataTemplate": "DROGON_HIST.DATA",
    "Simulator": "OPM_FLOW",
    "QueueSystem": "LSF",
    "NumCPU": 1,
    "NumRealizations": 250,
    "MaxRuntime": 18000,
    "RandomSeed": 123456,
    "ObservationsFile": "drogon_wbhp_rft_wct_gor_tracer_4d_plt.obs",
}

# FMU config references
FMUCONFIG = {
    "GlobalVariables": "fmuconfig/output/global_variables.yml",
    "GlobalVariablesTemplate": "fmuconfig/output/global_variables.yml.tmpl",
    "RateScaling": "fmuconfig/output/rate_scaling.yml",
    "RateScalingTemplate": "fmuconfig/output/rate_scaling.yml.tmpl",
    "CoordinateSystem": "ST_WGS84_UTM37N_P32637",
    "Field": "DROGON",
    "Country": "Norway",
    "ModelName": "ff",
}

# Hook workflows
HOOK_WORKFLOWS = [
    {"Name": "echo_config_file",              "Hook": "PRE_SIMULATION", "Description": "Write ERT config file run information to scratch"},
    {"Name": "run_fmuconfig",                 "Hook": "PRE_SIMULATION", "Description": "Update global_variables.yml and .tmpl files"},
    {"Name": "run_fmuconfig_rate",            "Hook": "PRE_SIMULATION", "Description": "Update rate_scaling.yml and .tmpl files"},
    {"Name": "wf_fmuobs",                     "Hook": "PRE_SIMULATION", "Description": "Create YAML version of ERT observations for Webviz"},
    {"Name": "xhook_create_case_metadata",    "Hook": "PRE_SIMULATION", "Description": "Create case metadata using fmu-dataio"},
]

# ── Production profile data (real OPM Flow output, realization-0) ────
# Source: equinor/webviz-subsurface-testdata, 01_drogon_ahm, realization-0/iter-0
# Monthly summary vectors from unsmry--monthly.csv (2018-01 to 2020-07)
PRODUCTION_PROFILE_P50 = {
    "Source": "webviz-subsurface-testdata/01_drogon_ahm/realization-0/iter-0",
    "StartDate": "2018-01-01",
    "EndDate": "2020-07-01",
    "Wells": WELLS,
    "FieldProduction": {
        "dates": [
            "2018-01-01","2018-02-01","2018-03-01","2018-04-01","2018-05-01",
            "2018-06-01","2018-07-01","2018-08-01","2018-09-01","2018-10-01",
            "2018-11-01","2018-12-01","2019-01-01","2019-02-01","2019-03-01",
            "2019-04-01","2019-05-01","2019-06-01","2019-07-01","2019-08-01",
            "2019-09-01","2019-10-01","2019-11-01","2019-12-01","2020-01-01",
            "2020-02-01","2020-03-01","2020-04-01","2020-05-01","2020-06-01",
            "2020-07-01",
        ],
        "FOPR_Sm3d": [
            0.0,3970.2,3980.0,7974.2,8002.0,7392.6,6410.7,10161.7,10515.3,
            14259.3,13142.6,10962.8,10603.0,10388.9,10134.9,9810.2,9558.2,
            9364.9,9114.0,8706.0,8369.2,8096.3,7641.7,7214.0,6923.2,6529.5,
            6282.0,6069.8,5810.2,5681.1,5520.3,
        ],
        "FGPR_Sm3d": [
            0.0,559088.4,556397.9,1084306.6,1073526.5,993481.6,875296.4,
            1365438.1,1382394.2,1956233.0,1896926.8,1494532.1,1417747.9,
            1379509.0,1337871.5,1290774.4,1255550.0,1234463.5,1209852.6,
            1176561.2,1160631.8,1153680.1,1108378.4,1055485.6,1017094.1,
            951073.4,907477.2,869131.2,821222.4,792453.7,766359.7,
        ],
        "FWPR_Sm3d": [
            0.0,41.3,38.2,77.7,77.9,100.5,169.1,347.6,822.0,1923.9,2615.5,
            2470.0,2771.6,3041.3,3288.4,3598.5,3970.7,4350.2,4783.1,5256.4,
            5703.3,6081.3,6349.9,6547.1,6765.2,6892.6,7030.7,7171.1,7265.9,
            7413.1,7581.4,
        ],
        "FWIR_Sm3d": [
            0.0,0.0,0.0,0.0,0.0,8000.0,8000.0,8000.0,8000.0,8000.0,8000.0,
            16000.0,16000.0,16000.0,16000.0,16000.0,16000.0,16000.0,16000.0,
            16000.0,16000.0,16000.0,16000.0,16000.0,16000.0,16000.0,16000.0,
            16000.0,16000.0,16000.0,16000.0,
        ],
        "FPR_barsa": [
            301.0,295.4,291.1,285.2,280.9,280.1,280.2,277.4,274.7,270.3,
            264.5,262.4,261.8,261.3,260.8,260.4,260.0,259.8,259.3,258.8,
            258.3,257.7,257.2,256.9,256.6,256.5,256.4,256.4,256.6,256.8,257.0,
        ],
        "FOPT_Sm3": [
            0,107186,218503,429416,668809,902715,1098834,1367803,1688689,
            2040743,2457924,2799600,3131530,3455186,3741322,4049177,4338311,
            4593814,4870662,5145290,5408784,5655302,5897222,6110950,6327287,
            6533738,6718742,6907922,7084592,7239404,7406547,
        ],
        "FWCT_frac": [
            0.0,0.0103,0.0095,0.0097,0.0096,0.0134,0.0257,0.0331,0.0725,
            0.1189,0.166,0.1839,0.2072,0.2264,0.245,0.2684,0.2935,0.3172,
            0.3442,0.3765,0.4053,0.4289,0.4538,0.4758,0.4942,0.5135,0.5281,
            0.5416,0.5557,0.5661,0.5787,
        ],
    },
}

# ── Volume estimates from real Drogon model (field totals, P50) ──────
VOLUME_ESTIMATES = {
    "STOIIP_MSm3": 45.4,       # Stock tank oil initially in place
    "GIIP_GSm3": 6.4,          # Gas initially in place
    "RecoverableOil_MSm3": 15.2,  # EUR oil
    "RecoveryFactor_pct": 33.5,
    "ByRegion": {
        "WestLowland":  {"STOIIP_MSm3": 0.50, "RF_pct": 30.0},
        "CentralSouth": {"STOIIP_MSm3": 6.22, "RF_pct": 35.0},
        "CentralNorth": {"STOIIP_MSm3": 7.81, "RF_pct": 34.0},
        "NorthHorst":   {"STOIIP_MSm3": 10.85, "RF_pct": 36.0},
        "CentralRamp":  {"STOIIP_MSm3": 5.14, "RF_pct": 32.0},
        "CentralHorst": {"STOIIP_MSm3": 5.61, "RF_pct": 33.0},
        "EastLowland":  {"STOIIP_MSm3": 9.27, "RF_pct": 31.0},
    },
    "ByZone": {
        "Valysar": {"STOIIP_MSm3": 28.5, "RF_pct": 35.0},
        "Therys":  {"STOIIP_MSm3": 11.2, "RF_pct": 31.0},
        "Volon":   {"STOIIP_MSm3": 5.7,  "RF_pct": 29.0},
    },
}

# ── Output artifact types ────────────────────────────────────────────
OUTPUT_ARTIFACTS = {
    "volumes": {
        "eclipse_vol_csv": "share/results/volumes/eclipse--vol.csv",
        "description": "Eclipse PRT volumes per region at initial timestep",
    },
    "production_tables": {
        "summary_arrow": "share/results/tables/ecl_summary/DROGON-<IENS>.arrow",
        "satfunc_csv": "share/results/tables/relperm.csv",
        "pvt_csv": "share/results/tables/pvt.csv",
        "vfp_arrow": "share/results/tables/vfp/vfp*.arrow",
        "gruptree_csv": "share/results/tables/gruptree.csv",
        "wellcompletiondata_arrow": "share/results/tables/wellcompletiondata.arrow",
    },
    "maps": {
        "hc_thickness_oil": "share/results/maps/*oil_thickness*.gri",
        "hc_thickness_gas": "share/results/maps/*gas_thickness*.gri",
        "avg_parameter_maps": "share/results/maps/*average*.gri",
        "facies_thickness": "share/results/maps/*facies_thickness*.gri",
    },
    "grid_properties": {
        "roff_files": "share/results/grids/eclgrid--*.roff",
        "description": "Eclipse restart and init parameters in ROFF format",
    },
    "sim2seis": {
        "synthetic_seismic": "share/results/seismic/*.segy",
        "description": "Simulated seismic from reservoir simulation results",
    },
}


# ── Helper: import DG1 shared ────────────────────────────────────────
import sys
if str(DG1_DIR) not in sys.path:
    sys.path.insert(0, str(DG1_DIR))
from _shared import load_json  # noqa: E402


def _find_id(manifest: Dict[str, Any], kind_fragment: str) -> str:
    """Find the first record ID matching *kind_fragment* in a manifest."""
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


def _pt(title, desc, *, is_in=True, is_out=False, kind="DataObject",
        min_occ=0, max_occ=1, role="Input"):
    """Create a ParameterTemplate entry.

    role: 'Input'    - spatial/physical data (seismic, wells, horizons etc.)
          'Workflow' - apps, process config, design, sequence definitions
          'Output'  - generated artefacts
    """
    entry = {
        "Title": title,
        "Description": desc,
        "IsInput": is_in,
        "IsOutput": is_out,
        "MinOccurs": min_occ,
        "MaxOccurs": max_occ,
        "DefaultParameterKind": kind,
    }
    if role != "Input":
        entry["DefaultParameterRole"] = role
    return entry


# ═══════════════════════════════════════════════════════════════════════
#  BUILD TEMPLATE
# ═══════════════════════════════════════════════════════════════════════

def build_template(prefix, acl, legal):
    template_id = f"{prefix}:work-product-component--ActivityTemplate:{TEMPLATE_UUID_DG2}:1"
    return {
        "id": template_id,
        "kind": "osdu:wks:work-product-component--ActivityTemplate:1.0.0",
        "acl": acl,
        "legal": legal,
        "data": {
            "Name": "Drogon - Full FMU Workflow Template (ERT → RMS → OPM Flow)",
            "Description": (
                "Comprehensive ActivityTemplate for the Drogon FMU reservoir model. "
                "Captures the complete input-to-output pipeline for one decision gate: "
                "seismic + horizons + wells + stratigraphy + uncertainty distributions → "
                "ERT orchestration (DESIGN2PARAMS → RMS MAIN → OPM Flow) → "
                "volumes, production profiles, maps, grid properties. "
                "Based on the official equinor/fmu-drogon tutorial model (24.3.1). "
                "250 realisations, one-by-one sensitivity design."
            ),
            "Originator": "markuslund.vevle@emerson.com",
            "ParameterTemplates": [
                # ── INPUTS: Subsurface data ──────────────────────────
                _pt("SeismicData", "3D/4D seismic interpretation data used for "
                    "facies conditioning (near/far offset, amplitude/RelAI). "
                    "Static 3D vintage and 3 monitor 4D surveys.",
                    kind="string"),
                _pt("Horizons", "Structural horizon surfaces: TopVolantis, "
                    "TopTherys, TopVolon, BaseVolantis. Input to RMS structural "
                    "model and Eclipse grid.",
                    kind="string"),
                _pt("StratigraphicColumn", "Stratigraphic column defining the "
                    "Volantis Group: Valysar Fm, Therys Fm, Volon Fm. Used for "
                    "zone definitions and facies grouping.",
                    kind="string"),
                _pt("Wells", "Well data: appraisal (55_33-1), producers (A1-A4), "
                    "injectors (A5-A6), RFT reference (R_A2..R_A6). Includes "
                    "trajectories, logs, completions.",
                    kind="string"),
                _pt("ReservoirProperties", "Reference petrophysical properties "
                    "per formation and facies: porosity, permeability, Kv/Kh, "
                    "J-functions, PVT, fluid contacts per region.",
                    kind="string"),
                _pt("FaultModel", "Fault framework with 7 regions and fault seal "
                    "scaling (LOGUNIF 0.1–10). Includes multregt template.",
                    kind="string"),
                _pt("Observations", "History matching observations: WBHP, RFT, "
                    "WCT, GOR, tracers, 4D seismic, PLT data.",
                    kind="string"),

                # ── WORKFLOW: ERT orchestration & design ────────────
                _pt("ErtConfig", "ERT configuration: drogon_design.ert defining "
                    "the full forward model chain, LSF queue settings, random "
                    "seed, and run parameters.",
                    kind="string", min_occ=1, role="Workflow"),
                _pt("DesignMatrix", "Design matrix Excel file "
                    "(design_matrix_one_by_one.xlsx): DesignSheet01 with "
                    "one-by-one sensitivity layout, DefaultValues sheet.",
                    kind="string", min_occ=1, role="Workflow"),
                _pt("UncertaintyParameters", "Uncertainty parameter distributions "
                    "from global_variables.dist: Kv/Kh, FWL, GOC, fault seal, "
                    "relperm interpolation, APS facies probabilities.",
                    kind="string", min_occ=1, role="Workflow"),
                _pt("ModelSwitches", "Model alternative switches: DCONV, HUM, "
                    "PETROMODEL, FACIESMODEL, seismic conditioning, facies belts.",
                    kind="string", role="Workflow"),
                _pt("FmuConfig", "fmuconfig global_variables.yml: complete model "
                    "parameterisation including dates, seismic paths, grids, "
                    "regions, facies, petro constants, J-functions, relperm.",
                    kind="string", min_occ=1, role="Workflow"),
                _pt("ForwardModelChain", "Ordered list of ERT forward models: "
                    "DESIGN2PARAMS → DESIGN_KW → RMS → ECLCOMPRESS → OPM_FLOW → "
                    "export_tables → export_maps → export_ecl_roff → sim2seis.",
                    kind="string", min_occ=1, role="Workflow"),
                _pt("NumberOfRealizations", "Number of realisations (250 for "
                    "one-by-one design).",
                    kind="integer", min_occ=1, role="Workflow"),

                # ── WORKFLOW: Simulation setup ───────────────────────
                _pt("RmsProject", "RMS project and workflow definition: project "
                    "name, version, workflow (MAIN).",
                    kind="string", role="Workflow"),
                _pt("EclipseDataTemplate", "Eclipse/OPM DATA file template "
                    "(DROGON_HIST.DATA) with INCLUDEs for grid, props, schedule.",
                    kind="string", role="Workflow"),
                _pt("HookWorkflows", "ERT hook workflows: fmuconfig update, "
                    "fmuobs YAML creation, case metadata via dataio.",
                    kind="string", role="Workflow"),

                # ── INPUTS: Existing OSDU objects ────────────────────
                _pt("InputParameterTable", "OSDU ColumnBasedTable WPC with "
                    "per-realisation input parameters (OWC depths + porosity).",
                    kind="DataObject"),
                _pt("GeoModelDataspace", "RDDMS ETP dataspace holding the Drogon "
                    "geomodel EPC files (structural model, shared DG1/DG2).",
                    kind="DataObject"),

                # ── OUTPUTS ──────────────────────────────────────────
                _pt("OutputParameterTable", "Generated per-realisation input "
                    "parameter table (ColumnBasedTable WPC).",
                    is_in=False, is_out=True),
                _pt("OutputVolumesRaw", "Per-realisation reservoir estimated "
                    "volumes (RAW REV WPC) - by region, zone, and facies.",
                    is_in=False, is_out=True, min_occ=1),
                _pt("OutputVolumesStats", "Statistical aggregation P10/P50/P90 "
                    "of volumes across realisations (STAT REV WPC).",
                    is_in=False, is_out=True, min_occ=1),
                _pt("OutputProductionForecast", "Field and well production "
                    "profiles (rates, cumulatives, pressures) as "
                    "ColumnBasedTable WPC.",
                    is_in=False, is_out=True, min_occ=1),
                _pt("OutputMaps", "HC thickness maps and average parameter maps "
                    "(regular surface grids).",
                    is_in=False, is_out=True, kind="string"),
                _pt("OutputGridProperties", "Eclipse grid properties exported to "
                    "ROFF: restart parameters, init properties.",
                    is_in=False, is_out=True, kind="string"),
                _pt("OutputSim2Seis", "Synthetic seismic computed from simulation "
                    "results for 4D comparison.",
                    is_in=False, is_out=True, kind="string"),
                _pt("OutputWellData", "RFT pressure data, tracer breakthrough, "
                    "well completion data.",
                    is_in=False, is_out=True, kind="string"),
                _pt("OutputEclipseTables", "Eclipse-derived tables: saturation "
                    "functions, PVT, VFP, group tree, summary vectors.",
                    is_in=False, is_out=True, kind="string"),

                # ── CONTEXT: Linked OSDU records ─────────────────────
                _pt("VolumeEstimates", "P50 volume estimates link to "
                    "statistical REV WPC record.",
                    is_in=False, is_out=True),
                _pt("ProductionProfileP50", "P50 production profile link to "
                    "ColumnBasedTable WPC with real OPM Flow output.",
                    is_in=False, is_out=True),
                _pt("ReservoirRecord", "OSDU Reservoir master-data record "
                    "for the Drogon field.",
                    kind="DataObject"),
                _pt("DevelopmentConcept", "DG2 Development Concept WPC record.",
                    is_in=False, is_out=True),
            ],
        },
    }


# ═══════════════════════════════════════════════════════════════════════
#  BUILD DATASPACE
# ═══════════════════════════════════════════════════════════════════════

def build_dataspace(prefix, acl, legal):
    return {
        "id":    f"{prefix}:dataset--ETPDataspace:{DATASPACE_ID_SUFFIX}:1",
        "kind":  "osdu:wks:dataset--ETPDataspace:1.0.0",
        "acl":   acl,
        "legal": legal,
        "data": {
            "Name": f"Drogon DG Geomodel Dataspace ({DATASPACE_NAME})",
            "Description": (
                "RDDMS dataspace holding the Drogon geomodel EPC files exported "
                "from RMS (drogon_activity.epc, drogon_tables.epc). "
                "Shared between DG1 and DG2 - same structural model."
            ),
            "DatasetProperties": {
                "URI": f"eml:///dataspace({DATASPACE_NAME})",
                "ServerURL": "wss://admeinterop.energy.azure.com/api/reservoir-ddms-etp/v2/",
            },
        },
    }


# ═══════════════════════════════════════════════════════════════════════
#  BUILD ACTIVITY
# ═══════════════════════════════════════════════════════════════════════

def build_activity(
    prefix, acl, legal,
    template_id, reservoir_id, workproduct_id,
    params_wpc_id, raw_wpc_id, stat_wpc_id,
    production_wpc_id="",
    dataspace_id="",
    devconcept_id="",
):
    activity_id = f"{prefix}:work-product-component--Activity:{ACTIVITY_UUID_DG2}:1"

    _kind = lambda k: f"{prefix}:reference-data--ParameterKind:{k}:"
    _role = lambda r: f"{prefix}:reference-data--ParameterRole:{r}:"

    parameters = [
        # ── INPUT: Seismic data ──────────────────────────────────
        {
            "Title": "SeismicData",
            "Description": (
                "Drogon 3D/4D seismic: static 3D vintage (2018-01-01) with "
                "near/far offset amplitude and RelAI; 3 monitor 4D surveys "
                "(18h-18v, 19h-18v, 20h-18v). Used for APS facies conditioning "
                "in Valysar. Template cube at 21.0.0 resolution."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Input"),
            "StringParameter": json.dumps(SEISMIC_DATA, separators=(",", ":")),
        },
        # ── INPUT: Horizons ──────────────────────────────────────
        {
            "Title": "Horizons",
            "Description": (
                "Structural horizon surfaces forming the Volantis Group "
                "framework. Exported from RMS to Eclipse grid."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Input"),
            "StringParameter": json.dumps(HORIZONS, separators=(",", ":")),
        },
        # ── INPUT: Stratigraphic column ──────────────────────────
        {
            "Title": "StratigraphicColumn",
            "Description": (
                "Volantis Group stratigraphy: Valysar Fm (fluvial: Floodplain, "
                "Channel, Crevasse, Coal), Therys Fm (marine: Offshore, "
                "Lowershoreface, Uppershoreface, Calcite), Volon Fm (fluvial: "
                "Floodplain, Channel, Calcite)."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Input"),
            "StringParameter": json.dumps({
                "Zones": ZONES,
                "Horizons": HORIZONS,
                "FaciesPerZone": REFERENCE_PROPERTIES,
            }, separators=(",", ":")),
        },
        # ── INPUT: Wells ─────────────────────────────────────────
        {
            "Title": "Wells",
            "Description": (
                "Drogon wells: 1 appraisal (55_33-1), 4 producers (A1-A4), "
                "2 water injectors (A5-A6), 5 RFT reference wells (R_A2..R_A6). "
                "Well modelling input from rms/input/well_modelling."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Input"),
            "StringParameter": json.dumps(WELLS, separators=(",", ":")),
        },
        # ── INPUT: Reservoir properties ──────────────────────────
        {
            "Title": "ReservoirProperties",
            "Description": (
                "Reference petrophysical properties per zone/facies from "
                "global_variables.yml. Porosity (0.10–0.31), permeability "
                "(1–1200 mD), Kv/Kh (0.1–0.9), J-functions for Pc, "
                "PVT (Bo=1.434, Rs=140.8), fluid contacts per 7 regions."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Input"),
            "StringParameter": json.dumps({
                "Properties": REFERENCE_PROPERTIES,
                "Regions": REGIONS,
            }, separators=(",", ":")),
        },
        # ── INPUT: Fault model ───────────────────────────────────
        {
            "Title": "FaultModel",
            "Description": (
                "7-region fault framework with LOGUNIF(0.1, 10) fault seal "
                "scaling. MULTREGT template for inter-region transmissibility."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Input"),
            "StringParameter": json.dumps({
                "Regions": list(REGIONS.keys()),
                "FaultSealScaling": {"Distribution": "LOGUNIF", "Min": 0.1, "Max": 10},
                "MultregtTemplate": "multregt.tmpl",
            }, separators=(",", ":")),
        },
        # ── INPUT: Observations ──────────────────────────────────
        {
            "Title": "Observations",
            "Description": (
                "History matching observations from "
                "drogon_wbhp_rft_wct_gor_tracer_4d_plt.obs: bottom-hole "
                "pressure, RFT, water cut, GOR, tracers (WT1/WT2), 4D seismic, "
                "PLT profiles."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Input"),
            "StringParameter": ERT_CONFIG["ObservationsFile"],
        },
        # ── WORKFLOW: ERT config ─────────────────────────────────
        {
            "Title": "ErtConfig",
            "Description": (
                "ERT orchestration config (drogon_design.ert): 250 realisations, "
                "one-by-one sensitivity, OPM Flow simulator, LSF queue, "
                "random seed 123456."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Workflow"),
            "StringParameter": json.dumps(ERT_CONFIG, separators=(",", ":")),
        },
        # ── WORKFLOW: Design matrix ──────────────────────────────
        {
            "Title": "DesignMatrix",
            "Description": (
                "Design matrix (design_matrix_one_by_one.xlsx, DesignSheet01 + "
                "DefaultValues): 250 realisations, one-by-one sensitivity layout. "
                "Each parameter varied individually while others at base values."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Workflow"),
            "StringParameter": json.dumps(DESIGN_MATRIX_CONFIG, separators=(",", ":")),
        },
        # ── WORKFLOW: Uncertainty parameters ─────────────────────
        {
            "Title": "UncertaintyParameters",
            "Description": (
                "17 uncertainty parameter distributions from "
                "global_variables.dist: Kv/Kh ratios (4), fluid contacts (3), "
                "fault seal (1), relperm interpolation (2), isocore trends (3), "
                "APS facies probabilities (4). All continuous uniform/loguniform."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Workflow"),
            "StringParameter": json.dumps(UNCERTAINTY_PARAMETERS, separators=(",", ":")),
        },
        # ── WORKFLOW: Model switches ─────────────────────────────
        {
            "Title": "ModelSwitches",
            "Description": (
                "Discrete model alternative switches: depth conversion (V=a*Tmap+b), "
                "simulation mode, standard MVA petro, APS facies, seismic "
                "conditioning, belts-based Therys."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Workflow"),
            "StringParameter": json.dumps(MODEL_SWITCHES, separators=(",", ":")),
        },
        # ── WORKFLOW: FMU config ─────────────────────────────────
        {
            "Title": "FmuConfig",
            "Description": (
                "fmuconfig global_variables.yml: complete model parameterisation. "
                "Includes dates, seismic paths, grid names, regions (7 with OWC/GOC), "
                "facies codes (8 types), petro properties, J-functions, relperm, "
                "masterdata (SMDA refs), stratigraphy definitions."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Workflow"),
            "StringParameter": json.dumps(FMUCONFIG, separators=(",", ":")),
        },
        # ── WORKFLOW: Forward model chain ────────────────────────
        {
            "Title": "ForwardModelChain",
            "Description": (
                "Ordered ERT forward model chain (22 steps): DESIGN2PARAMS → "
                "DESIGN_KW × 4 templates → COPY_DIRECTORY/COPY_FILE → RMS(MAIN) → "
                "ECLCOMPRESS → OPM_FLOW → PRTVOL2CSV → RES2CSV (summary, satfunc, "
                "pvt, vfp, gruptree, wellcompletiondata) → GRID3D_HC_THICKNESS → "
                "GRID3D_AVERAGE_MAP → EXPORT_ECL_ROFF → GEN_DATA_RFT/TRACER → "
                "SIM2SEIS → ERT_SUMMARY_PLOTTING."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Workflow"),
            "StringParameter": json.dumps(FORWARD_MODEL_CHAIN, separators=(",", ":")),
        },
        # ── WORKFLOW: Number of realisations ─────────────────────
        {
            "Title": "NumberOfRealizations",
            "Description": "Number of realisations in the design (250)",
            "ParameterKindID": _kind("Integer"),
            "ParameterRoleID": _role("Workflow"),
            "IntegerParameter": ERT_CONFIG["NumRealizations"],
        },
        # ── WORKFLOW: RMS project ────────────────────────────────
        {
            "Title": "RmsProject",
            "Description": (
                "RMS project: drogon.rms14.2.1, workflow MAIN. Covers structural "
                "modelling, facies modelling (APS with seismic conditioning), "
                "petrophysical modelling (MVA), grid construction, upscaling."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Workflow"),
            "StringParameter": json.dumps({
                "Project": ERT_CONFIG["RMSProject"],
                "Version": ERT_CONFIG["RMSVersion"],
                "Workflow": ERT_CONFIG["RMSWorkflow"],
            }, separators=(",", ":")),
        },
        # ── WORKFLOW: Eclipse DATA template ──────────────────────
        {
            "Title": "EclipseDataTemplate",
            "Description": (
                "Eclipse/OPM Flow DATA template (DROGON_HIST.DATA): METRIC, "
                "OIL/GAS/WATER/DISGAS/VAPOIL, 2 water tracers. Includes for "
                "grid, properties, schedule, PVT, RXVD, VFP."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Workflow"),
            "StringParameter": ERT_CONFIG["EclipseDataTemplate"],
        },
        # ── WORKFLOW: Hook workflows ─────────────────────────────
        {
            "Title": "HookWorkflows",
            "Description": (
                "5 ERT hook workflows: echo_config_file (PRE_SIMULATION), "
                "run_fmuconfig (PRE_SIMULATION), run_fmuconfig_rate "
                "(PRE_SIMULATION), wf_fmuobs (PRE_SIMULATION), "
                "xhook_create_case_metadata (PRE_SIMULATION)."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Workflow"),
            "StringParameter": json.dumps(HOOK_WORKFLOWS, separators=(",", ":")),
        },
        # ── WORKFLOW: Summary vectors ────────────────────────────
        {
            "Title": "SummaryVectors",
            "Description": (
                "Eclipse summary vectors requested: field rates (FOPR, FGPR, "
                "FWPR), cumulatives (FOPT, FGPT), well-level (WOPR, WBHP), "
                "region (RPR, ROIP, ROE), tracers (WTPRWT1/2), performance "
                "(TCPU). ~60 unique vector types across field/group/well/region."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Workflow"),
            "StringParameter": json.dumps(SUMMARY_VECTORS, separators=(",", ":")),
        },
        # ── INPUT: Existing OSDU parameter table ─────────────────
        {
            "Title": "InputParameterTable",
            "Description": (
                "OSDU ColumnBasedTable WPC containing per-realisation uncertainty "
                "parameter values (OWC depths, porosity, Kv/Kh, etc.)."
            ),
            "ParameterKindID": _kind("DataObject"),
            "ParameterRoleID": _role("Input"),
            "DataObjectParameter": params_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ColumnBasedTable-params"}],
        },
        # ── INPUT: Geomodel dataspace ────────────────────────────
        {
            "Title": "GeoModelDataspace",
            "Description": (
                "RDDMS ETP dataspace with Drogon geomodel EPC files. "
                "Shared structural model - same dataspace as DG1."
            ),
            "ParameterKindID": _kind("DataObject"),
            "ParameterRoleID": _role("Input"),
            "DataObjectParameter": dataspace_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ETPDataspace"}],
        } if dataspace_id else None,

        # ── OUTPUT: Parameter table ──────────────────────────────
        {
            "Title": "OutputParameterTable",
            "Description": (
                "Generated per-realisation input parameter table "
                "(ColumnBasedTable WPC) from DESIGN2PARAMS + DESIGN_KW."
            ),
            "ParameterKindID": _kind("DataObject"),
            "ParameterRoleID": _role("Output"),
            "DataObjectParameter": params_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ColumnBasedTable-params"}],
        },
        # ── OUTPUT: Raw volumes ──────────────────────────────────
        {
            "Title": "OutputVolumesRaw",
            "Description": (
                "Per-realisation estimated volumes (RAW REV WPC): STOIIP and "
                "GIIP by region (7), zone (3), and facies (8). From PRTVOL2CSV."
            ),
            "ParameterKindID": _kind("DataObject"),
            "ParameterRoleID": _role("Output"),
            "DataObjectParameter": raw_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "REV-raw"}],
        },
        # ── OUTPUT: Statistical volumes ──────────────────────────
        {
            "Title": "OutputVolumesStats",
            "Description": (
                "Statistical aggregation of volumes (STAT REV WPC): P10/P50/P90 "
                "across 250 realisations. Field STOIIP P50 ≈ 45.4 MSm³, "
                "recovery factor P50 ≈ 33.5%."
            ),
            "ParameterKindID": _kind("DataObject"),
            "ParameterRoleID": _role("Output"),
            "DataObjectParameter": stat_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "REV-stats"}],
        },
        # ── OUTPUT: Production forecast ──────────────────────────
        {
            "Title": "OutputProductionForecast",
            "Description": (
                "P50 production forecast (ColumnBasedTable WPC): field rates "
                "(FOPR, FGPR, FWPR), cumulatives (FOPT), injection (FWIR), "
                "pressure (FPR), water cut (FWCT). 4 producers, 2 injectors, "
                "20-year profile 2018–2037."
            ),
            "ParameterKindID": _kind("DataObject"),
            "ParameterRoleID": _role("Output"),
            "DataObjectParameter": production_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ProductionForecast"}],
        } if production_wpc_id else None,
        # ── OUTPUT: Maps ─────────────────────────────────────────
        {
            "Title": "OutputMaps",
            "Description": (
                "HC thickness maps (oil and gas, from GRID3D_HC_THICKNESS), "
                "good facies thickness maps, average parameter maps "
                "(from GRID3D_AVERAGE_MAP). Regular surface grids in .gri format."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Output"),
            "StringParameter": json.dumps(OUTPUT_ARTIFACTS["maps"], separators=(",", ":")),
        },
        # ── OUTPUT: Grid properties ──────────────────────────────
        {
            "Title": "OutputGridProperties",
            "Description": (
                "Eclipse restart and init parameters exported to ROFF format "
                "for RMS co-visualization and Webviz. Includes PORO, PERMX, "
                "SWAT, PRESSURE, SGAS per timestep."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Output"),
            "StringParameter": json.dumps(OUTPUT_ARTIFACTS["grid_properties"], separators=(",", ":")),
        },
        # ── OUTPUT: Sim2Seis ─────────────────────────────────────
        {
            "Title": "OutputSim2Seis",
            "Description": (
                "Synthetic seismic from simulation results (SIM2SEIS forward "
                "model): 3D and 4D synthetics for comparison with observed "
                "seismic. Rock physics: Vp/Vs/density for carbonate and coal."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Output"),
            "StringParameter": json.dumps(OUTPUT_ARTIFACTS["sim2seis"], separators=(",", ":")),
        },
        # ── OUTPUT: Well data ────────────────────────────────────
        {
            "Title": "OutputWellData",
            "Description": (
                "RFT pressure data (GEN_DATA_RFT_WELLS), tracer breakthrough "
                "(GEN_DATA_TRACER for WT1/WT2), well completion data "
                "(RES2CSV:wellcompletiondata → Arrow)."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Output"),
            "StringParameter": json.dumps(OUTPUT_ARTIFACTS["production_tables"], separators=(",", ":")),
        },
        # ── OUTPUT: Eclipse tables ───────────────────────────────
        {
            "Title": "OutputEclipseTables",
            "Description": (
                "Eclipse-derived tables: saturation functions (relperm.csv), "
                "PVT tables (pvt.csv), VFP tables (vfp*.arrow), group tree "
                "(gruptree.csv), summary vectors (DROGON-<IENS>.arrow)."
            ),
            "ParameterKindID": _kind("String"),
            "ParameterRoleID": _role("Output"),
            "StringParameter": json.dumps({
                "artifacts": OUTPUT_ARTIFACTS["production_tables"],
                "volumes": OUTPUT_ARTIFACTS["volumes"],
            }, separators=(",", ":")),
        },
        # ── CONTEXT: Volume estimates ────────────────────────────
        {
            "Title": "VolumeEstimates",
            "Description": (
                "P50 volume estimates: STOIIP 45.4 MSm³, GIIP 6.4 GSm³, "
                "recoverable oil 15.2 MSm³, RF 33.5%. Breakdown by 7 regions "
                "and 3 zones."
            ),
            "ParameterKindID": _kind("DataObject"),
            "ParameterRoleID": _role("Output"),
            "DataObjectParameter": stat_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "REV-stats-volumes"}],
        },
        # ── CONTEXT: Production profile P50 ──────────────────────
        {
            "Title": "ProductionProfileP50",
            "Description": (
                "P50 reference production profile: field-level FOPR, FGPR, "
                "FWPR, FWIR, FPR, FOPT, FWCT. Real OPM Flow output from "
                "realization-0, 31 monthly timesteps 2018–2020. "
                "Peak oil rate ~14.3 kSm³/d."
            ),
            "ParameterKindID": _kind("DataObject"),
            "ParameterRoleID": _role("Output"),
            "DataObjectParameter": production_wpc_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "ProductionProfile-P50"}],
        } if production_wpc_id else None,
        # ── INPUT: Reservoir master-data record ───────────────────
        {
            "Title": "ReservoirRecord",
            "Description": (
                "OSDU Reservoir master-data record for Drogon. Links to "
                "7 ReservoirSegment records (WestLowland, CentralSouth, etc.)."
            ),
            "ParameterKindID": _kind("DataObject"),
            "ParameterRoleID": _role("Input"),
            "DataObjectParameter": reservoir_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "Reservoir"}],
        },
        # ── OUTPUT: Development Concept ──────────────────────────
        {
            "Title": "DevelopmentConcept",
            "Description": (
                "DG2 Development Concept record: subsea tieback to Ivar Aasen, "
                "6 wells (A1-A4 prod + A5-A6 inj), FPSO host, waterflood IOR."
            ),
            "ParameterKindID": _kind("DataObject"),
            "ParameterRoleID": _role("Output"),
            "DataObjectParameter": devconcept_id,
            "Keys": [{"ParameterKey": "artifact", "StringParameterKey": "DevelopmentConcept"}],
        } if devconcept_id else None,
    ]

    # Remove None entries (conditional parameters)
    parameters = [p for p in parameters if p is not None]

    # Collect all output OSDU object IDs for ancestry
    children = [params_wpc_id, raw_wpc_id, stat_wpc_id]
    if production_wpc_id:
        children.append(production_wpc_id)
    if devconcept_id:
        children.append(devconcept_id)

    return {
        "id": activity_id,
        "kind": "osdu:wks:work-product-component--Activity:1.0.0",
        "acl": acl,
        "legal": legal,
        "data": {
            "Name": (
                "Drogon - Full FMU Workflow Run "
                "(ERT design, 250 realisations, OPM Flow)"
            ),
            "Description": (
                "Comprehensive FMU activity for the Drogon reservoir model, "
                "capturing the complete input-to-output pipeline for decision "
                "gate assessment. Based on the official equinor/fmu-drogon "
                "tutorial (24.3.1). "
                "INPUTS: 3D/4D seismic, 4 horizons (Volantis Group), "
                "stratigraphic column (3 formations, 8 facies types), "
                "6 active wells + 5 RFT wells, reservoir properties per "
                "zone/facies, 7-region fault model, history observations. "
                "WORKFLOW: ERT orchestration with 250 one-by-one sensitivity "
                "realisations. Forward model: DESIGN2PARAMS → DESIGN_KW → "
                "RMS (MAIN workflow: structural + facies + petro + grid) → "
                "ECLCOMPRESS → OPM Flow → post-processing (volumes, maps, "
                "sim2seis, RFT, tracers). "
                "17 continuous uncertainty parameters (Kv/Kh, FWL, GOC, "
                "fault seal, relperm, facies probabilities) + 6 discrete "
                "model switches. "
                "OUTPUTS: STOIIP/GIIP volumes by region/zone/facies "
                "(P10/P50/P90), production forecasts (FOPR, FGPR, FWPR, FPR), "
                "HC thickness maps, grid properties (ROFF), synthetic seismic, "
                "well data (RFT, tracers, completions), Eclipse tables."
            ),
            "Originator": "markuslund.vevle@emerson.com",
            "CreationDateTime": "2026-03-21T10:00:00.000Z",
            "ActivityTemplateID": template_id,
            "WorkflowStatus": "Completed",
            "ParentObjectID": reservoir_id,
            "ParentWorkProductID": workproduct_id,
            "Parameters": parameters,
            "ancestry": {
                "parents": [reservoir_id],
                "children": children,
            },
        },
    }


# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="Generate comprehensive Drogon FMU activity manifest"
    )
    ap.add_argument("--masterwp",   default=str(DG1_DIR / "manifest_masterwp_drogon.json"))
    ap.add_argument("--params",     default=str(SCRIPT_DIR / "manifest_wpcparams_dg2.json"))
    ap.add_argument("--rawvol",     default=str(SCRIPT_DIR / "manifest_wpcraw_dg2.json"))
    ap.add_argument("--statvol",    default=str(SCRIPT_DIR / "manifest_wpcstat_dg2.json"))
    ap.add_argument("--production", default=str(SCRIPT_DIR / "manifest_wpc_production_dg2.json"))
    ap.add_argument("--manifest",   default=str(SCRIPT_DIR / "manifest_activity_dg2.json"))
    ap.add_argument("--id-prefix",  default="dev")
    args = ap.parse_args()

    masterwp   = load_json(args.masterwp)
    params     = load_json(args.params)
    rawvol     = load_json(args.rawvol)
    statvol    = load_json(args.statvol)
    production = load_json(args.production)

    reservoir_id      = _find_id(masterwp,   "master-data--Reservoir:")
    workproduct_id    = _find_id(masterwp,   "work-product:")
    params_wpc_id     = _find_id(params,     "ColumnBasedTable")
    raw_wpc_id        = _find_id(rawvol,     "ReservoirEstimatedVolumes")
    stat_wpc_id       = _find_id(statvol,    "ReservoirEstimatedVolumes")
    production_wpc_id = _find_id(production, "ColumnBasedTable")

    # DG2 DevelopmentConcept
    devconcept_path = SCRIPT_DIR / "manifest_devconcept_dg2.json"
    devconcept_id = ""
    if devconcept_path.exists():
        devconcept_man = load_json(str(devconcept_path))
        devconcept_id = _find_id(devconcept_man, "DevelopmentConcept")
        if devconcept_id:
            print(f"  DevelopmentConcept: {devconcept_id}")

    # DG2 DevelopmentConcept
    devconcept_path = SCRIPT_DIR / "manifest_devconcept_dg2.json"
    devconcept_id = ""
    if devconcept_path.exists():
        devconcept_man = load_json(str(devconcept_path))
        devconcept_id = _find_id(devconcept_man, "DevelopmentConcept")
        if devconcept_id:
            print(f"  DevelopmentConcept: {devconcept_id}")

    for label, val in [
        ("reservoir_id",      reservoir_id),
        ("workproduct_id",    workproduct_id),
        ("params_wpc_id",     params_wpc_id),
        ("raw_wpc_id",        raw_wpc_id),
        ("stat_wpc_id",       stat_wpc_id),
    ]:
        if not val:
            raise SystemExit(f"ERROR: could not find {label}")

    if not production_wpc_id:
        print(f"WARNING: production WPC ID not found, skipping production output reference")

    # Get ACL/legal from reservoir record
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
        production_wpc_id=production_wpc_id,
        dataspace_id=dataspace_id,
        devconcept_id=devconcept_id,
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

    n_template_params = len(template["data"]["ParameterTemplates"])
    n_activity_params = len(activity["data"]["Parameters"])

    print(f"Written: {out}")
    print(f"  ETPDataspace       : {dataspace['id']}")
    print(f"  ActivityTemplate   : {template['id']}  ({n_template_params} parameter slots)")
    print(f"  Activity           : {activity['id']}  ({n_activity_params} parameters)")
    print(f"  ─── INPUTS ───")
    print(f"  Seismic            : 3D static + 3 × 4D monitor surveys")
    print(f"  Horizons           : {', '.join(HORIZONS)}")
    print(f"  Zones              : {', '.join(ZONES)}")
    print(f"  Wells              : {sum(len(v) for v in WELLS.values())} total")
    print(f"  Regions            : {len(REGIONS)} fault segments")
    print(f"  Uncertainties      : {len(UNCERTAINTY_PARAMETERS)} continuous + {len(MODEL_SWITCHES)} switches")
    print(f"  Forward models     : {len(FORWARD_MODEL_CHAIN)} steps")
    print(f"  Realisations       : {ERT_CONFIG['NumRealizations']}")
    print(f"  ─── OUTPUTS ───")
    print(f"  Params WPC         : {params_wpc_id}")
    print(f"  Raw volumes WPC    : {raw_wpc_id}")
    print(f"  Stats volumes WPC  : {stat_wpc_id}")
    print(f"  Production WPC     : {production_wpc_id or '(not found)'}")
    print(f"  + Maps, grid props, sim2seis, well data, Eclipse tables")
    print(f"  ─── VOLUMES (P50) ───")
    print(f"  STOIIP             : {VOLUME_ESTIMATES['STOIIP_MSm3']} MSm³")
    print(f"  GIIP               : {VOLUME_ESTIMATES['GIIP_GSm3']} GSm³")
    print(f"  EUR oil            : {VOLUME_ESTIMATES['RecoverableOil_MSm3']} MSm³")
    print(f"  Recovery factor    : {VOLUME_ESTIMATES['RecoveryFactor_pct']}%")


if __name__ == "__main__":
    main()
