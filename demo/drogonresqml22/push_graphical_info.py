#!/usr/bin/env python3
"""
push_graphical_info.py – Push a GraphicalInformationSet + ContinuousColorMaps
into the maap/drogon22 RDDMS dataspace via REST transactional API.

This is a RESQML 2.2 / EML Common 2.3 feature that associates display
settings (color scales, log mapping, opacity) with properties.

The client (ORES viz) reads these when rendering property values on geometry.

Usage:
    python demo/drogonresqml22/push_graphical_info.py interop
    python demo/drogonresqml22/push_graphical_info.py swedev
    python demo/drogonresqml22/push_graphical_info.py interop --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from pathlib import Path

try:
    import httpx
except ImportError:
    sys.exit("pip install httpx")

SCRIPT_DIR = Path(__file__).resolve().parent
DEMO_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(DEMO_DIR))

from _auth import get_token, load_instance  # noqa: E402

# ── Config ────────────────────────────────────────────────────────────────
DATASPACE = "maap/drogon22"

# UUIDs for new objects (stable so re-runs overwrite)
GIS_UUID = "f0a1b2c3-d4e5-4f67-8901-abcdef123456"
CMAP_PLASMA_UUID = "c0100001-0001-4000-a000-000000000001"
CMAP_VIRIDIS_UUID = "c0100001-0001-4000-a000-000000000002"
CMAP_HOT_UUID = "c0100001-0001-4000-a000-000000000003"

# Target property UUIDs (from drogon22 manifest)
PROP_OIL_SAT = "34d8af4f-2178-413a-b8c1-92100515bb5d"       # Oil Saturation [0-1]
PROP_GAS_SAT = "291af871-c827-4797-ba22-026891b65a44"       # Gas Saturation [0-1]
PROP_OIL_VOL = "0490b8f5-8d1f-4315-a3c6-d062436a8feb"      # Oil Bulk Volume [0-12938]
PROP_PERM = "396deb9c-3634-4d62-a35a-ab9d735cea69"          # Permeability (if present)
PROP_PORO = "3099b3c7-2689-4acc-8bba-724d05e75ef5"          # Carbonate Vol Frac [0-1]
PROP_WSAT = "160356a2-5d1e-4424-a937-3176ca2bfc2f"          # Water Sat (Gas Zone)

# IjkGrid UUID (supporting rep for all properties)
IJK_UUID = "2c6de928-7e08-4601-b979-34048bd68c02"


# ═══════════════════════════════════════════════════════════════════════════
# EML 2.3 object builders
# ═══════════════════════════════════════════════════════════════════════════

def _citation(title: str, desc: str = "") -> dict:
    """EML 2.3 Citation block."""
    return {
        "Title": title,
        "Description": desc or title,
        "Creation": "2026-05-20T10:00:00Z",
        "Originator": "Drogon RESQML 2.2 Demo (Equinor)",
        "Format": "ORES push_graphical_info.py",
    }


def _data_object_ref(uuid: str, content_type: str, title: str = "") -> dict:
    """EML DataObjectReference."""
    return {
        "UUID": uuid,
        "ContentType": content_type,
        "Title": title,
    }


def build_continuous_colormap(uuid: str, title: str,
                               colors: list[dict]) -> dict:
    """Build an eml23.ContinuousColorMap object.

    Each entry in colors: {index: float, hue: int, sat: float, val: float, alpha: float}
    """
    entries = []
    for c in colors:
        entries.append({
            "Index": c["index"],
            "Hsv": {
                "Hue": c["hue"],
                "Saturation": c["sat"],
                "Value": c["val"],
                "Alpha": c.get("alpha", 1.0),
            }
        })
    return {
        "Uuid": uuid,
        "SchemaVersion": "2.3",
        "Citation": _citation(title, f"Continuous color map: {title}"),
        "Entry": entries,
    }


def build_graphical_information_set() -> dict:
    """Build the eml23.GraphicalInformationSet object.

    Associates color maps + display settings with specific properties.
    """
    gi_entries = [
        # Oil Saturation → plasma, linear [0, 1]
        {
            "TargetObject": _data_object_ref(
                PROP_OIL_SAT,
                "application/x-resqml+xml;version=2.2;type=ContinuousProperty",
                "Oil Saturation",
            ),
            "ColorInformation": {
                "UseLogarithmicMapping": False,
                "UseReverseMapping": False,
                "MinIndex": 0.0,
                "MaxIndex": 1.0,
                "ColorMap": _data_object_ref(
                    CMAP_PLASMA_UUID,
                    "application/x-eml+xml;version=2.3;type=ContinuousColorMap",
                    "plasma",
                ),
            },
        },
        # Gas Saturation → viridis reversed, linear [0, 1]
        {
            "TargetObject": _data_object_ref(
                PROP_GAS_SAT,
                "application/x-resqml+xml;version=2.2;type=ContinuousProperty",
                "Gas Saturation",
            ),
            "ColorInformation": {
                "UseLogarithmicMapping": False,
                "UseReverseMapping": True,
                "MinIndex": 0.0,
                "MaxIndex": 1.0,
                "ColorMap": _data_object_ref(
                    CMAP_VIRIDIS_UUID,
                    "application/x-eml+xml;version=2.3;type=ContinuousColorMap",
                    "viridis",
                ),
            },
        },
        # Oil Bulk Volume → hot, logarithmic [1, 12938]
        {
            "TargetObject": _data_object_ref(
                PROP_OIL_VOL,
                "application/x-resqml+xml;version=2.2;type=ContinuousProperty",
                "Oil Bulk Volume",
            ),
            "ColorInformation": {
                "UseLogarithmicMapping": True,
                "UseReverseMapping": False,
                "MinIndex": 1.0,
                "MaxIndex": 12938.49,
                "ColorMap": _data_object_ref(
                    CMAP_HOT_UUID,
                    "application/x-eml+xml;version=2.3;type=ContinuousColorMap",
                    "hot",
                ),
            },
            "Opacity": 0.85,
        },
        # Water Saturation → plasma, linear [0, 1], full opacity
        {
            "TargetObject": _data_object_ref(
                PROP_WSAT,
                "application/x-resqml+xml;version=2.2;type=ContinuousProperty",
                "Water Saturation (Gas Zone)",
            ),
            "ColorInformation": {
                "UseLogarithmicMapping": False,
                "UseReverseMapping": False,
                "MinIndex": 0.0,
                "MaxIndex": 1.0,
                "ColorMap": _data_object_ref(
                    CMAP_PLASMA_UUID,
                    "application/x-eml+xml;version=2.3;type=ContinuousColorMap",
                    "plasma",
                ),
            },
        },
        # Carbonate Volume Fraction → viridis, linear [0, 1]
        {
            "TargetObject": _data_object_ref(
                PROP_PORO,
                "application/x-resqml+xml;version=2.2;type=ContinuousProperty",
                "Carbonate Volume Fraction",
            ),
            "ColorInformation": {
                "UseLogarithmicMapping": False,
                "UseReverseMapping": False,
                "MinIndex": 0.0,
                "MaxIndex": 1.0,
                "ColorMap": _data_object_ref(
                    CMAP_VIRIDIS_UUID,
                    "application/x-eml+xml;version=2.3;type=ContinuousColorMap",
                    "viridis",
                ),
            },
            "DefaultColor": {"Hue": 200, "Saturation": 0.7, "Value": 0.9, "Alpha": 1.0},
        },
    ]

    return {
        "Uuid": GIS_UUID,
        "SchemaVersion": "2.3",
        "Citation": _citation(
            "Drogon Property Visualization",
            "GraphicalInformationSet: color scales, log mapping, opacity for "
            "Drogon RESQML 2.2 ContinuousProperty objects on IjkGrid.",
        ),
        "GraphicalInformation": gi_entries,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Color map definitions (plasma, viridis, hot – simplified 5-stop versions)
# ═══════════════════════════════════════════════════════════════════════════

PLASMA_STOPS = [
    {"index": 0.0,  "hue": 270, "sat": 0.9, "val": 0.3},
    {"index": 0.25, "hue": 290, "sat": 0.85, "val": 0.6},
    {"index": 0.5,  "hue": 330, "sat": 0.8,  "val": 0.8},
    {"index": 0.75, "hue": 30,  "sat": 0.9,  "val": 0.95},
    {"index": 1.0,  "hue": 55,  "sat": 0.95, "val": 0.98},
]

VIRIDIS_STOPS = [
    {"index": 0.0,  "hue": 280, "sat": 0.7, "val": 0.3},
    {"index": 0.25, "hue": 230, "sat": 0.6, "val": 0.55},
    {"index": 0.5,  "hue": 175, "sat": 0.7, "val": 0.65},
    {"index": 0.75, "hue": 100, "sat": 0.8, "val": 0.78},
    {"index": 1.0,  "hue": 65,  "sat": 0.9, "val": 0.93},
]

HOT_STOPS = [
    {"index": 0.0,  "hue": 0,   "sat": 1.0, "val": 0.1},
    {"index": 0.25, "hue": 0,   "sat": 1.0, "val": 0.6},
    {"index": 0.5,  "hue": 20,  "sat": 1.0, "val": 0.85},
    {"index": 0.75, "hue": 40,  "sat": 0.95, "val": 0.95},
    {"index": 1.0,  "hue": 55,  "sat": 0.1,  "val": 1.0},
]


# ═══════════════════════════════════════════════════════════════════════════
# RDDMS REST transactional push
# ═══════════════════════════════════════════════════════════════════════════

def push_to_rddms(token: str, host: str, partition: str,
                   objects: list[tuple[str, dict]], dry_run: bool = False):
    """Push EML objects to RDDMS via begin→put→commit.

    objects: list of (type_name, json_dict) e.g. ("eml23.GraphicalInformationSet", {...})
    """
    base = f"https://{host}/api/reservoir-ddms/v2"
    ds_enc = urllib.parse.quote(DATASPACE, safe="")
    headers = {
        "Authorization": f"Bearer {token}",
        "data-partition-id": partition,
        "Content-Type": "application/json",
    }

    if dry_run:
        print(f"\n  [DRY RUN] Would push {len(objects)} objects to {DATASPACE}")
        for typ, obj in objects:
            print(f"    • {typ} ({obj.get('Uuid', '?')}): "
                  f"{(obj.get('Citation') or {}).get('Title', '?')}")
        return

    print(f"\n  Pushing {len(objects)} objects to {DATASPACE}...")

    # 1. Begin transaction
    tx_url = f"{base}/dataspaces/{ds_enc}/transactions"
    r = httpx.post(tx_url, headers=headers, timeout=30)
    if r.status_code >= 400:
        print(f"  ✗ begin_transaction: {r.status_code} {r.text[:300]}")
        # Try without transaction (some RDDMS versions accept direct PUT)
        print(f"  Trying direct PUT (no transaction)...")
        _direct_put(base, ds_enc, headers, objects)
        return
    tx_id = r.text.strip().strip('"')
    print(f"  Transaction: {tx_id[:12]}...")

    # 2. PUT resources (one type at a time)
    for typ, obj in objects:
        url = f"{base}/dataspaces/{ds_enc}/resources/{typ}"
        r = httpx.put(url, headers=headers, json=[obj],
                      params={"transactionId": tx_id}, timeout=60)
        status = "✓" if r.status_code < 400 else "✗"
        title = (obj.get("Citation") or {}).get("Title", "?")
        print(f"  {status} PUT {typ} ({title}): {r.status_code}")
        if r.status_code >= 400:
            print(f"    {r.text[:300]}")

    # 3. Commit
    commit_url = f"{base}/dataspaces/{ds_enc}/transactions/{tx_id}"
    r = httpx.put(commit_url, headers=headers, timeout=120)
    if r.status_code < 400:
        print(f"  ✓ Committed")
    else:
        print(f"  ✗ Commit failed: {r.status_code} {r.text[:300]}")


def _direct_put(base: str, ds_enc: str, headers: dict, objects: list):
    """Fallback: PUT objects directly without a transaction."""
    for typ, obj in objects:
        url = f"{base}/dataspaces/{ds_enc}/resources/{typ}"
        r = httpx.put(url, headers=headers, json=[obj], timeout=60)
        status = "✓" if r.status_code < 400 else "✗"
        title = (obj.get("Citation") or {}).get("Title", "?")
        print(f"  {status} PUT {typ} ({title}): {r.status_code}")
        if r.status_code >= 400:
            print(f"    {r.text[:300]}")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="Push GraphicalInformationSet + ColorMaps to RDDMS for drogon22")
    ap.add_argument("instance", help="Target instance (interop, swedev, interop)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would be pushed, no remote changes")
    ap.add_argument("--save-json", action="store_true",
                    help="Also save the EML objects to JSON files locally")
    args = ap.parse_args()

    # Load instance config
    inst = load_instance(args.instance)
    host = inst["host"].replace("https://", "").replace("http://", "").rstrip("/")
    partition = inst.get("partition") or "opendes"

    print(f"{'═' * 60}")
    print(f"  Push GraphicalInformationSet → {args.instance}")
    print(f"  Host:      {host}")
    print(f"  Dataspace: {DATASPACE}")
    print(f"  Partition: {partition}")
    print(f"{'═' * 60}")

    # Build EML objects
    cmap_plasma = build_continuous_colormap(CMAP_PLASMA_UUID, "plasma", PLASMA_STOPS)
    cmap_viridis = build_continuous_colormap(CMAP_VIRIDIS_UUID, "viridis", VIRIDIS_STOPS)
    cmap_hot = build_continuous_colormap(CMAP_HOT_UUID, "hot", HOT_STOPS)
    gis = build_graphical_information_set()

    objects = [
        ("eml23.ContinuousColorMap", cmap_plasma),
        ("eml23.ContinuousColorMap", cmap_viridis),
        ("eml23.ContinuousColorMap", cmap_hot),
        ("eml23.GraphicalInformationSet", gis),
    ]

    print(f"\n  Objects to push:")
    for typ, obj in objects:
        title = (obj.get("Citation") or {}).get("Title", "?")
        print(f"    • {typ}: {title} ({obj['Uuid']})")

    if args.save_json:
        out_dir = SCRIPT_DIR / "graphical_info"
        out_dir.mkdir(exist_ok=True)
        for typ, obj in objects:
            fname = f"{typ}_{obj['Uuid']}.json"
            (out_dir / fname).write_text(json.dumps(obj, indent=2))
            print(f"  Saved: {fname}")

    # Auth + push
    if not args.dry_run:
        token = get_token(args.instance, verbose=True)
        if not token:
            sys.exit(f"Failed to authenticate to {args.instance}")
    else:
        token = "dry-run"

    push_to_rddms(token, host, partition, objects, dry_run=args.dry_run)

    print(f"\n{'═' * 60}")
    print(f"  Done. Properties with graphical info:")
    print(f"    • Oil Saturation     → plasma, linear [0-1]")
    print(f"    • Gas Saturation     → viridis reversed, linear [0-1]")
    print(f"    • Oil Bulk Volume    → hot, log scale [1-12938]")
    print(f"    • Water Saturation   → plasma, linear [0-1]")
    print(f"    • Carbonate Vol Frac → viridis, linear [0-1]")
    print(f"  Test in ORES: select a ContinuousProperty → 3D view")
    print(f"{'═' * 60}")


if __name__ == "__main__":
    main()
