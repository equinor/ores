"""
weco.osdu_properties - OSDU Canonical Property Names and Units
===============================================================

Maps well-log mnemonics used internally by WeCo (GR, DEN, DT, etc.) to
OSDU Energy Data Platform canonical property names and units.

References:
    - OSDU Data Definitions: ``os-wellbore-ddms`` schema
    - Energistics RESQML: ``PropertyKind`` enumeration
    - SPWLA mnemonic standard / LAS 3.0

Usage::

    from weco.osdu_properties import (
        OSDU_LOG_PROPERTIES, get_osdu_name, get_unit, mnemonic_from_osdu
    )

    # Short mnemonic → full OSDU name + unit
    prop = OSDU_LOG_PROPERTIES["GR"]
    print(prop["osdu_name"])   # "Gamma Ray"
    print(prop["unit"])        # "gAPI"

    # Convenience
    print(get_osdu_name("DEN"))  # "Bulk Density"
    print(get_unit("GR"))        # "gAPI"
"""

from __future__ import annotations

from typing import Dict, Optional


# ═══════════════════════════════════════════════════════════════════════════
# OSDU Canonical Log Property Definitions
# ═══════════════════════════════════════════════════════════════════════════
# Keys: common mnemonics used in WeCo demo data and LAS files.
# Values: OSDU property metadata following os-wellbore-ddms schema.

OSDU_LOG_PROPERTIES: Dict[str, Dict[str, str]] = {
    # ── Continuous petrophysical logs ──────────────────────────────────
    "GR": {
        "osdu_name": "Gamma Ray",
        "osdu_kind": "GammaRay",
        "unit": "gAPI",
        "unit_osdu": "gAPI",
        "description": "Total natural gamma ray intensity",
        "property_kind": "continuous",
    },
    "DEN": {
        "osdu_name": "Bulk Density",
        "osdu_kind": "BulkDensity",
        "unit": "g/cm3",
        "unit_osdu": "g/cm3",
        "description": "Formation bulk density",
        "property_kind": "continuous",
    },
    "RHOB": {
        "osdu_name": "Bulk Density",
        "osdu_kind": "BulkDensity",
        "unit": "g/cm3",
        "unit_osdu": "g/cm3",
        "description": "Formation bulk density",
        "property_kind": "continuous",
    },
    "DT": {
        "osdu_name": "Compressional Slowness",
        "osdu_kind": "CompressionalSlowness",
        "unit": "us/ft",
        "unit_osdu": "us/ft",
        "description": "Compressional acoustic slowness (delta-t)",
        "property_kind": "continuous",
    },
    "SON": {
        "osdu_name": "Compressional Slowness",
        "osdu_kind": "CompressionalSlowness",
        "unit": "us/ft",
        "unit_osdu": "us/ft",
        "description": "Sonic slowness (alias for DT)",
        "property_kind": "continuous",
    },
    "NPHI": {
        "osdu_name": "Neutron Porosity",
        "osdu_kind": "NeutronPorosity",
        "unit": "v/v",
        "unit_osdu": "v/v",
        "description": "Neutron porosity (hydrogen index)",
        "property_kind": "continuous",
    },
    "NEU": {
        "osdu_name": "Neutron Porosity",
        "osdu_kind": "NeutronPorosity",
        "unit": "v/v",
        "unit_osdu": "v/v",
        "description": "Neutron porosity (alias for NPHI)",
        "property_kind": "continuous",
    },
    "RT": {
        "osdu_name": "Deep Resistivity",
        "osdu_kind": "DeepResistivity",
        "unit": "ohm.m",
        "unit_osdu": "ohm.m",
        "description": "Deep induction/laterolog resistivity",
        "property_kind": "continuous",
    },
    "CAL": {
        "osdu_name": "Caliper",
        "osdu_kind": "Caliper",
        "unit": "in",
        "unit_osdu": "in",
        "description": "Borehole caliper diameter",
        "property_kind": "continuous",
    },
    "SP": {
        "osdu_name": "Spontaneous Potential",
        "osdu_kind": "SpontaneousPotential",
        "unit": "mV",
        "unit_osdu": "mV",
        "description": "Spontaneous (self) potential",
        "property_kind": "continuous",
    },
    "PEF": {
        "osdu_name": "Photoelectric Factor",
        "osdu_kind": "PhotoelectricFactor",
        "unit": "b/e",
        "unit_osdu": "b/e",
        "description": "Photoelectric absorption factor",
        "property_kind": "continuous",
    },
    "COND": {
        "osdu_name": "Conductivity",
        "osdu_kind": "Conductivity",
        "unit": "mS/m",
        "unit_osdu": "mS/m",
        "description": "Electrical conductivity (1/resistivity)",
        "property_kind": "continuous",
    },
    # ── Geotechnical / Quaternary ──────────────────────────────────────
    "SPT": {
        "osdu_name": "Standard Penetration Test",
        "osdu_kind": "SPT_N_Value",
        "unit": "blows/30cm",
        "unit_osdu": "blows/30cm",
        "description": "SPT N-value (blow count)",
        "property_kind": "continuous",
    },
    "MS": {
        "osdu_name": "Magnetic Susceptibility",
        "osdu_kind": "MagneticSusceptibility",
        "unit": "SI",
        "unit_osdu": "SI",
        "description": "Magnetic susceptibility (volume)",
        "property_kind": "continuous",
    },
    "WC": {
        "osdu_name": "Water Content",
        "osdu_kind": "WaterContent",
        "unit": "%",
        "unit_osdu": "%",
        "description": "Gravimetric water content",
        "property_kind": "continuous",
    },
    # ── Depth references ───────────────────────────────────────────────
    "DEPTH": {
        "osdu_name": "Measured Depth",
        "osdu_kind": "MeasuredDepth",
        "unit": "m",
        "unit_osdu": "m",
        "description": "Measured depth along wellbore",
        "property_kind": "continuous",
    },
    "MD": {
        "osdu_name": "Measured Depth",
        "osdu_kind": "MeasuredDepth",
        "unit": "m",
        "unit_osdu": "m",
        "description": "Measured depth along wellbore",
        "property_kind": "continuous",
    },
    # ── Discrete / categorical properties ──────────────────────────────
    "FACIES": {
        "osdu_name": "Depositional Facies",
        "osdu_kind": "DepositionalFacies",
        "unit": "unitless",
        "unit_osdu": "Euc",
        "description": "Interpreted depositional facies classification",
        "property_kind": "discrete",
    },
    "DISTALITY": {
        "osdu_name": "Distality Index",
        "osdu_kind": "DistalityIndex",
        "unit": "unitless",
        "unit_osdu": "Euc",
        "description": "Proximal-distal position (1=distal, N=proximal)",
        "property_kind": "ordinal",
    },
    "BIOZONE": {
        "osdu_name": "Biostratigraphic Zone",
        "osdu_kind": "BiostratigraphicZone",
        "unit": "unitless",
        "unit_osdu": "Euc",
        "description": "Palynological / micropalaeontological biozone",
        "property_kind": "discrete",
    },
    "SEQUENCE": {
        "osdu_name": "Sequence Stratigraphy",
        "osdu_kind": "SequenceStratigraphy",
        "unit": "unitless",
        "unit_osdu": "Euc",
        "description": "Depositional sequence (systems tract level)",
        "property_kind": "discrete",
    },
    "SEQSTRAT": {
        "osdu_name": "Sequence Stratigraphy",
        "osdu_kind": "SequenceStratigraphy",
        "unit": "unitless",
        "unit_osdu": "Euc",
        "description": "Sequence stratigraphic interpretation",
        "property_kind": "discrete",
    },
    "ZONE": {
        "osdu_name": "Stratigraphic Zone",
        "osdu_kind": "StratigraphicZone",
        "unit": "unitless",
        "unit_osdu": "Euc",
        "description": "Lithostratigraphic or chronostratigraphic zone",
        "property_kind": "discrete",
    },
    "LITH": {
        "osdu_name": "Lithology",
        "osdu_kind": "Lithology",
        "unit": "unitless",
        "unit_osdu": "Euc",
        "description": "Rock type / lithology classification",
        "property_kind": "discrete",
    },
    "SEAM": {
        "osdu_name": "Coal Seam Indicator",
        "osdu_kind": "CoalSeam",
        "unit": "unitless",
        "unit_osdu": "Euc",
        "description": "Coal seam identification (0=non-seam, 1+=seam ID)",
        "property_kind": "discrete",
    },
    "HYDRO": {
        "osdu_name": "Hydrostratigraphic Unit",
        "osdu_kind": "HydrostratigraphicUnit",
        "unit": "unitless",
        "unit_osdu": "Euc",
        "description": "Hydrogeological unit (aquifer/aquitard classification)",
        "property_kind": "discrete",
    },
    "STRAT": {
        "osdu_name": "Stratigraphic Unit",
        "osdu_kind": "StratigraphicUnit",
        "unit": "unitless",
        "unit_osdu": "Euc",
        "description": "Formal lithostratigraphic unit",
        "property_kind": "discrete",
    },
}

# ═══════════════════════════════════════════════════════════════════════════
# Reverse mapping: OSDU kind → preferred mnemonic
# ═══════════════════════════════════════════════════════════════════════════

_OSDU_KIND_TO_MNEMONIC: Dict[str, str] = {
    v["osdu_kind"]: k for k, v in OSDU_LOG_PROPERTIES.items()
    if k == k.upper()  # prefer uppercase canonical form
}
# Ensure preferred mnemonics win over aliases
_OSDU_KIND_TO_MNEMONIC.update({
    "BulkDensity": "RHOB",
    "CompressionalSlowness": "DT",
    "NeutronPorosity": "NPHI",
    "MeasuredDepth": "DEPTH",
})

# ═══════════════════════════════════════════════════════════════════════════
# Mnemonic aliases (common LAS variants → canonical WeCo mnemonic)
# ═══════════════════════════════════════════════════════════════════════════

MNEMONIC_ALIASES: Dict[str, str] = {
    # Density aliases
    "RHOB": "RHOB", "DEN": "RHOB", "RHOZ": "RHOB", "ZDEN": "RHOB",
    "DENSITY": "RHOB",
    # Sonic aliases
    "DT": "DT", "SON": "DT", "DTCO": "DT", "DTC": "DT", "AC": "DT",
    "SONIC": "DT",
    # Neutron aliases
    "NPHI": "NPHI", "NEU": "NPHI", "TNPH": "NPHI", "NEUT": "NPHI",
    "CNPOR": "NPHI",
    # Gamma ray aliases
    "GR": "GR", "SGR": "GR", "CGR": "GR", "ECGR": "GR",
    # Resistivity aliases
    "RT": "RT", "ILD": "RT", "LLD": "RT", "RDEP": "RT", "RD": "RT",
    "AT90": "RT", "RLA5": "RT",
    # Caliper aliases
    "CAL": "CAL", "CALI": "CAL", "HCAL": "CAL",
    # SP aliases
    "SP": "SP",
    # PEF aliases
    "PEF": "PEF", "PE": "PEF",
    # Depth aliases
    "DEPTH": "DEPTH", "MD": "DEPTH", "DEPT": "DEPTH",
}


# ═══════════════════════════════════════════════════════════════════════════
# Convenience functions
# ═══════════════════════════════════════════════════════════════════════════

def get_osdu_name(mnemonic: str) -> str:
    """Return the OSDU canonical property name for a mnemonic.

    >>> get_osdu_name("GR")
    'Gamma Ray'
    >>> get_osdu_name("RHOB")
    'Bulk Density'
    """
    prop = OSDU_LOG_PROPERTIES.get(mnemonic.upper())
    if prop:
        return prop["osdu_name"]
    return mnemonic


def get_osdu_kind(mnemonic: str) -> str:
    """Return the OSDU PropertyKind string for a mnemonic.

    >>> get_osdu_kind("GR")
    'GammaRay'
    """
    prop = OSDU_LOG_PROPERTIES.get(mnemonic.upper())
    if prop:
        return prop["osdu_kind"]
    return mnemonic


def get_unit(mnemonic: str) -> str:
    """Return the standard unit of measurement for a mnemonic.

    >>> get_unit("GR")
    'gAPI'
    >>> get_unit("DEN")
    'g/cm3'
    """
    prop = OSDU_LOG_PROPERTIES.get(mnemonic.upper())
    if prop:
        return prop["unit"]
    return ""


def mnemonic_from_osdu(osdu_kind: str) -> Optional[str]:
    """Reverse-lookup: OSDU PropertyKind → preferred WeCo mnemonic.

    >>> mnemonic_from_osdu("GammaRay")
    'GR'
    >>> mnemonic_from_osdu("BulkDensity")
    'RHOB'
    """
    return _OSDU_KIND_TO_MNEMONIC.get(osdu_kind)


def resolve_mnemonic(alias: str) -> str:
    """Resolve a LAS mnemonic alias to the canonical WeCo name.

    >>> resolve_mnemonic("DTCO")
    'DT'
    >>> resolve_mnemonic("ILD")
    'RT'
    """
    return MNEMONIC_ALIASES.get(alias.upper(), alias.upper())


def is_discrete(mnemonic: str) -> bool:
    """Check if a property is discrete/categorical (vs continuous)."""
    prop = OSDU_LOG_PROPERTIES.get(mnemonic.upper())
    if prop:
        return prop["property_kind"] in ("discrete", "ordinal")
    return False
