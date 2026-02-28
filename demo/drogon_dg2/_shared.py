"""Shared helpers for drogon_dg2 demo scripts.

Re-exports everything from the DG1 _shared module so DG2 scripts can
``from _shared import load_json, SEGMENT_NAMES`` without sys.path hacks.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the DG1 drogon folder importable so we can reuse its _shared module.
_DG1_DIR = Path(__file__).resolve().parent.parent / "drogon"
if str(_DG1_DIR) not in sys.path:
    sys.path.insert(0, str(_DG1_DIR))

# Re-export everything from the DG1 shared module
from _shared import (          # noqa: F401, E402
    load_json,
    SEGMENT_NAMES,
    parse_dotenv,
    first_env,
    load_env,
)

# ── DG2-specific paths ────────────────────────────────────────────────
DG1_DIR = _DG1_DIR
DG2_DIR = Path(__file__).resolve().parent
