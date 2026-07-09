#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_manifest.py – Generic RDDMS manifest builder for any dataspace.

Uses the local OpenETP client (~/rddms on localhost:3000) to introspect an
RDDMS dataspace and generate OSDU catalog records, then pushes them to the
remote OSDU catalog via Storage API.

No Docker required. No .env file in this script.
Connection config (host, partition, port) is read from ~/rddms/config.user.env.

Token sources (tried in order):
  1. --token CLI argument       (paste a token directly)
  2. OSDU_TOKEN env var         (export OSDU_TOKEN=eyJ...)
  3. ores k8s/secret.yaml       (if running inside the ores repo)

═══════════════════════════════════════════════════════════════════════════
Quick start – complete command sequence
═══════════════════════════════════════════════════════════════════════════

  # 1. Configure ~/rddms/config.user.env (one-time setup):
  #    RDMS_ETP_HOST=equinorswedev.energy.azure.com
  #    RDMS_ETP_PORT=443
  #    RDMS_ETP_PROTOCOL=wss
  #    RDMS_ETP_PATH=/api/reservoir-ddms-etp/v2
  #    RDMS_REST_PORT=3000
  #    RDMS_REST_ROOT_PATH=/api/reservoir-ddms/v2/
  #    RDMS_DATA_PARTITION_MODE=single
  #    RDMS_DATA_PARTITION_ID=dev
  #    RDMS_OSDU_URL=https://equinorswedev.energy.azure.com
  #    RDMS_SSL_VERIFY=false

  # 2. Build the RDDMS client (one-time, after git clone):
  cd ~/rddms && npm install && npm run build

  # 3. Start the local OpenETP client (no Docker):
  cd ~/rddms && npx env-cmd --silent -f config.user.env --no-override \\
    -- npx env-cmd -f config.default.env --no-override \\
    -- node dist/src/lib/restApi/RestServer.js &

  # 4a. Run – build manifest & push to catalog (full dataspace):
  python build_manifest.py maap/omegas --token eyJ...

  # 4b. Run – build manifest only, save to file:
  python build_manifest.py maap/omegas --no-push -o manifest.json --token eyJ...

  # 4c. Run – specific RESQML objects only:
  python build_manifest.py maap/omegas --uris \\
      "eml:///dataspace('maap/omegas')/resqml22.Grid2dRepresentation(uuid=...)" \\
      --token eyJ...

═══════════════════════════════════════════════════════════════════════════
Token options
═══════════════════════════════════════════════════════════════════════════

  # Option A: paste token directly
  python build_manifest.py maap/omegas --token eyJ...

  # Option B: set env var (useful for repeated runs)
  export OSDU_TOKEN=eyJ...
  python build_manifest.py maap/omegas

  # Option C: auto-mint via ores k8s/secret.yaml (if available)
  python build_manifest.py maap/omegas

═══════════════════════════════════════════════════════════════════════════

Usage:
  python build_manifest.py <dataspace> [options]

  python build_manifest.py maap/omegas                        # full dataspace → catalog
  python build_manifest.py user/my-project --dry-run          # preview, no push
  python build_manifest.py maap/omegas -o manifest.json       # save manifest to file
  python build_manifest.py maap/omegas --no-push              # build only, don't push
  python build_manifest.py maap/omegas --rddms-dir ~/rddms2   # different client install
  python build_manifest.py maap/omegas --port 4000            # different port
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import httpx
except ImportError:
    sys.exit("Missing httpx – pip install httpx")


# ═══════════════════════════════════════════════════════════════════════════
# Config: read from ~/rddms/config.user.env
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_RDDMS_DIR = Path.home() / "rddms"
BATCH_SIZE = 20          # Storage API batch limit


def parse_env_file(path: Path) -> Dict[str, str]:
    """Parse a KEY=VALUE env file (config.user.env or config.default.env)."""
    vals: Dict[str, str] = {}
    if not path.exists():
        return vals
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k:
            vals[k] = v
    return vals


def load_rddms_config(rddms_dir: Path) -> Dict[str, str]:
    """Load connection config from the RDDMS client directory.

    Merges config.default.env (defaults) with config.user.env (overrides).
    Returns dict with keys like RDMS_ETP_HOST, RDMS_DATA_PARTITION_ID, etc.
    """
    defaults = parse_env_file(rddms_dir / "config.default.env")
    user = parse_env_file(rddms_dir / "config.user.env")
    merged = {**defaults, **user}
    return merged


def make_headers(token: str, partition: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "data-partition-id": partition,
        "Content-Type": "application/json",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Token resolution
# ═══════════════════════════════════════════════════════════════════════════

def resolve_token(cli_token: Optional[str] = None, instance: str = "eqndev") -> str:
    """Get a Bearer token from the first available source.

    Order: --token arg → OSDU_TOKEN env var → ores k8s/secret.yaml fallback.
    """
    # 1. CLI argument
    if cli_token:
        print("  ✓ Using token from --token argument")
        return cli_token

    # 2. Environment variable
    env_token = os.environ.get("OSDU_TOKEN", "").strip()
    if env_token:
        print("  ✓ Using token from OSDU_TOKEN env var")
        return env_token

    # 3. ores k8s fallback (if _auth.py is available)
    try:
        script_dir = Path(__file__).resolve().parent
        sys.path.insert(0, str(script_dir))
        from _auth import get_token  # noqa: E402
        print("  Minting token via ores k8s/secret.yaml...")
        token = get_token(instance, verbose=True)
        if token:
            return token
    except (ImportError, SystemExit, RuntimeError) as e:
        pass

    # Nothing worked
    print("  ✗ No token available. Provide one of:")
    print("    --token eyJ...                  (paste a token)")
    print("    export OSDU_TOKEN=eyJ...        (env var)")
    print("    k8s/secret.yaml credentials     (ores repo fallback)")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════
# Step 1: Check local client health
# ═══════════════════════════════════════════════════════════════════════════

def check_local_client(base_url: str) -> bool:
    """Verify the local OpenETP client is running."""
    try:
        r = httpx.get(f"{base_url}/health/info", timeout=5)
        if r.is_success:
            info = r.json()
            version = info.get("version", info.get("serverVersion", "?"))
            print(f"  ✓ Local client running ({version})")
            return True
        print(f"  ✗ Local client returned {r.status_code}")
        return False
    except httpx.ConnectError:
        print(f"  ✗ Cannot connect to local client at {base_url}")
        print(f"    Start it:  cd ~/rddms && npm run start")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# Step 2: Build manifest via local client
# ═══════════════════════════════════════════════════════════════════════════

def build_manifest(
    base_url: str,
    headers: dict,
    dataspace: str,
    uris: Optional[List[str]] = None,
) -> Optional[dict]:
    """Call manifests/build on the local OpenETP client.

    If uris is provided, builds for those specific RESQML objects.
    Otherwise builds for the entire dataspace.
    """
    if uris:
        body = {"uris": uris, "createMissingReferences": True}
        print(f"  Building manifest for {len(uris)} specific URI(s)...")
    else:
        dataspace_uri = f"eml:///dataspace('{dataspace}')"
        body = {"uris": [dataspace_uri], "createMissingReferences": True}
        print(f"  Building manifest for entire dataspace: {dataspace}")

    url = f"{base_url}/manifests/build"
    print(f"  POST {url}")

    try:
        r = httpx.post(url, headers=headers, json=body, timeout=180)
    except httpx.ConnectError:
        print("  ✗ Connection refused – is the local client running?")
        print("    Start it:  cd ~/rddms && npm run start")
        return None
    except httpx.TimeoutException:
        print("  ✗ Timeout (180s) – dataspace may have many objects")
        print("    Try --uris to build for specific objects instead")
        return None

    if r.status_code >= 400:
        print(f"  ✗ manifests/build failed: {r.status_code}")
        err_text = r.text[:600]
        print(f"    {err_text}")
        if r.status_code == 500:
            print("    Note: some RESQML types are not supported by the builder.")
            print("    Try --uris to select specific objects.")
        return None

    manifest = r.json()
    if not manifest:
        print("  ✗ Empty response from manifests/build")
        return None

    return manifest


# ═══════════════════════════════════════════════════════════════════════════
# Step 3: Extract records from manifest response
# ═══════════════════════════════════════════════════════════════════════════

def extract_records(manifest: dict) -> List[Dict[str, Any]]:
    """Extract all ingestable records from the manifest response."""
    records: List[Dict[str, Any]] = []
    # The manifest builder returns records in various sections
    for section in ("WorkProductComponents", "Datasets", "ReferenceData", "MasterData"):
        items = manifest.get(section) or manifest.get("Data", {}).get(section) or []
        if isinstance(items, list):
            records.extend(items)
            if items:
                print(f"    {section}: {len(items)} records")
    return records


# ═══════════════════════════════════════════════════════════════════════════
# Step 4: Stamp ACL/legal and push to catalog
# ═══════════════════════════════════════════════════════════════════════════

def stamp_acl_legal(
    records: List[Dict[str, Any]],
    owners: List[str],
    viewers: List[str],
    legal_tag: str,
    countries: List[str],
) -> None:
    """Ensure every record has proper ACL and legal tags."""
    for rec in records:
        if "acl" not in rec:
            rec["acl"] = {}
        rec["acl"]["owners"] = owners
        rec["acl"]["viewers"] = viewers
        if "legal" not in rec:
            rec["legal"] = {}
        rec["legal"]["legaltags"] = [legal_tag]
        rec["legal"]["otherRelevantDataCountries"] = countries


def push_to_catalog(
    records: List[Dict[str, Any]],
    storage_url: str,
    headers: dict,
) -> int:
    """Push records to OSDU Storage API in batches. Returns count of successes."""
    total_ok = 0
    n_batches = (len(records) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        try:
            r = httpx.put(
                f"{storage_url}/records",
                headers=headers,
                json=batch,
                timeout=60,
            )
        except httpx.TimeoutException:
            print(f"    ✗ Batch {batch_num}/{n_batches} timed out")
            continue

        if r.status_code in (200, 201):
            result = r.json()
            count = result.get("recordCount", len(batch))
            total_ok += count
            print(f"    ✓ Batch {batch_num}/{n_batches}: {count} records")
        else:
            print(f"    ✗ Batch {batch_num}/{n_batches} failed: {r.status_code}")
            print(f"      {r.text[:300]}")

    return total_ok


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="Build OSDU manifest from any RDDMS dataspace via local OpenETP client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s maap/omegas                       # full dataspace → catalog
  %(prog)s user/project --dry-run            # preview, no push
  %(prog)s maap/omegas --output out.json     # save manifest to file
  %(prog)s maap/omegas --uris "eml:///..."   # specific objects only
  %(prog)s maap/omegas --no-push             # build only, don't push
  %(prog)s maap/omegas --token eyJ...        # provide token directly

Token sources (tried in order):
  1. --token eyJ...              (paste a token)
  2. OSDU_TOKEN env var          (export OSDU_TOKEN=eyJ...)
  3. ores k8s/secret.yaml        (fallback if _auth.py available)

Prerequisites:
  1. cd ~/rddms && npm run start   (local OpenETP client)
  2. ~/rddms/config.user.env configured (host, partition)
""",
    )
    ap.add_argument("dataspace", help="RDDMS dataspace path (e.g. maap/omegas, user/project)")
    ap.add_argument("--token", metavar="TOKEN",
                    help="Bearer token (or set OSDU_TOKEN env var)")
    ap.add_argument("--instance", default="eqndev",
                    help="OSDU instance name for k8s fallback auth (default: eqndev)")
    ap.add_argument("--rddms-dir", metavar="DIR", default=str(DEFAULT_RDDMS_DIR),
                    help=f"Path to local RDDMS client (default: {DEFAULT_RDDMS_DIR})")
    ap.add_argument("--port", type=int, default=None,
                    help="Local client port (default: from config.user.env / 3000)")
    ap.add_argument("--uris", nargs="+", metavar="URI",
                    help="Build for specific RESQML URIs instead of entire dataspace")
    ap.add_argument("--output", "-o", metavar="FILE",
                    help="Save raw manifest JSON to file")
    ap.add_argument("--no-push", action="store_true",
                    help="Build manifest but don't push to catalog")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would happen without making any remote changes")
    args = ap.parse_args()

    dataspace = args.dataspace
    rddms_dir = Path(args.rddms_dir)

    # ── Load RDDMS client config ─────────────────────────────────────────
    config_path = rddms_dir / "config.user.env"
    if not config_path.exists():
        print(f"  ✗ RDDMS config not found: {config_path}")
        print(f"    Ensure ~/rddms/config.user.env exists and is configured.")
        print(f"    Or use --rddms-dir to point to your RDDMS client directory.")
        sys.exit(1)

    rddms_cfg = load_rddms_config(rddms_dir)
    host = rddms_cfg.get("RDMS_ETP_HOST", "")
    partition = rddms_cfg.get("RDMS_DATA_PARTITION_ID", "opendes")
    osdu_url = rddms_cfg.get("RDMS_OSDU_URL", "")
    port = args.port or int(rddms_cfg.get("RDMS_REST_PORT", "3000"))
    api_root = rddms_cfg.get("RDMS_REST_ROOT_PATH", "/api/reservoir-ddms/v2/").rstrip("/")

    if not host:
        print(f"  ✗ RDMS_ETP_HOST not set in {config_path}")
        sys.exit(1)
    if not osdu_url:
        osdu_url = f"https://{host}"

    local_base = f"http://localhost:{port}{api_root}"

    # Derive ACL defaults from partition
    owners = [f"data.default.owners@{partition}.dataservices.energy"]
    viewers = [f"data.default.viewers@{partition}.dataservices.energy"]
    legal_tag = f"{partition}-default-legal-tag"
    countries = ["NO"]

    storage_url = f"{osdu_url}/api/storage/v2"

    print(f"╔══════════════════════════════════════════════════════╗")
    print(f"║  RDDMS Manifest Builder                             ║")
    print(f"╠══════════════════════════════════════════════════════╣")
    print(f"║  Dataspace:  {dataspace:<40s}║")
    print(f"║  RDDMS host: {host:<40s}║")
    print(f"║  Partition:  {partition:<40s}║")
    print(f"║  Local port: {port:<40d}║")
    print(f"║  OSDU URL:   {osdu_url:<40s}║")
    print(f"╚══════════════════════════════════════════════════════╝")

    # ── Step 1: Get token ────────────────────────────────────────────────
    print(f"\n═══ Authenticate ═══")
    if args.dry_run:
        print("  [dry-run] Skipping auth")
        token = "DRY_RUN_TOKEN"
    else:
        token = resolve_token(cli_token=args.token, instance=args.instance)

    headers = make_headers(token, partition)

    # ── Step 2: Check local client ───────────────────────────────────────
    print(f"\n═══ Local OpenETP Client (port {port}) ═══")
    if not args.dry_run:
        if not check_local_client(local_base):
            sys.exit(1)
    else:
        print(f"  [dry-run] Would check localhost:{port}")

    # ── Step 3: Build manifest ───────────────────────────────────────────
    print(f"\n═══ Build Manifest ═══")
    if args.dry_run:
        uri_desc = f"{len(args.uris)} URIs" if args.uris else f"dataspace '{dataspace}'"
        print(f"  [dry-run] Would call manifests/build for {uri_desc}")
        print(f"  [dry-run] POST {local_base}/manifests/build")
        return

    t0 = time.time()
    manifest = build_manifest(local_base, headers, dataspace, uris=args.uris)
    elapsed = time.time() - t0

    if manifest is None:
        sys.exit(1)

    print(f"  Built in {elapsed:.1f}s")

    # ── Step 4: Save manifest if requested ───────────────────────────────
    if args.output:
        out_path = Path(args.output)
        out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"\n  Saved raw manifest → {out_path}")

    # ── Step 5: Extract records ──────────────────────────────────────────
    print(f"\n═══ Extract Records ═══")
    records = extract_records(manifest)
    if not records:
        print("  ⚠ No records generated")
        print("    The dataspace may be empty or contain only unsupported RESQML types.")
        return

    print(f"  Total: {len(records)} records")

    # Show summary by kind
    kinds: Dict[str, int] = {}
    for rec in records:
        kind = rec.get("kind", "unknown")
        # "osdu:wks:work-product-component--StructureMap:1.0.0" → "StructureMap"
        short = kind.split("--")[-1].split(":")[0] if "--" in kind else kind
        kinds[short] = kinds.get(short, 0) + 1
    for k, v in sorted(kinds.items()):
        print(f"    {k}: {v}")

    if args.no_push:
        if not args.output:
            print(json.dumps(manifest, indent=2))
        print(f"\n  ✓ {len(records)} records built (--no-push: not pushed to catalog)")
        return

    # ── Step 6: Stamp ACL/legal and push ─────────────────────────────────
    print(f"\n═══ Push to Catalog ({osdu_url}) ═══")
    stamp_acl_legal(records, owners, viewers, legal_tag, countries)
    total_ok = push_to_catalog(records, storage_url, headers)

    print(f"\n═══ Done ═══")
    print(f"  {total_ok}/{len(records)} records pushed to catalog")

    if args.output:
        print(f"  Raw manifest saved to: {args.output}")


if __name__ == "__main__":
    main()
