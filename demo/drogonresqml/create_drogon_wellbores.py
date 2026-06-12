#!/usr/bin/env python3
"""
create_drogon_wellbores.py - Curated Drogon Well/Wellbore master data + linking.

RDDMS/RESQML is NOT the wellbore authority. The reservoir manifest builder
(open-etp-client) deliberately leaves ``WellboreID`` empty on the WellLog /
WellboreMarkerSet records it derives from the EPC. This script is the
authority side:

  1. Create the curated Drogon master-data--Well and master-data--Wellbore
     records in the OSDU catalog (the wellbore authority).
  2. Link the RDDMS-derived WellLog / WellboreMarkerSet records to those
     wellbores by matching the record Name (e.g. "55_33-1 log",
     "55_33-A-3 markers", "RFT_55_33-A-2 log") to a Wellbore FacilityName,
     and patch ``data.WellboreID`` accordingly.

The marker/log records keep their RDDMS-built Name/Description untouched; only
the WellboreID cross-reference is added here.

Wellbore creation is pushed only with ``--push`` (a write to a shared
catalog). The linked manifest is always written to disk for review and for the
dataset push (ingest_drogon.py / --push-manifest) to consume.

Usage
-----
    # Offline: build records + link manifest, write artifacts, push nothing
    python create_drogon_wellbores.py interop --save-only

    # Create the wellbores in the catalog, write the linked manifest
    python create_drogon_wellbores.py interop --push

    # Also push the linked WPC manifest (markers/logs with WellboreID set)
    python create_drogon_wellbores.py interop --push --push-manifest
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# Reuse the instance config + ACL/legal patch + storage push from the
# dataset ingest tool (single source of truth for auth/ACL/legal/push).
from ingest_drogon import (  # noqa: E402
    InstanceConfig,
    authenticate,
    patch_manifest,
    push_via_storage,
)

# ── Constants ──────────────────────────────────────────────────────────────
WELL_KIND = "osdu:wks:master-data--Well:1.1.0"
WELLBORE_KIND = "osdu:wks:master-data--Wellbore:1.2.0"
DEFAULT_MANIFEST = Path("/tmp/manifest_drogon2_local_v2.json")
SOURCE_TAG = "ORES Drogon demo (curated)"

# Curated Drogon well/wellbore hierarchy (the authoritative master data).
# Keys are the wellbore names exactly as they appear (underscore form) in the
# RDDMS-derived record Names. Matching is separator/case-insensitive, so the
# OSDU FacilityName uses the canonical slash form.
#   well display name -> [wellbore name keys]
WELLS: Dict[str, List[str]] = {
    "55/33-1": ["55_33-1"],
    "55/33-2": ["55_33-2"],
    "55/33-3": ["55_33-3"],
    "55/33-A": [
        "55_33-A-1",
        "55_33-A-2",
        "55_33-A-3",
        "55_33-A-4",
        "55_33-A-5",
        "55_33-A-6",
    ],
}


# ── Helpers ──────────────────────────────────────────────────────────────--
def _slug(name: str) -> str:
    """Stable id fragment: alnum runs joined by '-' (e.g. '55/33-A-1' -> '55-33-A-1')."""
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")


def _norm(name: str | None) -> str:
    """Separator/case-insensitive match key ('55/33-A-3' == '55_33-a-3' -> '5533a3')."""
    return re.sub(r"[^a-z0-9]+", "", name.lower()) if name else ""


def _wellbore_key_from_record_name(name: str | None) -> str | None:
    """Derive the wellbore name from a WellLog/WellboreMarkerSet record Name.

    "55_33-1 log" / "55_33-A-3 markers" / "RFT_55_33-A-2 log" -> "55_33-A-2"
    """
    if not name:
        return None
    s = name.strip()
    for suffix in (" markers", " log"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    if s.startswith("RFT_"):
        s = s[4:]
    s = s.strip()
    return s or None


def _meta(cfg: InstanceConfig) -> Dict[str, Any]:
    """Standard acl + legal block for the target instance."""
    return {
        "acl": {"owners": cfg.owners, "viewers": cfg.viewers},
        "legal": {
            "legaltags": [cfg.legal_tag],
            "otherRelevantDataCountries": cfg.countries,
            "status": "compliant",
        },
    }


# ── Build curated master data ───────────────────────────────────────────────
def build_master_data(
    cfg: InstanceConfig,
) -> Tuple[List[dict], List[dict], Dict[str, str]]:
    """Build Well + Wellbore records and a {normalised-name -> wellbore id} map."""
    meta = _meta(cfg)
    wells: List[dict] = []
    wellbores: List[dict] = []
    name_to_id: Dict[str, str] = {}

    for well_name, wb_keys in WELLS.items():
        well_id = f"{cfg.partition}:master-data--Well:Drogon-{_slug(well_name)}"
        wells.append(
            {
                "id": well_id,
                "kind": WELL_KIND,
                **meta,
                "data": {
                    "FacilityName": well_name,
                    "FacilityID": well_name,
                    "Source": SOURCE_TAG,
                },
            }
        )
        for wb_key in wb_keys:
            wb_display = wb_key.replace("_", "/")
            wb_id = f"{cfg.partition}:master-data--Wellbore:Drogon-{_slug(wb_key)}"
            wellbores.append(
                {
                    "id": wb_id,
                    "kind": WELLBORE_KIND,
                    **meta,
                    "data": {
                        "FacilityName": wb_display,
                        "FacilityID": wb_display,
                        "WellID": f"{well_id}:",
                        "Source": SOURCE_TAG,
                    },
                }
            )
            # Index by both the underscore key and the slash display form.
            name_to_id[_norm(wb_key)] = wb_id
            name_to_id[_norm(wb_display)] = wb_id

    return wells, wellbores, name_to_id


# ── Link manifest ────────────────────────────────────────────────────────--
def _iter_wpcs(manifest: dict) -> List[dict]:
    data = manifest.get("Data", {}) or {}
    wpcs = data.get("WorkProductComponents")
    if wpcs is None:
        wpcs = data.get("WorkProductComponent", [])
    if isinstance(wpcs, dict):
        wpcs = [wpcs]
    return wpcs or []


def link_manifest(
    manifest: dict, name_to_id: Dict[str, str]
) -> Tuple[int, int, List[str]]:
    """Set data.WellboreID on WellLog / WellboreMarkerSet records by name match.

    Returns (linked, already_set, unmatched_names).
    """
    linked = 0
    already = 0
    unmatched: List[str] = []

    for rec in _iter_wpcs(manifest):
        kind = rec.get("kind", "")
        if "WellboreMarkerSet" not in kind and "WellLog" not in kind:
            continue
        data = rec.get("data", {})
        if data.get("WellboreID"):
            already += 1
            continue
        key = _wellbore_key_from_record_name(data.get("Name"))
        wb_id = name_to_id.get(_norm(key)) if key else None
        if wb_id:
            data["WellboreID"] = f"{wb_id}:"
            linked += 1
        else:
            unmatched.append(data.get("Name") or "<no name>")

    return linked, already, unmatched


# ── Push ─────────────────────────────────────────────────────────────────--
def push_records(token: str, cfg: InstanceConfig, records: List[dict]) -> bool:
    """PUT master-data records to the Storage API in batches of 100."""
    url = f"{cfg.base_osdu}/api/storage/v2/records"
    hdrs = cfg.headers(token)
    BATCH = 100
    ok = fail = 0
    for i in range(0, len(records), BATCH):
        batch = records[i : i + BATCH]
        r = httpx.put(url, headers=hdrs, json=batch, timeout=120)
        if r.is_success:
            cnt = r.json().get("recordCount", len(batch))
            ok += cnt
            print(f"    ✓ {cnt} stored")
        else:
            fail += len(batch)
            print(f"    ✗ {r.status_code}: {r.text[:300]}")
    print(f"  Results: {ok} stored, {fail} failed")
    return fail == 0


# ── Main ─────────────────────────────────────────────────────────────────--
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("instance", choices=["interop", "eqndev"],
                    help="Target OSDU instance (provides partition/ACL/legal)")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST,
                    help=f"WPC manifest to link (default: {DEFAULT_MANIFEST})")
    ap.add_argument("--out-dir", type=Path, default=SCRIPT_DIR,
                    help="Directory for output artifacts")
    ap.add_argument("--save-only", action="store_true",
                    help="Build + link + save artifacts; push nothing (default)")
    ap.add_argument("--push", action="store_true",
                    help="Create the Well/Wellbore master data in the catalog")
    ap.add_argument("--push-manifest", action="store_true",
                    help="Also push the linked WPC manifest (markers/logs)")
    args = ap.parse_args()

    cfg = InstanceConfig(args.instance)
    do_push = args.push or args.push_manifest

    print("═" * 60)
    print(f"  Drogon wellbore authority → {cfg.name} ({cfg.host})")
    print(f"  Partition: {cfg.partition}   Legal: {cfg.legal_tag}")
    print(f"  Manifest:  {args.manifest}")
    print("═" * 60)

    # 1. Build curated master data ------------------------------------------
    wells, wellbores, name_to_id = build_master_data(cfg)
    print(f"\n=== 1. Curated master data ===")
    print(f"  {len(wells)} Well + {len(wellbores)} Wellbore records")
    for w in wells:
        children = [wb["data"]["FacilityName"] for wb in wellbores
                    if wb["data"]["WellID"].rstrip(":") == w["id"]]
        print(f"    Well {w['data']['FacilityName']:<10} → {', '.join(children)}")

    wb_path = args.out_dir / f"drogon_wellbores_{cfg.name}.json"
    wb_path.write_text(json.dumps(wells + wellbores, indent=2))
    print(f"  Saved: {wb_path.name}")

    # 2. Link manifest -------------------------------------------------------
    print(f"\n=== 2. Link markers/logs → Wellbore ===")
    if not args.manifest.exists():
        print(f"  ⚠ Manifest not found: {args.manifest} (skipping link step)")
        linked_path = None
    else:
        manifest = json.loads(args.manifest.read_text())
        linked, already, unmatched = link_manifest(manifest, name_to_id)
        print(f"  Linked {linked} records"
              + (f", {already} already set" if already else ""))
        if unmatched:
            print(f"  ⚠ {len(unmatched)} unmatched: {sorted(set(unmatched))}")
        # ACL/legal for the target instance, then save the linked manifest.
        patch_manifest(manifest, cfg)
        linked_path = args.out_dir / f"{args.manifest.stem}.linked_{cfg.name}.json"
        linked_path.write_text(json.dumps(manifest, indent=2))
        print(f"  Saved: {linked_path.name}")

    # 3. Push (only when explicitly requested) ------------------------------
    if not do_push:
        print(f"\n{'─' * 60}")
        print("  Done (save-only — nothing pushed to the catalog)")
        return

    token = authenticate(cfg)

    print(f"\n=== 3. Create wellbores in catalog ({cfg.name}) ===")
    print("  PUT Wells...")
    ok_well = push_records(token, cfg, wells)
    print("  PUT Wellbores...")
    ok_wb = push_records(token, cfg, wellbores)

    if args.push_manifest and linked_path is not None:
        print(f"\n=== 4. Push linked manifest ({cfg.name}) ===")
        push_via_storage(token, cfg, json.loads(linked_path.read_text()))

    if ok_well and ok_wb:
        print(f"\n{'═' * 60}")
        print(f"  ✓ {len(wells)} Well + {len(wellbores)} Wellbore records in {cfg.name}")
    else:
        print("\n  ⚠ Some records failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
