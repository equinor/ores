#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
10genhorizons.py

Generate HorizonInterpretation WPC records from the boundaries of
StratigraphicUnitInterpretation records in a strat column manifest,
using ages from the linked ChronoStratigraphy reference-data manifest.

For each unit's linked ChronoStratigraphy record:
  - AgeBegin (older/deeper) -> base boundary horizon
  - AgeEnd   (younger/shallower) -> top boundary horizon

Unique horizons are generated per distinct age value.  The strat column
manifest is updated IN-PLACE:
  - Each unit gets OlderPossibleAge, YoungerPossibleAge
  - Each unit gets ColumnStratigraphicHorizonTopID, ColumnStratigraphicHorizonBaseID
  - HorizonInterpretation WPCs are appended to Data.WorkProductComponents

Usage (PowerShell, from repo root):
  py .\demo\py\10genhorizons.py --verbose
  py .\demo\py\10genhorizons.py --dry-run --verbose    # preview, don't write
  py .\demo\py\10genhorizons.py --out-horizons .\demo\strat\manifest_horizons.json --verbose
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
STRAT_DIR  = SCRIPT_DIR.parent / "strat"
MANIFEST_SC = STRAT_DIR / "manifest_stratcolumn.json"
MANIFEST_CH = STRAT_DIR / "manifest_chronostratics.json"

KIND_HORIZON = "osdu:wks:work-product-component--HorizonInterpretation:1.2.0"
KIND_UNIT    = "osdu:wks:work-product-component--StratigraphicUnitInterpretation:1.3.0"

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _save(p: Path, obj: Any) -> None:
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _acl(owners: List[str], viewers: List[str]) -> dict:
    return {"owners": owners, "viewers": viewers}


def _legal(legaltag: str, countries: List[str]) -> dict:
    return {"legaltags": [legaltag], "otherRelevantDataCountries": countries}


def sanitize_token(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s.strip())
    return re.sub(r"-+", "-", s)[:200]


def _age_token(age: float) -> str:
    """Turn 538.8 -> '538p8', 66.0 -> '66p0' for safe IDs."""
    s = f"{age:g}"
    return s.replace(".", "p").replace("-", "m")


def _horizon_id(partition: str, column_token: str, age: float) -> str:
    return f"{partition}:work-product-component--HorizonInterpretation:{column_token}-H-{_age_token(age)}Ma:"


# ---------------------------------------------------------------------------
# horizon builder
# ---------------------------------------------------------------------------

def build_horizon(
    partition: str, owners: List[str], viewers: List[str],
    legaltag: str, countries: List[str],
    column_token: str, age: float,
    label: str, role_type_id: str,
) -> dict:
    """Build a single HorizonInterpretation record for a boundary at `age` Ma."""
    hid = _horizon_id(partition, column_token, age)
    return {
        "id": hid,
        "kind": KIND_HORIZON,
        "acl": _acl(owners, viewers),
        "legal": _legal(legaltag, countries),
        "data": {
            "Name": label,
            "Description": f"Chronostratigraphic boundary at {age} Ma",
            "MeanPossibleAge": age,
            "OlderPossibleAge": age,
            "YoungerPossibleAge": age,
            "StratigraphicRoleTypeID": role_type_id,
            "isConformableAbove": True,
            "isConformableBelow": True,
            "IsDiscoverable": True,
        },
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Generate HorizonInterpretation records from unit boundaries and update strat column manifest"
    )
    ap.add_argument("--sc-manifest", default=str(MANIFEST_SC),
                    help=f"Strat column manifest (default: {MANIFEST_SC})")
    ap.add_argument("--ch-manifest", default=str(MANIFEST_CH),
                    help=f"Chrono ref-data manifest (default: {MANIFEST_CH})")
    ap.add_argument("--partition", default="dev")
    ap.add_argument("--namespace", default="", help="Alias for --partition")
    ap.add_argument("--owners", default="data.default.owners@dev.dataservices.energy")
    ap.add_argument("--viewers", default="data.office.global.viewers@dev.dataservices.energy")
    ap.add_argument("--legaltag", default="dev-equinor-osdu-reference-default")
    ap.add_argument("--countries", default="NO")
    ap.add_argument("--column-token", default="ChronoStratigraphicScheme-ICS2017",
                    help="Column token used in horizon IDs")
    ap.add_argument("--out-horizons", default="",
                    help="Also write a standalone horizon manifest to this path")
    ap.add_argument("--dry-run", action="store_true",
                    help="Preview changes, don't overwrite the strat column manifest")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    verbose = args.verbose
    partition = (args.namespace or args.partition or "dev").strip()
    owners  = [s.strip() for s in args.owners.split(",") if s.strip()]
    viewers = [s.strip() for s in args.viewers.split(",") if s.strip()]
    countries = [s.strip() for s in args.countries.split(",") if s.strip()]
    legaltag = args.legaltag
    column_token = args.column_token
    role_type_id = f"{partition}:reference-data--StratigraphicRoleType:Chronostratigraphic:"

    # --- 1. Load both manifests ---
    sc_path = Path(args.sc_manifest)
    ch_path = Path(args.ch_manifest)
    if not sc_path.exists():
        print(f"Strat column manifest not found: {sc_path}", file=sys.stderr); sys.exit(1)
    if not ch_path.exists():
        print(f"Chrono manifest not found: {ch_path}", file=sys.stderr); sys.exit(1)

    sc = _load(sc_path)
    ch = _load(ch_path)

    # --- 2. Build chrono lookup: id -> data ---
    chrono_by_id: Dict[str, dict] = {}
    for r in ch.get("ReferenceData") or []:
        if isinstance(r, dict) and r.get("id"):
            chrono_by_id[r["id"]] = r.get("data", {})
    if verbose:
        print(f"Loaded {len(chrono_by_id)} chrono records from {ch_path.name}")

    # --- 3. Walk strat column units, collect ages ---
    wpcs = sc.get("Data", {}).get("WorkProductComponents", [])
    units = [w for w in wpcs if KIND_UNIT in (w.get("kind") or "")]

    # age -> set of (unit_name, "top"|"base")  for labeling
    age_info: Dict[float, List[Tuple[str, str]]] = {}
    unit_ages: Dict[str, Tuple[Optional[float], Optional[float]]] = {}  # unit_id -> (older, younger)

    matched = 0
    unmatched = 0
    for u in units:
        d = u.get("data", {})
        uid = u.get("id", "")
        cid = d.get("ChronoStratigraphyID", "")
        cd = chrono_by_id.get(cid)
        if not cd:
            unmatched += 1
            continue
        matched += 1
        name = d.get("Name") or cd.get("Name") or "?"
        age_begin: Optional[float] = cd.get("AgeBegin")  # older = base
        age_end:   Optional[float] = cd.get("AgeEnd")    # younger = top

        unit_ages[uid] = (age_begin, age_end)

        if age_begin is not None:
            age_info.setdefault(age_begin, []).append((name, "base"))
        if age_end is not None:
            age_info.setdefault(age_end, []).append((name, "top"))

    if verbose:
        print(f"Units matched to chrono: {matched}, unmatched: {unmatched}")
        print(f"Unique boundary ages: {len(age_info)}")

    # --- 4. Generate HorizonInterpretation records ---
    horizons: List[dict] = []
    horizon_ids_by_age: Dict[float, str] = {}

    for age in sorted(age_info.keys()):
        entries = age_info[age]
        # Build a descriptive label:
        # prefer "Top <unit>" at that age (younger boundary),
        # fallback to "Base <unit>" (older boundary)
        tops  = [name for name, side in entries if side == "top"]
        bases = [name for name, side in entries if side == "base"]
        if tops:
            label = f"Top {tops[0]}"
            if len(tops) > 1:
                label += f" (+{len(tops)-1})"
        elif bases:
            label = f"Base {bases[0]}"
            if len(bases) > 1:
                label += f" (+{len(bases)-1})"
        else:
            label = f"{age} Ma"

        hid = _horizon_id(partition, column_token, age)
        horizon_ids_by_age[age] = hid

        rec = build_horizon(
            partition, owners, viewers, legaltag, countries,
            column_token, age, label, role_type_id,
        )
        horizons.append(rec)

    if verbose:
        print(f"Generated {len(horizons)} HorizonInterpretation records")
        # Show a few
        for h in horizons[:5]:
            hd = h["data"]
            print(f"  {hd['Name']:40s}  {hd['MeanPossibleAge']:>8g} Ma")
        if len(horizons) > 5:
            print(f"  ... and {len(horizons)-5} more")

    # --- 5. Update unit records with ages + horizon refs ---
    updated = 0
    for u in units:
        uid = u.get("id", "")
        ages = unit_ages.get(uid)
        if not ages:
            continue
        older, younger = ages
        d = u.get("data", {})
        if older is not None:
            d["OlderPossibleAge"] = older
            hid = horizon_ids_by_age.get(older)
            if hid:
                d["ColumnStratigraphicHorizonBaseID"] = hid
        if younger is not None:
            d["YoungerPossibleAge"] = younger
            hid = horizon_ids_by_age.get(younger)
            if hid:
                d["ColumnStratigraphicHorizonTopID"] = hid
        updated += 1

    if verbose:
        print(f"Updated {updated} unit records with ages + horizon refs")

    # --- 6. Append horizons to strat column manifest WPCs ---
    # Remove any existing horizons first
    existing_horizon_ids = {h["id"] for h in horizons}
    sc_wpcs = sc.get("Data", {}).get("WorkProductComponents", [])
    sc_wpcs_clean = [w for w in sc_wpcs if w.get("id") not in existing_horizon_ids
                     and KIND_HORIZON not in (w.get("kind") or "")]
    sc["Data"]["WorkProductComponents"] = sc_wpcs_clean + horizons

    total_wpcs = len(sc["Data"]["WorkProductComponents"])

    # --- 7. Write outputs ---
    if args.dry_run:
        print(f"\n[dry-run] Would write {total_wpcs} WPCs to {sc_path.name}")
        print(f"  Units: {len(units)}, Horizons: {len(horizons)}")
        return

    _save(sc_path, sc)
    print(f"\nUpdated {sc_path.name}: {total_wpcs} WPCs ({len(units)} units + {len(horizons)} horizons + rest)")

    if args.out_horizons:
        h_manifest = {
            "kind": "osdu:wks:Manifest:1.0.0",
            "acl": _acl(owners, viewers),
            "legal": _legal(legaltag, countries),
            "ReferenceData": [],
            "MasterData": [],
            "Data": {
                "Datasets": [],
                "WorkProductComponents": horizons,
                "WorkProduct": {},
            },
        }
        hp = Path(args.out_horizons)
        _save(hp, h_manifest)
        print(f"Wrote standalone horizon manifest: {hp} ({len(horizons)} records)")

    print("Done. Re-run 8deploy_stratcolumn.py to deploy updated records.")


if __name__ == "__main__":
    main()
