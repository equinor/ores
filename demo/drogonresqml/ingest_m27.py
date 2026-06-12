#!/usr/bin/env python3
"""
ingest_m27.py – Ingest the curated Drogon EPC + the locally-generated M27
manifest into an OSDU instance (RDDMS + catalog).

Unlike ingest_drogon.py (which loads the legacy manifest_full_opendes.json and
the upstream remote manifest builder), this driver uses the locally-generated
M27 manifest (manifest_drogon_m27.json), patches ACL/legal across ALL sections
(Data + MasterData + ReferenceData), and pushes via the Osdu_ingest workflow.

Pipeline per instance:
  1. Authenticate
  2. Purge maap/drogon dataspace (openETPServer space --delete)   [--no-purge to skip]
  3. Create dataspace
  4. Import curated drogon.epc via ETP
  5. Verify import
  6. Load + repartition + patch M27 manifest
  7. Push manifest to catalog (Osdu_ingest workflow)

Usage:
  python demo/drogonresqml/ingest_m27.py eqndev
  python demo/drogonresqml/ingest_m27.py interop
  python demo/drogonresqml/ingest_m27.py eqndev --no-purge
  python demo/drogonresqml/ingest_m27.py eqndev --skip-etp   # catalog only
  python demo/drogonresqml/ingest_m27.py eqndev --dry-run    # patch + save, no remote writes
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from ingest_drogon import (  # noqa: E402
    InstanceConfig,
    EPC_FILE,
    IMAGE_SSL,
    authenticate,
    create_dataspace,
    import_epc,
    verify_import,
    push_via_workflow,
    _repartition,
)

MANIFEST_FILE = SCRIPT_DIR / "manifest_drogon_m27.json"


def purge_dataspace(token: str, cfg: InstanceConfig) -> bool:
    """Delete the entire dataspace (and all its contents).

    REST DELETE /dataspaces/{ds} is tried first (works with owner/data entitlement
    even when the ETP DeleteDataspaces op is 403). Falls back to openETPServer.
    """
    print(f"\n=== Purge dataspace ({cfg.dataspace}) ===")
    ds_enc = cfg.dataspace.replace("/", "%2F")
    try:
        r = httpx.delete(f"{cfg.base_rddms}/dataspaces/{ds_enc}",
                         headers=cfg.headers(token), timeout=180)
        if r.status_code in (200, 202, 204):
            print(f"  ✓ Purged dataspace {cfg.dataspace} via REST ({r.status_code})")
            return True
        if r.status_code == 404:
            print(f"  ✓ Dataspace {cfg.dataspace} did not exist (404)")
            return True
        print(f"  ⚠ REST delete {r.status_code}: {r.text[:200]} — trying ETP...")
    except Exception as e:
        print(f"  ⚠ REST delete error ({e}) — trying ETP...")

    tok_file = SCRIPT_DIR / ".etp_token"
    tok_file.write_text(token)
    inner = (
        f"export JWT=$(cat /data/.etp_token) && "
        f"/bin/openETPServer space "
        f"--server-url {cfg.etp_url} "
        f"--data-partition-id {cfg.partition} "
        f"--auth bearer --jwt-token $JWT "
        f"-s {cfg.dataspace} --delete"
    )
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{SCRIPT_DIR}:/data",
        "--entrypoint=sh", IMAGE_SSL, "-c", inner,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    tok_file.unlink(missing_ok=True)
    combined = result.stdout + result.stderr

    if result.returncode == 0:
        print(f"  ✓ Purged dataspace {cfg.dataspace} via ETP")
        return True
    if "not exist" in combined.lower() or "not found" in combined.lower():
        print(f"  ✓ Dataspace {cfg.dataspace} did not exist (nothing to purge)")
        return True
    print(f"  ✗ Purge failed (rc={result.returncode})")
    print(f"    {combined[-400:]}")
    return False


def patch_all_sections(manifest: dict, cfg: InstanceConfig) -> dict:
    """Repartition + set ACL/legal on every record in Data, MasterData, ReferenceData."""
    print(f"\n=== Patch manifest ({cfg.name}) ===")

    # 1. Repartition record IDs + cross-references (opendes: -> {partition}:)
    manifest = _repartition(manifest, cfg)

    # 1b. Rewrite data-internal group domains (e.g. CollaborationProject
    #     DefaultWIPACL/ProjectContributorACL: @opendes.dataservices -> @{partition}.dataservices)
    if cfg.partition != "opendes":
        old_dom = "@opendes.dataservices"
        new_dom = f"@{cfg.partition}.dataservices"

        def _dom(o):
            if isinstance(o, str):
                return o.replace(old_dom, new_dom)
            if isinstance(o, list):
                return [_dom(v) for v in o]
            if isinstance(o, dict):
                return {k: _dom(v) for k, v in o.items()}
            return o

        manifest = _dom(manifest)

    acl = {"owners": cfg.owners, "viewers": cfg.viewers}
    legal = {
        "legaltags": [cfg.legal_tag],
        "otherRelevantDataCountries": cfg.countries,
        "status": "compliant",
    }

    def _records():
        data = manifest.get("Data", {})
        for v in data.values():
            if isinstance(v, list):
                yield from v
        for key in ("MasterData", "ReferenceData"):
            sec = manifest.get(key)
            if isinstance(sec, list):
                yield from sec

    n = 0
    for rec in _records():
        rec["acl"] = {"owners": list(acl["owners"]), "viewers": list(acl["viewers"])}
        rec["legal"] = {
            "legaltags": list(legal["legaltags"]),
            "otherRelevantDataCountries": list(legal["otherRelevantDataCountries"]),
            "status": legal["status"],
        }
        n += 1

    print(f"  Patched {n} records → partition={cfg.partition}, "
          f"legal={cfg.legal_tag}, countries={cfg.countries}")
    return manifest


def counts(manifest: dict) -> str:
    data = manifest.get("Data", {})
    parts = [f"{k}={len(v)}" for k, v in data.items() if isinstance(v, list)]
    parts.append(f"MasterData={len(manifest.get('MasterData', []))}")
    parts.append(f"ReferenceData={len(manifest.get('ReferenceData', []))}")
    return ", ".join(parts)


def main():
    ap = argparse.ArgumentParser(description="Ingest Drogon EPC + M27 manifest")
    ap.add_argument("instance", choices=["interop", "eqndev"])
    ap.add_argument("--no-purge", action="store_true", help="Skip dataspace purge")
    ap.add_argument("--skip-etp", action="store_true", help="Skip EPC import (catalog only)")
    ap.add_argument("--dry-run", action="store_true", help="Patch + save, no remote writes")
    ap.add_argument("--save-only", action="store_true", help="Save patched manifest, no push")
    args = ap.parse_args()

    cfg = InstanceConfig(args.instance)
    if not MANIFEST_FILE.exists():
        sys.exit(f"Missing {MANIFEST_FILE}")

    print("═" * 64)
    print(f"  Drogon M27 → {cfg.name} ({cfg.host})")
    print(f"  Dataspace:  {cfg.dataspace}")
    print(f"  Partition:  {cfg.partition}")
    print(f"  Legal:      {cfg.legal_tag}")
    print(f"  Manifest:   {MANIFEST_FILE.name}")
    print(f"  EPC:        {EPC_FILE.name}")
    print(f"  Purge:      {not args.no_purge}")
    print("═" * 64)

    manifest = json.loads(MANIFEST_FILE.read_text())
    print(f"\nLoaded manifest: {counts(manifest)}")

    token = None
    if not args.dry_run:
        token = authenticate(cfg)

    # ── Purge + import EPC ──
    if not args.dry_run and not args.skip_etp:
        if not args.no_purge:
            purge_dataspace(token, cfg)
        create_dataspace(token, cfg)
        if not import_epc(token, cfg):
            print("  ⚠ EPC import failed — continuing to catalog push")
        verify_import(token, cfg)

    # ── Patch manifest ──
    manifest = patch_all_sections(manifest, cfg)
    out = SCRIPT_DIR / f"manifest_drogon_m27_{cfg.name}.json"
    out.write_text(json.dumps(manifest, indent=2))
    print(f"  Saved patched manifest → {out.name} ({out.stat().st_size/1024:.0f} KB)")

    if args.dry_run or args.save_only:
        print(f"\nDone (dry-run/save-only, not pushed). {counts(manifest)}")
        return

    # ── Push to catalog ──
    print(f"\n=== Push manifest to catalog ({cfg.name}) ===")
    ok = push_via_workflow(token, cfg, manifest)
    if ok:
        print(f"\n{'═' * 64}\n  ✓ M27 manifest indexed in {cfg.name} catalog\n  {counts(manifest)}")
    else:
        print("\n  ⚠ Workflow push failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
