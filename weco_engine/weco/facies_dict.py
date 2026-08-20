"""
weco.facies_dict - Facies Dictionary for Zone Colours and Labels
=================================================================

Maps integer zone IDs (from Well.region) to human-readable names, colours,
and lithology descriptions. Used by plot functions to render meaningful
facies tracks and legends.

Usage::

    from weco.facies_dict import FaciesDictionary, STANDARD_LITHO_PALETTE

    fd = FaciesDictionary.from_region_name("LITH")
    color = fd.get_color(zone_id=3)
    label = fd.get_label(zone_id=3)

    # Or build from OSDU records
    fd = FaciesDictionary.from_osdu_units(litho_records)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# ═══════════════════════════════════════════════════════════════════════════
# Standard Lithology Colour Palette (USGS-inspired)
# ═══════════════════════════════════════════════════════════════════════════

#: Maps common lithology names → (R, G, B) hex colour.
STANDARD_LITHO_PALETTE: Dict[str, str] = {
    "sandstone":    "#F5D76E",  # yellow
    "sand":         "#F5D76E",
    "siltstone":    "#C8B560",  # olive-yellow
    "silt":         "#C8B560",
    "shale":        "#808080",  # gray
    "claystone":    "#6B6B6B",  # dark gray
    "clay":         "#6B6B6B",
    "mudstone":     "#8B7D6B",  # brown-gray
    "limestone":    "#6CACE4",  # light blue
    "chalk":        "#B0E0E6",  # powder blue
    "dolomite":     "#4A90D9",  # medium blue
    "marl":         "#A3C9A8",  # sage green
    "coal":         "#1C1C1C",  # near-black
    "peat":         "#3D2B1F",  # dark brown
    "conglomerate": "#D4A574",  # tan
    "gravel":       "#C9A96E",  # light brown
    "anhydrite":    "#DDA0DD",  # plum
    "gypsum":       "#E6C3E6",  # light plum
    "halite":       "#FFB6C1",  # light pink
    "basalt":       "#2F4F4F",  # dark slate
    "granite":      "#FF6B6B",  # red
    "tuff":         "#98FB98",  # pale green
    "volcanic":     "#8B0000",  # dark red
}

#: Default zone colours for integer IDs (when no lithology name known).
#: 20 distinct colours for zones 0–19; wraps for higher IDs.
ZONE_COLORS: List[str] = [
    "#F5D76E",  # 0: sand/yellow
    "#808080",  # 1: shale/gray
    "#6CACE4",  # 2: limestone/blue
    "#4CAF50",  # 3: green
    "#FF9800",  # 4: orange
    "#9C27B0",  # 5: purple
    "#00BCD4",  # 6: cyan
    "#795548",  # 7: brown
    "#E91E63",  # 8: pink
    "#3F51B5",  # 9: indigo
    "#CDDC39",  # 10: lime
    "#FF5722",  # 11: deep orange
    "#607D8B",  # 12: blue-gray
    "#FFC107",  # 13: amber
    "#009688",  # 14: teal
    "#673AB7",  # 15: deep purple
    "#8BC34A",  # 16: light green
    "#F44336",  # 17: red
    "#2196F3",  # 18: blue
    "#FFEB3B",  # 19: yellow-bright
]

#: Common region name patterns → likely lithology mapping heuristic.
REGION_LITHO_HINTS: Dict[str, Dict[int, str]] = {
    "LITH": {},       # generic lithology - use zone_id → color directly
    "FACIES": {},     # depositional facies
    "SEAM": {0: "shale", 1: "coal"},  # coal basin: 0=non-seam, 1+=seam
    "HYDRO": {0: "shale", 1: "sandstone", 2: "limestone"},  # hydrostratigraphic
}

#: Standard lithology integer code tables used in well logs.
#: Multiple conventions exist; we try each and pick the best match.
_LITHO_CODE_TABLES: Dict[str, Dict[int, str]] = {
    "npd": {  # Norwegian Petroleum Directorate / NPD convention
        1: "sandstone", 2: "shale", 3: "limestone", 4: "dolomite",
        5: "siltstone", 6: "marl", 7: "coal", 8: "conglomerate",
        9: "chalk", 10: "anhydrite", 11: "halite", 12: "tuff",
        13: "claystone", 14: "mudstone", 15: "basalt",
    },
    "cgd": {  # Common Geologic Data codes (North Sea convention)
        0: "shale", 1: "sandstone", 2: "siltstone", 3: "limestone",
        4: "dolomite", 5: "coal", 6: "marl", 7: "chalk",
        8: "anhydrite", 9: "conglomerate", 10: "halite",
    },
    "simple": {  # Simplified 3-class (common in facies models)
        0: "shale", 1: "sandstone", 2: "limestone",
    },
    "binary": {  # Sand/shale binary (common in net-to-gross)
        0: "shale", 1: "sandstone",
    },
}


@dataclass
class FaciesEntry:
    """Single entry in a facies dictionary."""
    zone_id: int
    name: str = ""
    color: str = "#CCCCCC"
    lithology: str = ""
    description: str = ""


@dataclass
class FaciesDictionary:
    """Maps zone IDs to names, colours, and lithology descriptions.

    Attributes:
        entries: Dict mapping zone_id → FaciesEntry.
        region_name: The region channel this dictionary applies to.
    """
    entries: Dict[int, FaciesEntry] = field(default_factory=dict)
    region_name: str = ""

    def get_color(self, zone_id: int) -> str:
        """Get colour for a zone ID. Falls back to ZONE_COLORS palette."""
        if zone_id in self.entries:
            return self.entries[zone_id].color
        return ZONE_COLORS[zone_id % len(ZONE_COLORS)]

    def get_label(self, zone_id: int) -> str:
        """Get human-readable label for a zone ID."""
        if zone_id in self.entries and self.entries[zone_id].name:
            return self.entries[zone_id].name
        return str(zone_id)

    def get_lithology(self, zone_id: int) -> str:
        """Get lithology name for a zone ID."""
        if zone_id in self.entries:
            return self.entries[zone_id].lithology
        return ""

    def add(self, zone_id: int, name: str = "", color: str = "",
            lithology: str = "", description: str = ""):
        """Add or update an entry."""
        if not color:
            if lithology and lithology.lower() in STANDARD_LITHO_PALETTE:
                color = STANDARD_LITHO_PALETTE[lithology.lower()]
            else:
                color = ZONE_COLORS[zone_id % len(ZONE_COLORS)]
        self.entries[zone_id] = FaciesEntry(
            zone_id=zone_id, name=name or str(zone_id),
            color=color, lithology=lithology, description=description
        )

    @classmethod
    def from_zone_ids(cls, zone_ids: Sequence[int],
                      region_name: str = "") -> "FaciesDictionary":
        """Create a dictionary from a list of zone IDs with default colours."""
        fd = cls(region_name=region_name)
        for zid in sorted(set(zone_ids)):
            fd.add(zid)
        return fd

    @classmethod
    def from_region_data(cls, region_name: str,
                         wells) -> "FaciesDictionary":
        """Build dictionary from all zone IDs found across wells for a region.

        Args:
            region_name: Name of the region channel (e.g. "LITH", "FACIES").
            wells: Sequence of Well objects with .region attribute.
        """
        zone_ids = set()
        for well in wells:
            if hasattr(well, 'region') and region_name in well.region:
                for entry in well.region[region_name]:
                    if isinstance(entry, (list, tuple)) and len(entry) >= 1:
                        if entry[0] is not None:
                            zone_ids.add(int(entry[0]))

        fd = cls(region_name=region_name)

        # Apply lithology hints if available
        hints = REGION_LITHO_HINTS.get(region_name.upper(), {})
        for zid in sorted(zone_ids):
            litho = hints.get(zid, "")
            fd.add(zid, lithology=litho)

        return fd

    @classmethod
    def from_osdu_units(cls, records: Sequence[dict],
                        region_name: str = "LITH") -> "FaciesDictionary":
        """Build from OSDU LithostratigraphicUnit records.

        Expected record format::
            {
                "id": "...",
                "data": {
                    "Name": "Draupne Formation",
                    "Code": 3,
                    "LithologyType": "shale",
                    "ColorCode": "#808080"
                }
            }
        """
        fd = cls(region_name=region_name)
        for rec in records:
            data = rec.get("data", rec)
            zid = data.get("Code") or data.get("code") or data.get("zone_id")
            if zid is None:
                continue
            zid = int(zid)
            name = data.get("Name", data.get("name", str(zid)))
            color = data.get("ColorCode", data.get("color_code", ""))
            litho = data.get("LithologyType", data.get("lithology", ""))
            desc = data.get("Description", data.get("description", ""))
            fd.add(zid, name=name, color=color, lithology=litho, description=desc)
        return fd

    @classmethod
    def from_region_auto(cls, region_name: str,
                         wells) -> "FaciesDictionary":
        """Auto-detect facies from region values by matching to code tables.

        Scans all zone IDs across wells and tries to match them against known
        lithology code conventions (NPD, CGD, simple, binary). Picks the table
        that covers the most observed zone IDs.

        Args:
            region_name: Name of the region channel.
            wells: Sequence of Well objects with .region attribute.

        Returns:
            FaciesDictionary with auto-detected lithology assignments.
        """
        # Collect all unique zone IDs
        zone_ids: set = set()
        for well in wells:
            if hasattr(well, 'region') and region_name in well.region:
                for entry in well.region[region_name]:
                    if isinstance(entry, (list, tuple)) and len(entry) >= 1:
                        if entry[0] is not None:
                            zone_ids.add(int(entry[0]))

        if not zone_ids:
            return cls(region_name=region_name)

        # Check explicit hints first
        upper_name = region_name.upper()
        for hint_key, hint_map in REGION_LITHO_HINTS.items():
            if hint_key in upper_name and hint_map:
                fd = cls(region_name=region_name)
                for zid in sorted(zone_ids):
                    litho = hint_map.get(zid, "")
                    fd.add(zid, lithology=litho,
                           name=litho.capitalize() if litho else str(zid))
                return fd

        # Try each code table, pick the one with best coverage
        best_table = ""
        best_coverage = 0.0
        for table_name, table in _LITHO_CODE_TABLES.items():
            matched = sum(1 for zid in zone_ids if zid in table)
            coverage = matched / len(zone_ids) if zone_ids else 0
            if coverage > best_coverage:
                best_coverage = coverage
                best_table = table_name

        fd = cls(region_name=region_name)

        if best_coverage >= 0.5 and best_table:
            # Good enough match - apply the code table
            table = _LITHO_CODE_TABLES[best_table]
            for zid in sorted(zone_ids):
                litho = table.get(zid, "")
                name = litho.capitalize() if litho else f"Zone {zid}"
                fd.add(zid, name=name, lithology=litho)
        else:
            # No good match - fall back to default colours
            for zid in sorted(zone_ids):
                fd.add(zid)

        return fd

    @classmethod
    def from_geology(cls, geology_key: str,
                     region_name: str = "FACIES") -> "FaciesDictionary":
        """Build from OSDU facies scheme for a depositional environment.

        Uses the osdu_facies module to look up the standard facies scheme
        for the geological setting and build a FaciesDictionary with
        OSDU-canonical names, lithology types, and standard colours.

        Args:
            geology_key: Geological setting key (e.g. "shallow_marine",
                "coal", "fluvial", "quaternary", "carbonate").
            region_name: The region channel this applies to.

        Returns:
            FaciesDictionary with OSDU-standard labels and colours.

        Example::

            fd = FaciesDictionary.from_geology("shallow_marine")
            print(fd.get_label(1))  # "Tidal Channel"
        """
        try:
            from weco.osdu_facies import get_facies_scheme
        except ImportError:
            return cls(region_name=region_name)

        scheme = get_facies_scheme(geology_key)
        if scheme is None:
            return cls(region_name=region_name)
        return scheme.to_facies_dict(region_name=region_name)
