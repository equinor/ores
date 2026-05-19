"""
weco.depenv — Depositional Environment Preset Library
======================================================

Maps canonical OSDU depositional environment names to WeCo correlation
presets (log selection, weights, gap costs, constraints).

The canonical names follow the OSDU ``StratigraphicUnitInterpretation``
``DepositionalEnvironment`` vocabulary, supplemented by RESQML
``DepositionMode`` enumerations.

Usage::

    from weco.depenv import DEPENV_PRESETS, detect_environment, suggest_options

    # From OSDU depositional env string
    preset = DEPENV_PRESETS.get("shallow_marine")
    options = preset["recommended_opts"]

    # Auto-detect from strat column
    env = detect_environment(strat_column)
    opts = suggest_options(env, data_names=["GR", "DEN", "DT"])
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Canonical OSDU Depositional Environment Names
# ═══════════════════════════════════════════════════════════════════════════

#: Maps OSDU DepositionalEnvironment strings to normalised keys.
#: Handles common variants / synonyms.
OSDU_DEPENV_ALIASES: Dict[str, str] = {
    # — Marine —
    "Shallow Marine": "shallow_marine",
    "shallow marine": "shallow_marine",
    "ShallowMarine": "shallow_marine",
    "Shoreface": "shallow_marine",
    "shoreface": "shallow_marine",
    "Shelf": "shallow_marine",
    "shelf": "shallow_marine",
    "Deep Marine": "deep_marine",
    "deep marine": "deep_marine",
    "DeepMarine": "deep_marine",
    "Turbidite": "deep_marine",
    "turbidite": "deep_marine",
    "Submarine Fan": "deep_marine",
    "submarine fan": "deep_marine",
    "Basin Floor": "deep_marine",
    "Slope": "deep_marine",
    "slope": "deep_marine",
    # — Deltaic —
    "Deltaic": "deltaic",
    "deltaic": "deltaic",
    "Delta": "deltaic",
    "delta": "deltaic",
    "Delta Front": "deltaic",
    "Delta Plain": "deltaic",
    "Prodelta": "deltaic",
    # — Fluvial —
    "Fluvial": "fluvial",
    "fluvial": "fluvial",
    "Alluvial": "fluvial",
    "alluvial": "fluvial",
    "Continental": "fluvial",
    "continental": "fluvial",
    "Channel": "fluvial",
    "Floodplain": "fluvial",
    # — Lacustrine —
    "Lacustrine": "lacustrine",
    "lacustrine": "lacustrine",
    "Lake": "lacustrine",
    # — Aeolian —
    "Aeolian": "aeolian",
    "aeolian": "aeolian",
    "Eolian": "aeolian",
    "Desert": "aeolian",
    # — Tidal —
    "Tidal": "tidal",
    "tidal": "tidal",
    "Tidal Flat": "tidal",
    "Estuarine": "tidal",
    "estuarine": "tidal",
    # — Carbonate —
    "Carbonate": "carbonate",
    "carbonate": "carbonate",
    "Carbonate Platform": "carbonate",
    "Reef": "reef",
    "reef": "reef",
    "Reefal": "reef",
    # — Coal —
    "Coal": "coal",
    "coal": "coal",
    "Peat": "coal",
    "Swamp": "coal",
    # — Glacial —
    "Glacial": "glacial",
    "glacial": "glacial",
    "Quaternary": "glacial",
    "Periglacial": "glacial",
    "Till": "glacial",
}


# ═══════════════════════════════════════════════════════════════════════════
# Depositional Environment Presets
# ═══════════════════════════════════════════════════════════════════════════

DEPENV_PRESETS: Dict[str, Dict[str, Any]] = {

    "shallow_marine": {
        "label": "Shallow Marine / Shoreface",
        "osdu_names": ["Shallow Marine", "Shoreface", "Shelf"],
        "description": "Wave-dominated shoreface / shelf system.",
        "log_priority": ["GR", "RHOB", "DEN", "DT", "NPHI", "RT"],
        "recommended_opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.50,
            "var_data2": "RHOB", "var_weight2": 0.30,
            "var_data3": "DT", "var_weight3": 0.20,
            "order": "position",
            "max_cor": 80, "nbr_cor": 80, "out_nbr_cor": 5,
            "const_gap_cost": 2.0,
        },
        "geo_preset_key": "shallow_marine_reservoir",
    },

    "deep_marine": {
        "label": "Deep-Marine Turbidite / Fan",
        "osdu_names": ["Deep Marine", "Turbidite", "Submarine Fan", "Slope"],
        "description": "Deep-water turbidite / fan system.",
        "log_priority": ["GR", "DEN", "RHOB", "DT", "SON", "RT"],
        "recommended_opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.60,
            "var_data2": "DEN", "var_weight2": 0.25,
            "var_data3": "DT", "var_weight3": 0.15,
            "order": "position",
            "max_cor": 100, "nbr_cor": 100, "out_nbr_cor": 5,
            "const_gap_cost": 1.0,
        },
        "geo_preset_key": "deep_marine_clastic",
    },

    "deltaic": {
        "label": "Deltaic (Delta Front / Prodelta)",
        "osdu_names": ["Deltaic", "Delta", "Delta Front", "Prodelta"],
        "description": (
            "River-dominated or wave-dominated delta system.\n"
            "Progradational coarsening-upward parasequences.\n\n"
            "Typical logs: GR, SP, DEN, DT\n"
            "Key features: clinoform geometry, rapid lateral facies change,\n"
            "mouth-bar sands, prodelta muds, distributary channels."
        ),
        "log_priority": ["GR", "SP", "DEN", "RHOB", "DT", "RT"],
        "recommended_opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.55,
            "var_data2": "DEN", "var_weight2": 0.25,
            "var_data3": "DT", "var_weight3": 0.20,
            "order": "position",
            "max_cor": 80, "nbr_cor": 80, "out_nbr_cor": 5,
            "const_gap_cost": 1.5,
        },
        "geo_preset_key": None,
    },

    "fluvial": {
        "label": "Fluvial / Continental / Alluvial",
        "osdu_names": ["Fluvial", "Alluvial", "Continental", "Channel"],
        "description": "Alluvial / fluvial / continental deposits.",
        "log_priority": ["GR", "SP", "RT", "DEN"],
        "recommended_opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.70,
            "var_data2": "RT", "var_weight2": 0.30,
            "order": "position",
            "max_cor": 80, "nbr_cor": 80, "out_nbr_cor": 5,
            "const_gap_cost": 1.5,
        },
        "geo_preset_key": "fluvial_continental",
    },

    "lacustrine": {
        "label": "Lacustrine (Lake)",
        "osdu_names": ["Lacustrine", "Lake"],
        "description": (
            "Lacustrine deposits — lake-floor, shore, and deltaic sub-envs.\n\n"
            "Typical logs: GR, DEN, SON, TOC\n"
            "Key features: laminated mudstones (source rocks), thin turbidites,\n"
            "highstand deltas, evaporite cycles in closed basins."
        ),
        "log_priority": ["GR", "DEN", "RHOB", "DT", "SON", "RT"],
        "recommended_opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.50,
            "var_data2": "DEN", "var_weight2": 0.30,
            "var_data3": "DT", "var_weight3": 0.20,
            "order": "position",
            "max_cor": 80, "nbr_cor": 80, "out_nbr_cor": 5,
            "const_gap_cost": 1.0,
        },
        "geo_preset_key": None,
    },

    "aeolian": {
        "label": "Aeolian (Desert / Dune)",
        "osdu_names": ["Aeolian", "Eolian", "Desert"],
        "description": (
            "Wind-deposited sandstones, typically well-sorted.\n\n"
            "Typical logs: GR, DEN, NPHI, DT\n"
            "Key features: very clean sands (low GR), high porosity,\n"
            "cross-stratification at seismic scale, interdune muds as markers."
        ),
        "log_priority": ["GR", "DEN", "RHOB", "NPHI", "DT"],
        "recommended_opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.40,
            "var_data2": "DEN", "var_weight2": 0.35,
            "var_data3": "NPHI", "var_weight3": 0.25,
            "order": "position",
            "max_cor": 80, "nbr_cor": 80, "out_nbr_cor": 5,
            "const_gap_cost": 2.0,
        },
        "geo_preset_key": None,
    },

    "tidal": {
        "label": "Tidal / Estuarine",
        "osdu_names": ["Tidal", "Tidal Flat", "Estuarine"],
        "description": (
            "Tidal flat, estuary, or tide-dominated delta deposits.\n\n"
            "Typical logs: GR, SP, DEN, RT\n"
            "Key features: heterolithic alternation (sand/mud), tidal bundles,\n"
            "mud drapes, IHS (inclined heterolithic stratification)."
        ),
        "log_priority": ["GR", "SP", "DEN", "RHOB", "RT", "DT"],
        "recommended_opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.55,
            "var_data2": "DEN", "var_weight2": 0.25,
            "var_data3": "RT", "var_weight3": 0.20,
            "order": "position",
            "max_cor": 80, "nbr_cor": 80, "out_nbr_cor": 5,
            "const_gap_cost": 1.5,
        },
        "geo_preset_key": None,
    },

    "carbonate": {
        "label": "Carbonate Platform",
        "osdu_names": ["Carbonate", "Carbonate Platform"],
        "description": "Carbonate platform / ramp system.",
        "log_priority": ["DEN", "RHOB", "DT", "SON", "GR", "NPHI"],
        "recommended_opts": {
            "cost_function": "composite",
            "var_data": "DEN", "var_weight": 0.35,
            "var_data2": "DT", "var_weight2": 0.35,
            "var_data3": "GR", "var_weight3": 0.15,
            "var_data4": "NPHI", "var_weight4": 0.15,
            "order": "position",
            "max_cor": 100, "nbr_cor": 100, "out_nbr_cor": 5,
            "const_gap_cost": 0.5,
        },
        "geo_preset_key": "carbonate_platform",
    },

    "reef": {
        "label": "Reef / Reefal",
        "osdu_names": ["Reef", "Reefal"],
        "description": (
            "Reef or reefal carbonate build-up.\n\n"
            "Typical logs: DEN, SON, NEU, GR\n"
            "Key features: massive framework, high porosity (vugs/molds),\n"
            "back-reef lagoonal muds, fore-reef talus, diagenetic overprint."
        ),
        "log_priority": ["DEN", "RHOB", "DT", "SON", "NPHI", "GR"],
        "recommended_opts": {
            "cost_function": "composite",
            "var_data": "DEN", "var_weight": 0.40,
            "var_data2": "DT", "var_weight2": 0.30,
            "var_data3": "NPHI", "var_weight3": 0.20,
            "var_data4": "GR", "var_weight4": 0.10,
            "order": "position",
            "max_cor": 100, "nbr_cor": 100, "out_nbr_cor": 5,
            "const_gap_cost": 0.5,
        },
        "geo_preset_key": "carbonate_platform",
    },

    "coal": {
        "label": "Coal Basin / Cyclothem",
        "osdu_names": ["Coal", "Peat", "Swamp"],
        "description": "Coal-bearing basin with cyclic sequences.",
        "log_priority": ["DEN", "RHOB", "GR", "RT", "DT", "SON", "NEU"],
        "recommended_opts": {
            "cost_function": "composite",
            "var_data": "DEN", "var_weight": 0.35,
            "var_data2": "GR", "var_weight2": 0.25,
            "var_data3": "RT", "var_weight3": 0.15,
            "var_data4": "DT", "var_weight4": 0.15,
            "var_data5": "NEU", "var_weight5": 0.10,
            "order": "position",
            "max_cor": 100, "nbr_cor": 100, "out_nbr_cor": 5,
            "const_gap_cost": 3.0,
        },
        "geo_preset_key": "coal_basin",
    },

    "glacial": {
        "label": "Glacial / Quaternary Hydrogeology",
        "osdu_names": ["Glacial", "Quaternary", "Till", "Periglacial"],
        "description": "Glacial lowland, Quaternary hydrogeology.",
        "log_priority": ["GR", "RT", "SPT", "MS", "DEN"],
        "recommended_opts": {
            "cost_function": "composite",
            "var_data": "GR", "var_weight": 0.50,
            "var_data2": "RT", "var_weight2": 0.30,
            "var_data3": "SPT", "var_weight3": 0.20,
            "order": "position",
            "max_cor": 80, "nbr_cor": 80, "out_nbr_cor": 5,
            "const_gap_cost": 2.0,
        },
        "geo_preset_key": "quaternary_hydrogeology",
    },
}


# ═══════════════════════════════════════════════════════════════════════════
# Detection and suggestion functions
# ═══════════════════════════════════════════════════════════════════════════

def normalise_depenv(name: str) -> Optional[str]:
    """Normalise an OSDU depositional environment name to a preset key.

    Returns None if no match found.
    """
    if not name:
        return None
    return OSDU_DEPENV_ALIASES.get(name) or OSDU_DEPENV_ALIASES.get(name.strip())


def detect_environment(strat_column) -> Optional[str]:
    """Auto-detect the dominant depositional environment from a StratColumn.

    Scans all units for ``depositional_environment`` fields and returns
    the most frequent normalised key.
    """
    from collections import Counter

    counts: Counter = Counter()
    for rank in strat_column.ranks:
        for unit in rank.units:
            key = normalise_depenv(unit.depositional_environment or "")
            if key:
                counts[key] += 1

    if not counts:
        return None
    return counts.most_common(1)[0][0]


def suggest_options(
    env_key: str,
    data_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Suggest WeCo engine options for a depositional environment.

    Parameters
    ----------
    env_key : str
        Normalised depenv key (e.g. "shallow_marine").
    data_names : list of str, optional
        Available log names — used to substitute missing logs.

    Returns
    -------
    dict
        Engine options dict ready for ``ProjectExt.set_options_ext()``.
    """
    preset = DEPENV_PRESETS.get(env_key)
    if not preset:
        logger.warning(f"Unknown environment key: {env_key}")
        return {}

    opts = dict(preset["recommended_opts"])

    # Substitute missing logs with available ones
    if data_names:
        available = set(data_names)
        prio = preset.get("log_priority", [])
        ranked = [n for n in prio if n in available]

        for slot, key in enumerate(["var_data", "var_data2", "var_data3",
                                     "var_data4", "var_data5"], start=0):
            if key in opts and opts[key] not in available:
                if slot < len(ranked):
                    opts[key] = ranked[slot]
                else:
                    # Remove unavailable slots
                    del opts[key]
                    wkey = key.replace("data", "weight")
                    opts.pop(wkey, None)

    return opts
