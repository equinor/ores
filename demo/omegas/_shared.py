"""Shared helpers for Omega Sør demo scripts.

Mirrors the drogon/_shared.py pattern: re-exports auth helpers and defines
dataset-specific constants (segment/zone names, spatial extent, CRS, etc.).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# ── Re-export auth helpers from central module ──────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _auth import parse_dotenv, load_env, mint_from_env as get_access_token  # noqa: E402,F401


# ── JSON loader ─────────────────────────────────────────────────────────
def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Dataset constants ───────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent

# Zone names (reservoir formations in the Brent Group)
ZONE_NAMES: Dict[str, str] = {
    "Tarbert": "Tarbert Fm",
    "Rannoch": "Rannoch Fm",
}

# Segments (structural compartments from the RMS model)
SEGMENT_NAMES: Dict[str, str] = {
    "Tarbert_1": "Tarbert Zone 1",
    "Tarbert_2": "Tarbert Zone 2",
    "Rannoch_1": "Rannoch Zone 1",
    "Rannoch_2": "Rannoch Zone 2",
}

# ── Spatial / CRS ──────────────────────────────────────────────────────
# Omega Sør is on the Snorre field, block 34/4, North Sea
# ED50 / UTM zone 31N (EPSG:23031) is the project CRS in RMS
PROJECT_CRS_ID = "dev:reference-data--CoordinateReferenceSystem:ED50-UTM31N:"
PROJECT_EPSG = "EPSG:23031"

# WGS84 bounding box for spatial search (approximate from well 34/4-19 S)
# Lat/Lon: ~61.45°N, 2.15°E  (Snorre area, Tampen)
SPATIAL_AREA_WGS84 = {
    "Wgs84Coordinates": {
        "type": "Polygon",
        "coordinates": [[[2.05, 61.40], [2.25, 61.40], [2.25, 61.50],
                         [2.05, 61.50], [2.05, 61.40]]]
    }
}

# ── OSDU envelope defaults ──────────────────────────────────────────────
ID_PREFIX = "dev"

DEFAULT_ACL = {
    "owners": ["data.default.owners@dev.dataservices.energy"],
    "viewers": ["data.office.global.viewers@dev.dataservices.energy"],
}
DEFAULT_LEGAL = {
    "legaltags": ["dev-equinor-private-default"],
    "otherRelevantDataCountries": ["NO"],
}

# ── RDDMS / ETP ────────────────────────────────────────────────────────
DATASPACE = "maap/omegas"
EPC_FILE = SCRIPT_DIR / "os.epc"
H5_FILE = SCRIPT_DIR / "os.h5"

# ── Field / licence metadata ────────────────────────────────────────────
FIELD_NAME = "Snorre"
DISCOVERY_NAME = "Omega Sør Alfa"
LICENCE = "PL057"
BLOCK = "34/4"
WELL_EXPLORATION = "34/4-19 S"
OPERATOR = "Equinor Energy AS"
WATER_DEPTH_M = 381.0
