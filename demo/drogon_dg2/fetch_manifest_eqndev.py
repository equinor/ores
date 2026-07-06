#!/usr/bin/env python3
"""
fetch_manifest_eqndev.py – Call the RDDMS manifest builder on eqndev
for the maap/drogon_dg dataspace and save the result for review.

Usage:
  python demo/drogon_dg2/fetch_manifest_eqndev.py
  python demo/drogon_dg2/fetch_manifest_eqndev.py --types "resqml20.*"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    sys.exit("pip install httpx")

SCRIPT_DIR = Path(__file__).resolve().parent
DEMO_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(DEMO_DIR))

from _auth import get_token, load_instance  # noqa: E402

DATASPACE = "maap/drogon_dg"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataspace", default=DATASPACE)
    ap.add_argument("--types", default=None, help="Comma-separated type patterns, e.g. 'resqml20.*'")
    ap.add_argument("-o", "--output", default=str(SCRIPT_DIR / "manifest_rddms_dg2.json"))
    args = ap.parse_args()

    inst = load_instance("eqndev")
    host = inst["host"]
    partition = inst.get("partition", "dev")

    print(f"Instance: eqndev ({host})")
    print(f"Dataspace: {args.dataspace}")

    token = get_token("eqndev", verbose=True)
    headers = {
        "Authorization": f"Bearer {token}",
        "data-partition-id": partition,
        "Content-Type": "application/json",
    }

    # Step 1: List resources in the dataspace
    ds_enc = args.dataspace.replace("/", "%2F")
    rddms_base = f"{host}/api/reservoir-ddms/v2"

    print(f"\n── Resources in {args.dataspace} ──")
    r = httpx.get(f"{rddms_base}/dataspaces/{ds_enc}/resources",
                  headers=headers, timeout=30)
    if r.is_success:
        resources = r.json()
        if isinstance(resources, list):
            for t in resources:
                print(f"  {t.get('name', t.get('type', '?'))}: {t.get('count', '?')}")
        else:
            print(f"  {json.dumps(resources)[:500]}")
    else:
        print(f"  ⚠ {r.status_code}: {r.text[:300]}")

    # Step 1b: Get detailed resource list (individual objects with names)
    print(f"\n── Detailed resources (Grid2d + IjkGrid) ──")
    for rtype in ["resqml20.obj_Grid2dRepresentation", "resqml20.obj_IjkGridRepresentation"]:
        r2 = httpx.get(f"{rddms_base}/dataspaces/{ds_enc}/resources/{rtype}",
                       headers=headers, timeout=60)
        if r2.is_success:
            objs = r2.json()
            print(f"\n  {rtype} ({len(objs)} objects):")
            for obj in objs[:60]:
                name = obj.get("name", obj.get("title", "?"))
                uri = obj.get("uri", "")
                uuid = uri.split("(")[-1].rstrip(")") if "(" in uri else ""
                custom = obj.get("customData", {})
                print(f"    [{uuid[:8]}] {name}")
                if custom:
                    print(f"             custom: {json.dumps(dict(custom))[:120]}")
        else:
            print(f"  {rtype}: {r2.status_code} {r2.text[:100]}")

    # Step 2: Build manifest via local rddms (if reachable) or skip
    print(f"\n── Building manifest ──")
    url = f"{rddms_base}/manifests/build"
    body = {
        "uris": [f"eml:///dataspace('{args.dataspace}')"],
        "createMissingReferences": True,
    }
    if args.types:
        body["typePatterns"] = [t.strip() for t in args.types.split(",")]

    print(f"  POST {url}")
    r = httpx.post(url, json=body, headers=headers, timeout=180)
    if r.status_code >= 300:
        print(f"  ⚠ Remote manifest builder failed: {r.status_code}: {r.text[:300]}")
        print(f"  Trying with local RDDMS REST (start with docker compose)...")
        # Try local rddms
        local_url = "http://localhost:3000/api/reservoir-ddms/v2/manifests/build"
        local_headers = {**headers}
        try:
            r = httpx.post(local_url, json=body, headers=local_headers, timeout=180)
            if r.status_code >= 300:
                print(f"  ⚠ Local also failed: {r.status_code}")
                print(f"  Will use resource listing only for review.")
                manifest = None
            else:
                manifest = r.json()
        except Exception as e:
            print(f"  ⚠ Local not reachable: {e}")
            manifest = None
    else:
        manifest = r.json()

    # Step 3: Summary
    if manifest is None:
        print("\n── No manifest generated, review resource names above ──")
        return

    data = manifest.get("Data", {})
    wpcs = data.get("WorkProductComponents", [])
    refs = manifest.get("ReferenceData", [])
    masters = manifest.get("MasterData", [])
    datasets = data.get("Datasets", [])

    print(f"\n── Manifest Summary ──")
    print(f"  WorkProductComponents: {len(wpcs)}")
    print(f"  ReferenceData:         {len(refs)}")
    print(f"  MasterData:            {len(masters)}")
    print(f"  Datasets:              {len(datasets)}")

    # Group WPCs by kind
    by_kind: dict[str, list] = {}
    for wpc in wpcs:
        kind = wpc.get("kind", "?").split("--")[-1].split(":")[0] if "--" in wpc.get("kind", "") else wpc.get("kind", "?")
        by_kind.setdefault(kind, []).append(wpc)

    print(f"\n── WPC by kind ──")
    for kind, items in sorted(by_kind.items()):
        print(f"\n  {kind} ({len(items)}):")
        for wpc in items:
            d = wpc.get("data", {})
            name = d.get("Name", d.get("name", "(no Name)"))
            desc = d.get("Description", "")[:60]
            spatial = "✓spatial" if d.get("SpatialArea") or d.get("SpatialPoint") else "✗spatial"
            ni = d.get("NodeCountOnIAxis")
            nj = d.get("NodeCountOnJAxis")
            grid = f" [{ni}x{nj}]" if ni else ""
            origin = ""
            if d.get("BinGridOriginEasting") or d.get("OriginEasting"):
                e = d.get("BinGridOriginEasting") or d.get("OriginEasting")
                n = d.get("BinGridOriginNorthing") or d.get("OriginNorthing")
                origin = f" origin=({e},{n})"
            ddms = d.get("DDMSDatasets", [])
            ddms_str = f" ddms={ddms[0].split('/')[-1][:40]}" if ddms else ""
            print(f"    {name}{grid} {spatial}{origin}{ddms_str}")
            if desc:
                print(f"      desc: {desc}")

    # Step 4: Save
    out = Path(args.output)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n── Saved to {out} ({out.stat().st_size // 1024} KB) ──")


if __name__ == "__main__":
    main()
