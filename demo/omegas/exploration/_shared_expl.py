"""Shared helpers for Omega Sør Exploration well decision scripts.

Extends the parent omegas/_shared.py with exploration-specific constants.
"""
from __future__ import annotations

import sys
from pathlib import Path

# ── Make parent omegas/ importable ──────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PARENT_DIR = SCRIPT_DIR.parent

sys.path.insert(0, str(PARENT_DIR))
sys.path.insert(0, str(PARENT_DIR.parent))

from _shared import (  # noqa: E402, F401
    DEFAULT_ACL, DEFAULT_LEGAL, ID_PREFIX,
    SPATIAL_AREA_WGS84, PROJECT_CRS_ID, DATASPACE,
    FIELD_NAME, DISCOVERY_NAME, LICENCE, BLOCK,
    WELL_EXPLORATION, OPERATOR, WATER_DEPTH_M,
    load_json,
)

# ── Exploration-specific constants ──────────────────────────────────────
WELL_NAME = "34/4-19 S"
WELL_ID_SUFFIX = "34-4-19S"

# SharePoint project site (requires Entra ID auth via Edge)
SHAREPOINT_SITE = "https://statoilsrm.sharepoint.com/sites/WCPNO344-19S"

# ── Cross-references to parent Omega Sør project ────────────────────────
# Same CollaborationProject as the WPC development decision
CP_ID = f"{ID_PREFIX}:master-data--CollaborationProject:OmegaSor-FieldDev:1"

# Same Reservoir master data
RESERVOIR_ID = f"{ID_PREFIX}:master-data--Reservoir:OmegaSorAlfa:1"
SEG_TARBERT_ID = f"{ID_PREFIX}:master-data--ReservoirSegment:OmegaSor-Tarbert:1"
SEG_RANNOCH_ID = f"{ID_PREFIX}:master-data--ReservoirSegment:OmegaSor-Rannoch:1"

# Existing well/wellbore from master manifest
WELL_EXPL_ID = f"{ID_PREFIX}:master-data--Well:{WELL_ID_SUFFIX}:1"
WELLBORE_EXPL_ID = f"{ID_PREFIX}:master-data--Wellbore:{WELL_ID_SUFFIX}:1"

# Exploration BD IDs
BD_EXPL_ID = f"{ID_PREFIX}:master-data--BusinessDecision:OmegaSor-Exploration:1"
COLLECTION_EXPL_ID = f"{ID_PREFIX}:work-product-component--PersistedCollection:OmegaSor-Exploration-Evidence:1"
DRILLING_COLLECTION_EXPL_ID = f"{ID_PREFIX}:work-product-component--PersistedCollection:OmegaSor-Exploration-Drilling:1"
GEOSCIENCE_COLLECTION_EXPL_ID = f"{ID_PREFIX}:work-product-component--PersistedCollection:OmegaSor-Exploration-Geoscience:1"

# ETP dataspace reference (same dataspace as development BD)
DATASPACE_ID = f"{ID_PREFIX}:dataset--ETPDataspace:maap-omegas:1"
