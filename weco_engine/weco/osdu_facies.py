"""
weco.osdu_facies - OSDU-Standard Depositional and Lithofacies Schemes
======================================================================

Defines facies classification schemes following OSDU reference vocabularies:
    - DepositionalEnvironment (OSDU Master Data)
    - LithologyType (OSDU ReferenceData)
    - DepositionalFacies (Energistics RESQML)

Each scheme maps integer zone IDs (as used in WeCo engine) to:
    - OSDU-canonical depositional facies names
    - Lithology types (OSDU LithologyType vocabulary)
    - Standard colours (USGS/ICS convention)
    - Grain size and energy indicators

Usage::

    from weco.osdu_facies import (
        FACIES_SCHEMES, get_facies_scheme, build_facies_dict
    )

    scheme = get_facies_scheme("shallow_marine")
    fd = build_facies_dict(scheme)

References:
    - OSDU Data Definitions: ``reference-data--LithologyType``
    - OSDU Data Definitions: ``reference-data--DepositionalEnvironment``
    - RESQML v2.0.1: ``DepositionalFacies``, ``DepositionMode``
    - Walker & James (1992) Facies Models
    - Reading (1996) Sedimentary Environments
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from weco.facies_dict import FaciesDictionary, STANDARD_LITHO_PALETTE


# ═══════════════════════════════════════════════════════════════════════════
# OSDU Facies Entry
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class OsduFaciesEntry:
    """One facies class in an OSDU-standard scheme."""

    zone_id: int
    name: str                           # OSDU DepositionalFacies name
    depositional_environment: str       # OSDU DepositionalEnvironment
    lithology_type: str                 # OSDU LithologyType
    color_html: str                     # hex colour
    grain_size: str = ""                # coarse/medium/fine/very fine/clay
    energy: str = ""                    # high/moderate/low
    description: str = ""


@dataclass
class OsduFaciesScheme:
    """Complete facies classification scheme for a depositional setting."""

    name: str
    depositional_system: str            # OSDU DepositionalEnvironment (system)
    description: str = ""
    entries: List[OsduFaciesEntry] = field(default_factory=list)

    def to_facies_dict(self, region_name: str = "FACIES") -> FaciesDictionary:
        """Convert to a WeCo FaciesDictionary for plotting."""
        fd = FaciesDictionary(region_name=region_name)
        for e in self.entries:
            fd.add(
                zone_id=e.zone_id,
                name=e.name,
                color=e.color_html,
                lithology=e.lithology_type.lower(),
                description=e.description,
            )
        return fd


# ═══════════════════════════════════════════════════════════════════════════
# OSDU Standard Facies Schemes
# ═══════════════════════════════════════════════════════════════════════════

# ── Shallow Marine (Hugin Fm, Sigrun/Gudrun/Troll) ────────────────────────
# Based on OSDU DepositionalEnvironment vocabulary + North Sea convention
# Ref: Knaust & Hoth (2021), Dreyer et al. (2005)

SHALLOW_MARINE_SCHEME = OsduFaciesScheme(
    name="Shallow Marine Clastic (North Sea)",
    depositional_system="Shallow Marine",
    description=(
        "Tide-to-wave influenced shallow marine system. "
        "Hugin Formation analogue (Middle–Upper Jurassic, Viking Graben)."
    ),
    entries=[
        OsduFaciesEntry(
            zone_id=1,
            name="Tidal Channel",
            depositional_environment="Tidal Channel",
            lithology_type="Sandstone",
            color_html="#F5D76E",
            grain_size="medium to coarse",
            energy="high",
            description="Cross-bedded sand, mud drapes, herringbone XB",
        ),
        OsduFaciesEntry(
            zone_id=2,
            name="Upper Shoreface",
            depositional_environment="Upper Shoreface",
            lithology_type="Sandstone",
            color_html="#E6C35C",
            grain_size="fine to medium",
            energy="high",
            description="Well-sorted sand, swaley/hummocky XS, Skolithos",
        ),
        OsduFaciesEntry(
            zone_id=3,
            name="Lower Shoreface",
            depositional_environment="Lower Shoreface",
            lithology_type="Sandstone",
            color_html="#C8B560",
            grain_size="very fine to fine",
            energy="moderate",
            description="Bioturbated fine sand, wave-rippled, Cruziana",
        ),
        OsduFaciesEntry(
            zone_id=4,
            name="Offshore Transition",
            depositional_environment="Offshore Transition",
            lithology_type="Siltstone",
            color_html="#A89850",
            grain_size="silt to very fine sand",
            energy="low to moderate",
            description="Interbedded silt/clay, HCS storm beds, intensely bioturbated",
        ),
        OsduFaciesEntry(
            zone_id=5,
            name="Offshore",
            depositional_environment="Offshore",
            lithology_type="Mudstone",
            color_html="#808080",
            grain_size="clay to silt",
            energy="low",
            description="Massive mudstone, Zoophycos/Chondrites, anaerobic intervals",
        ),
        OsduFaciesEntry(
            zone_id=6,
            name="Lagoon",
            depositional_environment="Lagoon",
            lithology_type="Mudstone",
            color_html="#6B8E23",
            grain_size="clay",
            energy="low",
            description="Dark organic-rich mud, rootlets, restricted fauna",
        ),
        OsduFaciesEntry(
            zone_id=7,
            name="Fluvial Channel",
            depositional_environment="Fluvial Channel",
            lithology_type="Sandstone",
            color_html="#DAA520",
            grain_size="coarse to very coarse",
            energy="high",
            description="Multi-storey channel sand, lag deposits, fining-up",
        ),
        OsduFaciesEntry(
            zone_id=8,
            name="Shelf Heterolithic",
            depositional_environment="Shelf",
            lithology_type="Heterolithic",
            color_html="#B8860B",
            grain_size="mixed fine sand/mud",
            energy="low to moderate",
            description="Thin-bedded heterolithic, flaser/wavy/lenticular bedding",
        ),
    ],
)


# ── Coastal Plain / Fluvial (Bryson) ──────────────────────────────────────
# Based on OSDU DepositionalEnvironment: Continental / Fluvial

COASTAL_PLAIN_SCHEME = OsduFaciesScheme(
    name="Coastal Plain / Fluvial (Appalachian)",
    depositional_system="Fluvial",
    description=(
        "Appalachian Basin coastal plain to fluvial system. "
        "Cretaceous clastics with facies from channel to overbank."
    ),
    entries=[
        OsduFaciesEntry(
            zone_id=1,
            name="Channel Sandstone",
            depositional_environment="Fluvial Channel",
            lithology_type="Sandstone",
            color_html="#F5D76E",
            grain_size="medium to coarse",
            energy="high",
            description="Erosional base, trough XB, fining-up",
        ),
        OsduFaciesEntry(
            zone_id=2,
            name="Point Bar",
            depositional_environment="Point Bar",
            lithology_type="Sandstone",
            color_html="#E6C35C",
            grain_size="fine to medium",
            energy="moderate to high",
            description="Lateral accretion, fining-up, epsilon XB",
        ),
        OsduFaciesEntry(
            zone_id=3,
            name="Crevasse Splay",
            depositional_environment="Crevasse Splay",
            lithology_type="Siltstone",
            color_html="#C8B560",
            grain_size="fine sand to silt",
            energy="moderate",
            description="Thin tabular beds, rippled, unconfined",
        ),
        OsduFaciesEntry(
            zone_id=4,
            name="Floodplain",
            depositional_environment="Floodplain",
            lithology_type="Mudstone",
            color_html="#808080",
            grain_size="clay to silt",
            energy="low",
            description="Massive mudstone, pedogenic features, rootlets",
        ),
        OsduFaciesEntry(
            zone_id=5,
            name="Coastal Plain Paleosol",
            depositional_environment="Coastal Plain",
            lithology_type="Claystone",
            color_html="#6B6B6B",
            grain_size="clay",
            energy="low",
            description="Paleosol, mottled, carbonate nodules",
        ),
        OsduFaciesEntry(
            zone_id=6,
            name="Lacustrine Mud",
            depositional_environment="Lacustrine",
            lithology_type="Mudstone",
            color_html="#4A6741",
            grain_size="clay",
            energy="low",
            description="Dark organic-rich lacustrine mud, laminated",
        ),
    ],
)


# ── Quaternary Glacial / Hydrogeological ──────────────────────────────────
# Based on OSDU DepositionalEnvironment: Glacial

QUATERNARY_GLACIAL_SCHEME = OsduFaciesScheme(
    name="Quaternary Glacial (Scandinavian)",
    depositional_system="Glacial",
    description=(
        "Pleistocene–Holocene glacial/interglacial succession. "
        "Aquifer (sand/gravel) and aquitard (till/clay) units."
    ),
    entries=[
        OsduFaciesEntry(
            zone_id=1,
            name="Glaciofluvial Sand",
            depositional_environment="Glaciofluvial",
            lithology_type="Sand",
            color_html="#F5D76E",
            grain_size="fine to coarse sand",
            energy="high",
            description="Outwash sand/gravel, stratified, aquifer unit",
        ),
        OsduFaciesEntry(
            zone_id=2,
            name="Till",
            depositional_environment="Glacial Till",
            lithology_type="Diamicton",
            color_html="#8B7D6B",
            grain_size="diamicton (mixed)",
            energy="high (glacial)",
            description="Unsorted glacial diamicton, compact, aquitard",
        ),
        OsduFaciesEntry(
            zone_id=3,
            name="Glaciolacustrine Clay",
            depositional_environment="Glaciolacustrine",
            lithology_type="Clay",
            color_html="#6B6B6B",
            grain_size="clay to silt",
            energy="low",
            description="Varved/massive clay, glacial lake deposit, aquitard",
        ),
        OsduFaciesEntry(
            zone_id=4,
            name="Interglacial Organic",
            depositional_environment="Lacustrine",
            lithology_type="Peat",
            color_html="#3D2B1F",
            grain_size="organic",
            energy="low",
            description="Peat/gyttja, Eemian interglacial marker horizon",
        ),
        OsduFaciesEntry(
            zone_id=5,
            name="Marine Clay",
            depositional_environment="Marine",
            lithology_type="Clay",
            color_html="#4682B4",
            grain_size="clay",
            energy="low",
            description="Post-glacial marine clay, Holocene transgression",
        ),
    ],
)


# ── Coal Measures ─────────────────────────────────────────────────────────
# Based on OSDU DepositionalEnvironment: Coal / Swamp

COAL_MEASURES_SCHEME = OsduFaciesScheme(
    name="Coal Measures (Paralic)",
    depositional_system="Coal",
    description=(
        "Paralic coal-bearing succession with cyclic "
        "coal–seat earth–channel sand sequences."
    ),
    entries=[
        OsduFaciesEntry(
            zone_id=1,
            name="Coal Seam",
            depositional_environment="Peat Mire",
            lithology_type="Coal",
            color_html="#1C1C1C",
            grain_size="organic",
            energy="low",
            description="Bituminous coal, bright-banded, economic seam",
        ),
        OsduFaciesEntry(
            zone_id=2,
            name="Seat Earth",
            depositional_environment="Swamp",
            lithology_type="Claystone",
            color_html="#6B6B6B",
            grain_size="clay",
            energy="low",
            description="Paleosol/underclay beneath coal, rootlets (Stigmaria)",
        ),
        OsduFaciesEntry(
            zone_id=3,
            name="Channel Sandstone",
            depositional_environment="Fluvial Channel",
            lithology_type="Sandstone",
            color_html="#F5D76E",
            grain_size="medium to coarse",
            energy="high",
            description="Distributary channel fill, erosional base, XB",
        ),
        OsduFaciesEntry(
            zone_id=4,
            name="Overbank Siltstone",
            depositional_environment="Floodplain",
            lithology_type="Siltstone",
            color_html="#C8B560",
            grain_size="silt to fine sand",
            energy="low to moderate",
            description="Laminated overbank fines, rippled, plant debris",
        ),
        OsduFaciesEntry(
            zone_id=5,
            name="Marine Band",
            depositional_environment="Marine",
            lithology_type="Mudstone",
            color_html="#808080",
            grain_size="clay",
            energy="low",
            description="Dark marine shale, Lingula, goniatite marker",
        ),
    ],
)


# ── Deltaic ───────────────────────────────────────────────────────────────
# Based on OSDU DepositionalEnvironment: Delta

DELTAIC_SCHEME = OsduFaciesScheme(
    name="Deltaic (Prograding)",
    depositional_system="Deltaic",
    description=(
        "River-dominated prograding delta. "
        "Coarsening-upward parasequences from prodelta to mouth bar."
    ),
    entries=[
        OsduFaciesEntry(
            zone_id=1,
            name="Distributary Channel",
            depositional_environment="Distributary Channel",
            lithology_type="Sandstone",
            color_html="#DAA520",
            grain_size="medium to coarse",
            energy="high",
            description="Channel fill, erosional base, trough XB",
        ),
        OsduFaciesEntry(
            zone_id=2,
            name="Mouth Bar",
            depositional_environment="Mouth Bar",
            lithology_type="Sandstone",
            color_html="#F5D76E",
            grain_size="fine to medium",
            energy="moderate to high",
            description="Coarsening-up bar, planar XB, climbing ripples",
        ),
        OsduFaciesEntry(
            zone_id=3,
            name="Delta Front",
            depositional_environment="Delta Front",
            lithology_type="Siltstone",
            color_html="#C8B560",
            grain_size="silt to very fine sand",
            energy="moderate",
            description="Interbedded silt/sand, HCS, intense bioturbation",
        ),
        OsduFaciesEntry(
            zone_id=4,
            name="Prodelta",
            depositional_environment="Prodelta",
            lithology_type="Mudstone",
            color_html="#808080",
            grain_size="clay to silt",
            energy="low",
            description="Massive-laminated mud, distal turbidite stringers",
        ),
    ],
)


# ── Fluvial ───────────────────────────────────────────────────────────────
# Based on OSDU DepositionalEnvironment: Fluvial

FLUVIAL_SCHEME = OsduFaciesScheme(
    name="Fluvial Channel Belt",
    depositional_system="Fluvial",
    description=(
        "Meandering to braided fluvial system. "
        "Discontinuous channel sandbodies in mudstone matrix."
    ),
    entries=[
        OsduFaciesEntry(
            zone_id=1,
            name="Channel Fill",
            depositional_environment="Fluvial Channel",
            lithology_type="Sandstone",
            color_html="#F5D76E",
            grain_size="medium to coarse",
            energy="high",
            description="Multi-storey channel, lag, fining-up, trough XB",
        ),
        OsduFaciesEntry(
            zone_id=2,
            name="Overbank/Floodplain",
            depositional_environment="Floodplain",
            lithology_type="Mudstone",
            color_html="#808080",
            grain_size="clay to silt",
            energy="low",
            description="Massive-mottled mud, paleosol, rootlets",
        ),
        OsduFaciesEntry(
            zone_id=3,
            name="Crevasse/Levee",
            depositional_environment="Crevasse Splay",
            lithology_type="Siltstone",
            color_html="#C8B560",
            grain_size="silt to fine sand",
            energy="moderate",
            description="Thin rippled beds, plant fragments, unconfined",
        ),
    ],
)


# ── Carbonate Platform ────────────────────────────────────────────────────
# Based on OSDU DepositionalEnvironment: Carbonate

CARBONATE_PLATFORM_SCHEME = OsduFaciesScheme(
    name="Carbonate Platform",
    depositional_system="Carbonate",
    description=(
        "Shallow-water carbonate platform with reef, lagoon, and slope facies."
    ),
    entries=[
        OsduFaciesEntry(
            zone_id=1,
            name="Reef Framework",
            depositional_environment="Reef",
            lithology_type="Limestone",
            color_html="#6CACE4",
            grain_size="boundstone",
            energy="high",
            description="Coral/stromatoporoid framestone, massive",
        ),
        OsduFaciesEntry(
            zone_id=2,
            name="Lagoon",
            depositional_environment="Lagoon",
            lithology_type="Limestone",
            color_html="#B0E0E6",
            grain_size="mudstone to wackestone",
            energy="low",
            description="Restricted, micrite-rich, gastropods, algae",
        ),
        OsduFaciesEntry(
            zone_id=3,
            name="Shoal",
            depositional_environment="Carbonate Shoal",
            lithology_type="Limestone",
            color_html="#4A90D9",
            grain_size="grainstone",
            energy="high",
            description="Ooid/bioclast grainstone, cross-bedded",
        ),
        OsduFaciesEntry(
            zone_id=4,
            name="Slope",
            depositional_environment="Slope",
            lithology_type="Limestone",
            color_html="#A3C9A8",
            grain_size="packstone to wackestone",
            energy="moderate",
            description="Periplatform debris, turbidites, slumps",
        ),
        OsduFaciesEntry(
            zone_id=5,
            name="Basin",
            depositional_environment="Deep Marine",
            lithology_type="Marl",
            color_html="#808080",
            grain_size="mudstone to marl",
            energy="low",
            description="Pelagic-hemipelagic marl/chalk, condensed",
        ),
    ],
)


# ═══════════════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════════════

#: Maps geology key (used in DEMOS) → OSDU facies scheme.
FACIES_SCHEMES: Dict[str, OsduFaciesScheme] = {
    "shallow_marine": SHALLOW_MARINE_SCHEME,
    "coastal_plain": COASTAL_PLAIN_SCHEME,
    "quaternary": QUATERNARY_GLACIAL_SCHEME,
    "glacial": QUATERNARY_GLACIAL_SCHEME,
    "coal": COAL_MEASURES_SCHEME,
    "deltaic": DELTAIC_SCHEME,
    "fluvial": FLUVIAL_SCHEME,
    "carbonate": CARBONATE_PLATFORM_SCHEME,
    "reef": CARBONATE_PLATFORM_SCHEME,
    "tidal": SHALLOW_MARINE_SCHEME,
}


def get_facies_scheme(geology_key: str) -> Optional[OsduFaciesScheme]:
    """Get the OSDU facies scheme for a given geological setting.

    Args:
        geology_key: Key matching demo ``geology`` field or depenv preset.

    Returns:
        OsduFaciesScheme or None if no matching scheme.
    """
    return FACIES_SCHEMES.get(geology_key)


def build_facies_dict(
    scheme: OsduFaciesScheme,
    region_name: str = "FACIES",
) -> FaciesDictionary:
    """Convert an OSDU facies scheme to a WeCo FaciesDictionary.

    Convenience wrapper around ``scheme.to_facies_dict()``.
    """
    return scheme.to_facies_dict(region_name=region_name)


def get_facies_label(geology_key: str, zone_id: int) -> str:
    """Get the OSDU depositional facies name for a zone ID.

    >>> get_facies_label("shallow_marine", 1)
    'Tidal Channel'
    >>> get_facies_label("coal", 1)
    'Coal Seam'
    """
    scheme = FACIES_SCHEMES.get(geology_key)
    if scheme:
        for e in scheme.entries:
            if e.zone_id == zone_id:
                return e.name
    return str(zone_id)


def get_lithology_type(geology_key: str, zone_id: int) -> str:
    """Get the OSDU LithologyType for a facies zone.

    >>> get_lithology_type("shallow_marine", 1)
    'Sandstone'
    >>> get_lithology_type("quaternary", 2)
    'Diamicton'
    """
    scheme = FACIES_SCHEMES.get(geology_key)
    if scheme:
        for e in scheme.entries:
            if e.zone_id == zone_id:
                return e.lithology_type
    return ""
