"""
weco.strat_column — Stratigraphic Column model and OSDU integration
====================================================================

Adapted from ``~/ores/demo/strat/stratcolumnhandler.py``.

Provides a lightweight stratigraphic column model (Column → Rank → Unit →
Horizon) that can be:

* Built from OSDU WPC JSON bundles
* Built from RESQML JSON graphs
* Built from simple Python dicts (for testing)
* Mapped onto WeCo Wells as hierarchical region layers

The canonical OSDU WPC kinds used:

* ``work-product-component--StratigraphicColumn``
* ``work-product-component--StratigraphicColumnRankInterpretation``
* ``work-product-component--StratigraphicUnitInterpretation``
* ``work-product-component--HorizonInterpretation``

Usage::

    from weco.strat_column import StratColumn

    col = StratColumn.from_dict({...})
    col.apply_to_well(well, well_picks)
"""

from __future__ import annotations

import json
import logging
import uuid as _uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Data model
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class StratHorizon:
    """Boundary between two stratigraphic units (top or base)."""

    name: str
    uuid: str = field(default_factory=lambda: str(_uuid.uuid4()))
    unit_name: Optional[str] = None
    boundary_type: str = "Top"  # 'Top' | 'Base'
    age_ma: Optional[float] = None


@dataclass
class StratUnit:
    """One stratigraphic unit within a rank."""

    name: str
    uuid: str = field(default_factory=lambda: str(_uuid.uuid4()))
    level: Optional[int] = None
    top_age_ma: Optional[float] = None
    base_age_ma: Optional[float] = None
    parent_name: Optional[str] = None
    color_html: Optional[str] = None
    depositional_environment: Optional[str] = None


@dataclass
class StratRank:
    """One rank (e.g. System, Series, Stage) in a stratigraphic column."""

    name: str
    kind: str = "litho"  # 'litho' | 'chrono'
    level: Optional[int] = None
    ordering: str = "OlderToYounger"
    units: List[StratUnit] = field(default_factory=list)


@dataclass
class StratColumn:
    """A stratigraphic column comprising one or more ranks."""

    name: str
    ranks: List[StratRank] = field(default_factory=list)
    horizons: List[StratHorizon] = field(default_factory=list)

    # -------------------------------------------------------------------
    # Constructors
    # -------------------------------------------------------------------

    @classmethod
    def from_dict(cls, d: dict) -> "StratColumn":
        """Build from a plain dict (for tests and JSON config).

        Expected format::

            {
                "name": "My Column",
                "ranks": [
                    {
                        "name": "System",
                        "kind": "chrono",
                        "units": [
                            {"name": "Cretaceous", "top_age_ma": 66.0, "base_age_ma": 145.0},
                            ...
                        ]
                    }
                ],
                "horizons": [
                    {"name": "Top Cretaceous", "age_ma": 66.0, "unit_name": "Cretaceous", "boundary_type": "Top"},
                    ...
                ]
            }
        """
        ranks = []
        for rd in d.get("ranks", []):
            units = [StratUnit(**{k: v for k, v in u.items()
                                  if k in StratUnit.__dataclass_fields__})
                     for u in rd.get("units", [])]
            ranks.append(StratRank(
                name=rd["name"],
                kind=rd.get("kind", "litho"),
                level=rd.get("level"),
                ordering=rd.get("ordering", "OlderToYounger"),
                units=units,
            ))
        horizons = [StratHorizon(**{k: v for k, v in h.items()
                                    if k in StratHorizon.__dataclass_fields__})
                    for h in d.get("horizons", [])]
        return cls(name=d.get("name", "unnamed"), ranks=ranks, horizons=horizons)

    @classmethod
    def from_osdu_bundle(cls, records: list) -> "StratColumn":
        """Build from a list of OSDU WPC records.

        Expects the records to include the Column, its Ranks, and Units.
        """
        col_rec = None
        rank_recs = []
        unit_recs = []
        horizon_recs = []

        for r in records:
            kind = r.get("kind", "")
            if "StratigraphicColumn:" in kind and "Rank" not in kind:
                col_rec = r
            elif "StratigraphicColumnRankInterpretation:" in kind:
                rank_recs.append(r)
            elif "StratigraphicUnitInterpretation:" in kind:
                unit_recs.append(r)
            elif "HorizonInterpretation:" in kind:
                horizon_recs.append(r)

        # Build lookup
        unit_by_id = {r["id"]: r for r in unit_recs if "id" in r}
        horizon_by_id = {r["id"]: r for r in horizon_recs if "id" in r}

        col_name = "unnamed"
        if col_rec:
            col_name = col_rec.get("data", {}).get("Name", col_rec.get("id", "unnamed"))

        ranks = []
        for rr in rank_recs:
            rd = rr.get("data", {})
            rank_name = rd.get("Name", rr.get("id", "Rank"))
            rank_kind = "chrono" if rd.get("IsChronostratigraphic") else "litho"

            units = []
            for u_ref in rd.get("StratigraphicUnits", []):
                uid = u_ref if isinstance(u_ref, str) else u_ref.get("$ref", u_ref.get("id", ""))
                ur = unit_by_id.get(uid, unit_by_id.get(uid.rstrip(":"), {}))
                ud = ur.get("data", {}) if ur else {}
                units.append(StratUnit(
                    name=ud.get("Name", uid),
                    uuid=ur.get("id", str(_uuid.uuid4())) if ur else str(_uuid.uuid4()),
                    top_age_ma=ud.get("OlderChronostratigraphicAge", ud.get("TopAgeMa")),
                    base_age_ma=ud.get("YoungerChronostratigraphicAge", ud.get("BaseAgeMa")),
                    depositional_environment=ud.get("DepositionalEnvironment"),
                ))
            ranks.append(StratRank(
                name=rank_name, kind=rank_kind, units=units,
            ))

        horizons = []
        for hr in horizon_recs:
            hd = hr.get("data", {})
            horizons.append(StratHorizon(
                name=hd.get("Name", hr.get("id", "")),
                uuid=hr.get("id", str(_uuid.uuid4())),
                age_ma=hd.get("AgeMa"),
            ))

        return cls(name=col_name, ranks=ranks, horizons=horizons)

    @classmethod
    def from_json(cls, path: str) -> "StratColumn":
        """Load from a JSON file (dict format or OSDU bundle)."""
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, list):
            return cls.from_osdu_bundle(data)
        if "records" in data:
            return cls.from_osdu_bundle(data["records"])
        return cls.from_dict(data)

    # -------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize to a plain dict."""
        return {
            "name": self.name,
            "ranks": [
                {
                    "name": r.name,
                    "kind": r.kind,
                    "level": r.level,
                    "ordering": r.ordering,
                    "units": [
                        {
                            "name": u.name,
                            "level": u.level,
                            "top_age_ma": u.top_age_ma,
                            "base_age_ma": u.base_age_ma,
                            "parent_name": u.parent_name,
                            "color_html": u.color_html,
                            "depositional_environment": u.depositional_environment,
                        }
                        for u in r.units
                    ],
                }
                for r in self.ranks
            ],
            "horizons": [
                {
                    "name": h.name,
                    "unit_name": h.unit_name,
                    "boundary_type": h.boundary_type,
                    "age_ma": h.age_ma,
                }
                for h in self.horizons
            ],
        }

    def to_json(self, path: str) -> None:
        """Write to JSON file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    # -------------------------------------------------------------------
    # Apply to wells
    # -------------------------------------------------------------------

    def apply_to_well(
        self,
        well,
        well_picks: list,
        *,
        add_no_crossing: bool = True,
    ) -> dict:
        """Apply this column's ranks as regions on a WeCo Well.

        Parameters
        ----------
        well : Well
            Target well (must have data["Depth"]).
        well_picks : list of dict
            ``[{"unit_name": str, "top_md": float, "base_md": float}]``
        add_no_crossing : bool
            If True, also creates a "StratHorizons" region from unit boundaries.

        Returns
        -------
        dict
            ``{"regions_created": [...], "no_crossing_region": str|None}``
        """
        from weco.rddms import import_units_as_region, import_horizons_as_region

        picks_by_name = {p["unit_name"]: p for p in well_picks}
        created = []

        for rank in self.ranks:
            region_name = f"Rank_{rank.name}".replace(" ", "_")
            unit_picks = []
            for unit in rank.units:
                pick = picks_by_name.get(unit.name)
                if pick:
                    unit_picks.append({
                        "name": unit.name,
                        "top_md": pick["top_md"],
                        "base_md": pick["base_md"],
                    })
            if unit_picks:
                import_units_as_region(well, unit_picks, region_name)
                created.append(region_name)

        nc_region = None
        if add_no_crossing:
            horizon_picks = []
            for pick in well_picks:
                horizon_picks.append({
                    "name": f"Top_{pick['unit_name']}",
                    "md": pick["top_md"],
                })
            if horizon_picks:
                nc_region = "StratHorizons"
                import_horizons_as_region(well, horizon_picks, nc_region)

        return {"regions_created": created, "no_crossing_region": nc_region}

    def apply_to_well_list(
        self,
        well_list,
        picks_per_well: dict,
        *,
        add_no_crossing: bool = True,
    ) -> dict:
        """Apply column to all wells in a WellList.

        Parameters
        ----------
        well_list : WellList
        picks_per_well : dict
            ``{well_name: [{"unit_name": str, "top_md": float, "base_md": float}]}``

        Returns
        -------
        dict
            ``{well_name: apply_result}``
        """
        results = {}
        for w in well_list.wells:
            picks = picks_per_well.get(w.name, [])
            if picks:
                results[w.name] = self.apply_to_well(
                    w, picks, add_no_crossing=add_no_crossing
                )
        return results

    # -------------------------------------------------------------------
    # Depositional environment detection
    # -------------------------------------------------------------------

    def detect_depositional_environments(self) -> list:
        """Return a deduplicated list of depositional environments from units."""
        envs = set()
        for rank in self.ranks:
            for unit in rank.units:
                if unit.depositional_environment:
                    envs.add(unit.depositional_environment)
        return sorted(envs)

    @property
    def unit_count(self) -> int:
        return sum(len(r.units) for r in self.ranks)

    @property
    def horizon_count(self) -> int:
        return len(self.horizons)

    def __repr__(self) -> str:
        return (
            f"StratColumn(name={self.name!r}, "
            f"ranks={len(self.ranks)}, "
            f"units={self.unit_count}, "
            f"horizons={self.horizon_count})"
        )
