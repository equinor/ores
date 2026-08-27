#!/usr/bin/env python3
"""
ingest_drogon22.py – Ingest Drogon RESQML 2.2 demo EPC into any OSDU instance
and push the OSDU manifest.

This is the RESQML 2.2 upgrade of the drogonresqml demo (was RESQML 2.0.1).

Key differences from RESQML 2.0.1:
  - Dataspace: maap/drogon22 (instead of maap/drogon)
  - RESQML type prefix: resqml22 (instead of resqml20)
  - Object naming: BoundaryFeature (unified, replaces GeneticBoundaryFeature
    and TectonicBoundaryFeature), no obj_ prefix
  - EML Common 2.3 citation block
  - Updated EPC internal naming conventions

Supports:  interop, interop  (any instance configured in k8s/configmap.yaml)

Steps:
  1. Authenticate (reads auth mode from instance config)
  2. Create dataspace maap/drogon22 on target RDDMS
  3. Import EPC via ETP (RESQML 2.2 content)
  4. Verify import via REST
  5. Load OSDU manifest (RESQML 2.2 schema mappings)
  6. Patch manifest with target instance ACLs/partition
  7. Push to OSDU catalog (Workflow or Storage API)

Usage:
  python demo/drogonresqml22/ingest_drogon22.py interop              # full pipeline
  python demo/drogonresqml22/ingest_drogon22.py interop               # full pipeline
  python demo/drogonresqml22/ingest_drogon22.py interop --skip-etp    # manifest only
  python demo/drogonresqml22/ingest_drogon22.py interop --save-only   # build + save, no push
  python demo/drogonresqml22/ingest_drogon22.py interop --dry-run     # no remote changes
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

try:
    import httpx
except ImportError:
    sys.exit("pip install httpx")

# ── Paths ─────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent          # demo/drogonresqml22/
DEMO_DIR = SCRIPT_DIR.parent                          # demo/
sys.path.insert(0, str(DEMO_DIR))

from _auth import get_token, load_instance  # noqa: E402

# ── Constants ─────────────────────────────────────────────────────────────
DATASPACE_DEFAULT = "maap/drogon22"
DATASPACE_OVERRIDE = {}
EPC_FILE = SCRIPT_DIR / "drogon22.epc"
MANIFEST_FILE = SCRIPT_DIR / "manifest_drogon22_subset.json"
IMAGE_SSL = "osdu-etp-sslclient"

# RESQML 2.2 type prefix (no obj_ prefix, different class names)
RESQML_PREFIX = "resqml22"


# ═══════════════════════════════════════════════════════════════════════════
# Instance config loader
# ═══════════════════════════════════════════════════════════════════════════

class InstanceConfig:
    """Loads all instance-specific settings from configmap/env."""

    def __init__(self, name: str):
        self.name = name
        inst = load_instance(name)
        self.host = inst["host"].replace("https://", "").replace("http://", "").rstrip("/")
        self.partition = inst.get("partition") or "opendes"
        self.legal_tag = inst.get("legal_tag") or f"{self.partition}-default-legal-tag"
        owners = inst.get("owners")
        self.owners = owners if isinstance(owners, list) else [owners] if owners else [f"data.default.owners@{self.partition}.dataservices.energy"]
        viewers = inst.get("viewers")
        self.viewers = viewers if isinstance(viewers, list) else [viewers] if viewers else [f"data.default.viewers@{self.partition}.dataservices.energy"]
        countries = inst.get("countries")
        self.countries = countries if isinstance(countries, list) else [countries] if countries else ["NO"]
        self.dataspace = DATASPACE_OVERRIDE.get(name, DATASPACE_DEFAULT)
        self.base_rddms = f"https://{self.host}/api/reservoir-ddms/v2"
        self.base_osdu = f"https://{self.host}"
        self.etp_url = f"wss://{self.host}/api/reservoir-ddms-etp/v2/"

    def headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "data-partition-id": self.partition,
            "Content-Type": "application/json",
        }

    def __repr__(self):
        return (f"InstanceConfig({self.name}: {self.host}, "
                f"partition={self.partition}, legal={self.legal_tag})")


# ═══════════════════════════════════════════════════════════════════════════
# 1. Auth
# ═══════════════════════════════════════════════════════════════════════════

def authenticate(cfg: InstanceConfig) -> str:
    """Get access token for the target instance."""
    print(f"=== 1. Authenticate ({cfg.name}) ===")
    token = get_token(cfg.name, verbose=True)
    if not token:
        sys.exit(f"Failed to get access token for {cfg.name}")
    return token


# ═══════════════════════════════════════════════════════════════════════════
# 2. Create dataspace
# ═══════════════════════════════════════════════════════════════════════════

def purge_dataspace(token: str, cfg: InstanceConfig) -> bool:
    """Delete the whole dataspace via ETP (requires ETP delete rights, e.g.
    interop). On instances without delete rights (interop) this is a no-op."""
    print(f"\n=== 2a. Purge dataspace ({cfg.dataspace}) via ETP ===")
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
    cmd = ["docker", "run", "--rm", "-v", f"{SCRIPT_DIR}:/data",
           "--entrypoint=sh", IMAGE_SSL, "-c", inner]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    tok_file.unlink(missing_ok=True)
    combined = result.stdout + result.stderr
    if result.returncode == 0:
        print(f"  ✓ Purged dataspace {cfg.dataspace}")
        time.sleep(3)
        return True
    if "not found" in combined.lower():
        print(f"  ✓ Dataspace {cfg.dataspace} did not exist (nothing to purge)")
        return True
    print(f"  ⚠ Purge failed (rc={result.returncode}) - likely no ETP delete "
          f"rights on this instance; continuing additive")
    print(f"    {combined[-200:]}")
    return False


def create_dataspace(token: str, cfg: InstanceConfig) -> bool:
    """Create maap/drogon22 dataspace on remote RDDMS via REST."""
    print(f"\n=== 2. Create dataspace ({cfg.dataspace}) ===")
    payload = [{
        "DataspaceId": cfg.dataspace,
        "Path": cfg.dataspace,
        "CustomData": {
            "legaltags": [cfg.legal_tag],
            "otherRelevantDataCountries": cfg.countries,
            "owners": cfg.owners,
            "viewers": cfg.viewers,
        },
    }]
    r = httpx.post(f"{cfg.base_rddms}/dataspaces", headers=cfg.headers(token),
                   json=payload, timeout=30)
    if r.status_code in (200, 201):
        print(f"  ✓ Created dataspace {cfg.dataspace}")
        return True
    if r.status_code in (400, 409):
        print(f"  ✓ Dataspace {cfg.dataspace} already exists ({r.status_code})")
        return True
    if r.status_code in (401, 403):
        print(f"  ⚠ REST create failed ({r.status_code}), trying ETP...")
        return create_dataspace_etp(token, cfg)
    print(f"  ✗ Failed: {r.status_code} {r.text[:300]}")
    return False


def create_dataspace_etp(token: str, cfg: InstanceConfig) -> bool:
    """Create dataspace via ETP client (fallback)."""
    xdata = json.dumps({
        "legaltags": [cfg.legal_tag],
        "otherRelevantDataCountries": cfg.countries,
        "owners": cfg.owners,
        "viewers": cfg.viewers,
    })

    tok_file = SCRIPT_DIR / ".etp_token"
    tok_file.write_text(token)

    inner = (
        f"export JWT=$(cat /data/.etp_token) && "
        f"/bin/openETPServer space "
        f"--server-url {cfg.etp_url} "
        f"--data-partition-id {cfg.partition} "
        f"--auth bearer --jwt-token $JWT "
        f"--new -s {cfg.dataspace} "
        f"--xdata '{xdata}'"
    )
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{SCRIPT_DIR}:/data",
        "--entrypoint=sh", IMAGE_SSL, "-c", inner,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    tok_file.unlink(missing_ok=True)

    combined = result.stdout + result.stderr
    if result.returncode == 0:
        print(f"  ✓ Created dataspace {cfg.dataspace} via ETP")
        return True
    if "already exist" in combined.lower():
        print(f"  ✓ Dataspace {cfg.dataspace} already exists")
        return True
    print(f"  ✗ ETP create failed (rc={result.returncode})")
    print(f"    {combined[-300:]}")
    return False


# ═══════════════════════════════════════════════════════════════════════════
# 3. Import EPC via ETP
# ═══════════════════════════════════════════════════════════════════════════

def import_epc(token: str, cfg: InstanceConfig) -> bool:
    """Import RESQML 2.2 EPC into the target RDDMS via ETP."""
    print(f"\n=== 3. Import EPC via ETP (RESQML 2.2) ===")

    if not EPC_FILE.exists():
        print(f"  ⚠ EPC file not found: {EPC_FILE}")
        print(f"    Build it with: python demo/drogonresqml22/build_drogon22_epc.py")
        return False

    tok_file = SCRIPT_DIR / ".etp_token"
    tok_file.write_text(token)

    inner = (
        f"export JWT=$(cat /data/.etp_token) && "
        f"/bin/openETPServer space "
        f"--server-url {cfg.etp_url} "
        f"--data-partition-id {cfg.partition} "
        f"--auth bearer --jwt-token $JWT "
        f"-s {cfg.dataspace} "
        f"--import-epc /data/{EPC_FILE.name} -j -M 50MB"
    )
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{SCRIPT_DIR}:/data",
        "--entrypoint=sh", IMAGE_SSL, "-c", inner,
    ]
    print(f"  Importing {EPC_FILE.name} → {cfg.dataspace}")
    print(f"  ETP URL: {cfg.etp_url}")
    result = subprocess.run(cmd, text=True, timeout=600)
    tok_file.unlink(missing_ok=True)

    if result.returncode == 0:
        print(f"  ✓ EPC import succeeded (RESQML 2.2)")
        return True
    print(f"  ✗ EPC import failed (rc={result.returncode})")
    return False


# ═══════════════════════════════════════════════════════════════════════════
# 4. Verify import
# ═══════════════════════════════════════════════════════════════════════════

def verify_import(token: str, cfg: InstanceConfig) -> bool:
    """Check resources in the remote dataspace."""
    print(f"\n=== 4. Verify import ===")
    ds_enc = cfg.dataspace.replace("/", "%2F")
    r = httpx.get(f"{cfg.base_rddms}/dataspaces/{ds_enc}/resources",
                  headers=cfg.headers(token), timeout=30)
    if not r.is_success:
        print(f"  ⚠ Could not verify: {r.status_code} {r.text[:200]}")
        return False
    resources = r.json()
    if isinstance(resources, list):
        total = sum(t.get("count", 0) for t in resources)
        print(f"  ✓ {total} objects across {len(resources)} types")
        for t in resources:
            print(f"    {t.get('name', '?')}: {t.get('count', '?')}")
        # Verify we see resqml22 types
        resqml22_types = [t for t in resources if "resqml22" in t.get("name", "")]
        if resqml22_types:
            print(f"  ✓ Confirmed RESQML 2.2 types present")
        else:
            print(f"  ⚠ No resqml22 types found – check EPC version")
    else:
        print(f"  Response: {json.dumps(resources)[:300]}")
    return True


# ═══════════════════════════════════════════════════════════════════════════
# 5. Load manifest
# ═══════════════════════════════════════════════════════════════════════════

def load_manifest(cfg: InstanceConfig) -> dict:
    """Load the pre-built RESQML 2.2 manifest."""
    print(f"\n=== 5. Load manifest (RESQML 2.2) ===")
    if not MANIFEST_FILE.exists():
        sys.exit(f"  ✗ Manifest not found: {MANIFEST_FILE}")
    manifest = json.loads(MANIFEST_FILE.read_text())
    data = manifest.get("Data", {})
    total = sum(len(v) for v in data.values() if isinstance(v, list))
    print(f"  Loaded {total} records from {MANIFEST_FILE.name}")

    # Re-partition for target instance
    manifest = _repartition(manifest, cfg)
    return manifest


def _repartition(manifest: dict, cfg: InstanceConfig) -> dict:
    """Replace partition prefix and dataspace in all record IDs and cross-references."""
    old_partition = "opendes"
    old_dataspace = "maap/drogon22"

    need_partition = cfg.partition != old_partition
    need_dataspace = cfg.dataspace != old_dataspace

    if not need_partition and not need_dataspace:
        return manifest

    def _replace(obj):
        if isinstance(obj, str):
            s = obj
            if need_partition:
                s = s.replace(f"{old_partition}:", f"{cfg.partition}:")
            if need_dataspace:
                s = s.replace(old_dataspace, cfg.dataspace)
            return s
        if isinstance(obj, list):
            return [_replace(v) for v in obj]
        if isinstance(obj, dict):
            return {k: _replace(v) for k, v in obj.items()}
        return obj

    return _replace(manifest)


def build_manifest_remote(token: str, cfg: InstanceConfig) -> dict:
    """Call POST /manifests/build on the remote RDDMS (after EPC import)."""
    print(f"\n=== 5. Build manifest (remote) ===")
    url = f"{cfg.base_rddms}/manifests/build"
    body = {
        "uris": [f"eml:///dataspace('{cfg.dataspace}')"],
        "createMissingReferences": True,
    }
    print(f"  POST {url}")
    r = httpx.post(url, json=body, headers=cfg.headers(token), timeout=120)
    if r.status_code >= 300:
        print(f"  FAIL {r.status_code}: {r.text[:500]}")
        sys.exit(1)

    manifest = r.json()
    data = manifest.get("Data", {})
    counts = {k: len(v) for k, v in data.items() if isinstance(v, list)}
    print(f"  ✓ {counts}")
    return manifest


# ═══════════════════════════════════════════════════════════════════════════
# 6. Patch manifest for target instance
# ═══════════════════════════════════════════════════════════════════════════

def patch_manifest(manifest: dict, cfg: InstanceConfig) -> dict:
    """Patch all records with target instance ACLs and legal tags."""
    print(f"\n=== 6. Patch manifest ({cfg.name}) ===")
    data = manifest.get("Data", {})

    patched = 0
    for section in data.values():
        if not isinstance(section, list):
            continue
        for rec in section:
            rec["acl"] = {"owners": cfg.owners, "viewers": cfg.viewers}
            rec["legal"] = {
                "legaltags": [cfg.legal_tag],
                "otherRelevantDataCountries": cfg.countries,
                "status": "compliant",
            }
            patched += 1

    print(f"  Patched {patched} records → partition={cfg.partition}, legal={cfg.legal_tag}")
    return manifest


# ═══════════════════════════════════════════════════════════════════════════
# 7. Save / Push
# ═══════════════════════════════════════════════════════════════════════════

def save_manifest(manifest: dict, cfg: InstanceConfig, output: Path | None = None) -> Path:
    """Save manifest to disk."""
    out = output or SCRIPT_DIR / f"manifest_drogon22_{cfg.name}.json"
    out.write_text(json.dumps(manifest, indent=2))
    size_kb = out.stat().st_size / 1024
    print(f"\n  Saved: {out.name} ({size_kb:.0f} KB)")
    return out


def push_via_storage(token: str, cfg: InstanceConfig, manifest: dict) -> bool:
    """Push records via Storage API PUT /records."""
    url = f"{cfg.base_osdu}/api/storage/v2/records"
    hdrs = cfg.headers(token)

    records: list[dict] = []
    for section in manifest.get("Data", {}).values():
        if isinstance(section, list):
            records.extend(section)

    BATCH = 100
    ok = 0
    fail = 0
    for i in range(0, len(records), BATCH):
        batch = records[i:i + BATCH]
        print(f"  PUT batch {i // BATCH + 1} ({len(batch)} records)...")
        r = httpx.put(url, headers=hdrs, json=batch, timeout=120)
        if r.is_success:
            cnt = r.json().get("recordCount", len(batch))
            ok += cnt
            print(f"    ✓ {cnt} stored")
        else:
            fail += len(batch)
            print(f"    ✗ {r.status_code}: {r.text[:200]}")

    print(f"  Results: {ok} stored, {fail} failed")
    return fail == 0


def push_via_workflow(token: str, cfg: InstanceConfig, manifest: dict) -> bool:
    """Push manifest via Workflow API (Osdu_ingest)."""
    url = f"{cfg.base_osdu}/api/workflow/v1/workflow/Osdu_ingest/workflowRun"
    hdrs = cfg.headers(token)
    body = {
        "executionContext": {
            "manifest": manifest,
            "Payload": {
                "data-partition-id": cfg.partition,
                "AppKey": "ores-drogon22-ingest",
            },
        },
    }
    print(f"  POST {url}")
    r = httpx.post(url, headers=hdrs, json=body, timeout=60)
    if r.status_code not in (200, 201, 202):
        print(f"  FAIL {r.status_code}: {r.text[:300]}")
        return False

    run_id = r.json().get("runId", "?")
    print(f"  Workflow run: {run_id}")
    status = _poll_workflow(token, cfg, run_id)
    print(f"  Final status: {status}")
    return status in ("completed", "succeeded", "finished")


def _poll_workflow(token: str, cfg: InstanceConfig, run_id: str,
                   timeout: int = 300, interval: int = 5) -> str:
    """Poll workflow run until terminal state or timeout."""
    url = f"{cfg.base_osdu}/api/workflow/v1/workflow/Osdu_ingest/workflowRun/{run_id}"
    hdrs = cfg.headers(token)
    deadline = time.time() + timeout

    while time.time() < deadline:
        time.sleep(interval)
        try:
            r = httpx.get(url, headers=hdrs, timeout=30)
            if not r.is_success:
                continue
            status = r.json().get("status", "unknown").lower()
            if status in ("completed", "succeeded", "failed", "error",
                          "cancelled", "finished"):
                return status
            print(f"    poll: {status}...")
        except Exception:
            continue
    return "timeout"


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="Ingest Drogon RESQML 2.2 demo EPC into an OSDU instance")
    ap.add_argument("instance", choices=["interop", "interop"],
                    help="Target OSDU instance name")
    ap.add_argument("--dataspace", default=None,
                    help="Override dataspace (default: maap/drogon221)")
    ap.add_argument("--skip-etp", action="store_true",
                    help="Skip ETP import (manifest only)")
    ap.add_argument("--purge", action="store_true",
                    help="Purge the dataspace via ETP before import (interop only; "
                         "no-op where ETP delete rights are absent, e.g. interop)")
    ap.add_argument("--remote-manifest", action="store_true",
                    help="Use remote RDDMS manifest builder instead of local manifest")
    ap.add_argument("--save-only", action="store_true",
                    help="Save manifest, don't push to catalog")
    ap.add_argument("--dry-run", action="store_true",
                    help="No remote changes at all")
    ap.add_argument("--storage", action="store_true",
                    help="Use Storage API instead of Workflow API")
    ap.add_argument("-o", "--output", type=Path,
                    help="Output path for manifest JSON")
    args = ap.parse_args()

    cfg = InstanceConfig(args.instance)
    if args.dataspace:
        cfg.dataspace = args.dataspace

    print(f"{'═' * 60}")
    print(f"  Drogon RESQML 2.2 Demo → {cfg.name} ({cfg.host})")
    print(f"  Dataspace:  {cfg.dataspace}")
    print(f"  Partition:  {cfg.partition}")
    print(f"  Legal:      {cfg.legal_tag}")
    print(f"  RESQML:     2.2 (resqml22.* types, no obj_ prefix)")
    print(f"  EPC:        {EPC_FILE.name}")
    print(f"{'═' * 60}\n")

    # ── Auth ──
    token = None
    need_remote = not args.save_only and not args.dry_run
    if need_remote or not args.skip_etp:
        token = authenticate(cfg)

    # ── ETP import ──
    if not args.dry_run and not args.skip_etp:
        if not token:
            token = authenticate(cfg)
        if args.purge:
            purge_dataspace(token, cfg)
        create_dataspace(token, cfg)
        ok = import_epc(token, cfg)
        if not ok:
            print("  ⚠ ETP import failed - continuing with manifest")
        verify_import(token, cfg)

    # ── Load manifest ──
    if args.remote_manifest and not args.skip_etp:
        if not token:
            token = authenticate(cfg)
        manifest = build_manifest_remote(token, cfg)
    else:
        manifest = load_manifest(cfg)

    # ── Patch for target ──
    manifest = patch_manifest(manifest, cfg)

    # ── Summary ──
    data = manifest.get("Data", {})
    total = sum(len(v) for v in data.values() if isinstance(v, list))
    print(f"\n  Manifest: {total} records")
    for k, v in data.items():
        if isinstance(v, list) and v:
            print(f"    {k}: {len(v)}")

    # ── Save ──
    out_path = save_manifest(manifest, cfg, args.output)

    if args.save_only or args.dry_run:
        print(f"\n{'─' * 60}")
        print(f"  Done (saved to {out_path.name}, not pushed)")
        return

    # ── Push ──
    print(f"\n=== 7. Push manifest to catalog ===")
    if not token:
        token = authenticate(cfg)

    if args.storage:
        ok = push_via_storage(token, cfg, manifest)
    else:
        ok = push_via_workflow(token, cfg, manifest)
        if not ok:
            print("  Workflow failed, trying Storage API fallback...")
            ok = push_via_storage(token, cfg, manifest)

    if ok:
        print(f"\n{'═' * 60}")
        print(f"  ✓ {total} records indexed in {cfg.name} catalog")
    else:
        print(f"\n  ⚠ Some records failed to index")
        sys.exit(1)


if __name__ == "__main__":
    main()
