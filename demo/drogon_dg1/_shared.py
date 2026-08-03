"""Shared helpers for drogon demo scripts.

Centralises load_json, SEGMENT_NAMES, and auth/env loading so they live in
one place rather than being copy-pasted across every generator / ingest script.

Auth functions (parse_dotenv, first_env, load_env, mint_from_env) are provided
by the central ``demo/_auth.py`` module and re-exported here for convenience.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

# ── Re-export auth helpers from central module ──────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _auth import parse_dotenv, load_env, mint_from_env as get_access_token  # noqa: E402,F401


# ── JSON loader ─────────────────────────────────────────────────────────
def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Segment display names (Valysar / Drogon) ───────────────────────────
SEGMENT_NAMES: Dict[str, str] = {
    "WestLowland":  "West Lowland",
    "CentralSouth": "Central South",
    "CentralNorth": "Central North",
    "NorthHorst":   "North Horst",
    "CentralRamp":  "Central Ramp",
    "CentralHorst": "Central Horst",
    "EastLowland":  "East Lowland",
}
