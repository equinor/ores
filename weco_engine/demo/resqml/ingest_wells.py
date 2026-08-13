#!/usr/bin/env python3
"""
ingest_wells.py — Ingest WeCo demo wells into RDDMS via ORES k8s auth
======================================================================

Uses the ORES instance/auth infrastructure (k8s/configmap.yaml + secret.yaml)
to authenticate and push RESQML payloads to Reservoir-DDMS v2 instances.

Target instances (from ORES k8s config):
  - eqndev   — SWE dev (per_user_pkce or client_credentials)
  - interop  — ADME Interop (client_credentials)
  - preship  — Microsoft pre-ship M26

The correct RDDMS v2 transactional API is:
  POST /api/reservoir-ddms/v2/dataspaces/{ds}/transactions       → begin
  PUT  /api/reservoir-ddms/v2/dataspaces/{ds}/resources?txId=... → write
  PUT  /api/reservoir-ddms/v2/dataspaces/{ds}/transactions/{id}  → commit

Usage::

    # Ingest to interop and eqndev (uses k8s/secret.yaml credentials):
    python demo/resqml/ingest_wells.py --instance interop eqndev

    # Ingest to all configured instances:
    python demo/resqml/ingest_wells.py --all

    # Dry-run:
    python demo/resqml/ingest_wells.py --all --dry-run

    # Also include local RDDMS (docker WSL):
    python demo/resqml/ingest_wells.py --instance local

Prerequisites:
  - Generate payloads first: python demo/resqml/generate_payloads.py
  - ORES k8s/secret.yaml must be populated (cp from template + fill secrets)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

# Add project roots to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ORES_ROOT = PROJECT_ROOT.parent / "ores"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(ORES_ROOT))

TARGET_DATASPACE = "maap/weco"
PAYLOADS_DIR = Path(__file__).parent / "payloads"

# Local RDDMS (WSL docker stack)
LOCAL_RDDMS_URL = "http://localhost:3000/api/reservoir-ddms/v2"


# ═══════════════════════════════════════════════════════════════════════════
#  Load ORES k8s config → env vars → instances
# ═══════════════════════════════════════════════════════════════════════════

def _load_ores_env():
    """Load ORES k8s configmap + secret into environment (like eval env_from_k8s)."""
    k8s_dir = ORES_ROOT / "k8s"
    if not k8s_dir.exists():
        print(f"  WARN: ORES k8s dir not found at {k8s_dir}")
        return

    sys.path.insert(0, str(k8s_dir))
    from env_from_k8s import load_k8s_yaml

    config = load_k8s_yaml(k8s_dir / "configmap.yaml")
    secrets = load_k8s_yaml(k8s_dir / "secret.yaml")

    # Set env vars (don't override existing ones)
    for key, val in {**config, **secrets}.items():
        if key not in os.environ:
            os.environ[key] = val

    n_cfg = len(config)
    n_sec = len(secrets)
    print(f"  [env] Loaded {n_cfg} config + {n_sec} secret vars from k8s/")


def _get_instances():
    """Load ORES instances after env is populated."""
    from app.instances import get_instances, _load_instances, _instances
    if not _instances:
        _load_instances()
    return get_instances()


# ═══════════════════════════════════════════════════════════════════════════
#  Synchronous RDDMS v2 Client (transactional)
# ═══════════════════════════════════════════════════════════════════════════

class RddmsV2Client:
    """Synchronous client using the correct RDDMS v2 transactional API."""

    def __init__(self, base_url: str, token: str, data_partition: str,
                 ssl_verify: bool = True):
        import httpx
        self.base_url = base_url.rstrip("/")
        self.data_partition = data_partition
        self.client = httpx.Client(
            timeout=120.0,
            verify=ssl_verify,
            headers={
                "Authorization": f"Bearer {token}",
                "data-partition-id": data_partition,
                "Content-Type": "application/json",
            },
        )

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _ds_enc(self, dataspace: str) -> str:
        return urllib.parse.quote(dataspace, safe="")

    def check_dataspace(self, dataspace: str) -> bool:
        """Check if dataspace exists."""
        ds = self._ds_enc(dataspace)
        try:
            r = self.client.get(self._url(f"/dataspaces/{ds}"))
            return r.status_code == 200
        except Exception:
            return False

    def list_dataspaces(self) -> list:
        """List available dataspaces."""
        try:
            r = self.client.get(self._url("/dataspaces"))
            if r.status_code == 200:
                return r.json() if isinstance(r.json(), list) else []
        except Exception:
            pass
        return []

    def put_objects_transactional(self, dataspace: str, objects: list) -> int:
        """Write objects using begin->put->commit transaction."""
        if not objects:
            return 0

        ds = self._ds_enc(dataspace)

        # Begin transaction
        r = self.client.post(self._url(f"/dataspaces/{ds}/transactions"))
        if r.status_code not in (200, 201):
            print(f"    x BEGIN TX failed: {r.status_code} {r.text[:300]}")
            return 0
        # tx_id: might be JSON string or raw text
        try:
            tx_id = r.json() if isinstance(r.json(), str) else r.text.strip('" \n')
        except Exception:
            tx_id = r.text.strip('" \n')

        # PUT objects (batch up to 50)
        batch_size = 50
        total = 0
        for i in range(0, len(objects), batch_size):
            batch = objects[i:i + batch_size]
            r = self.client.put(
                self._url(f"/dataspaces/{ds}/resources"),
                json=batch,
                params={"transactionId": tx_id},
            )
            if r.status_code in (200, 201, 204):
                total += len(batch)
            else:
                print(f"    x PUT batch {i//batch_size+1} failed: "
                      f"{r.status_code} {r.text[:200]}")
                # Rollback
                self.client.delete(
                    self._url(f"/dataspaces/{ds}/transactions/{tx_id}"))
                return total

        # Commit
        r = self.client.put(self._url(f"/dataspaces/{ds}/transactions/{tx_id}"))
        if r.status_code not in (200, 201, 204):
            print(f"    x COMMIT failed: {r.status_code} {r.text[:200]}")
            self.client.delete(
                self._url(f"/dataspaces/{ds}/transactions/{tx_id}"))
            return 0

        return total

    def close(self):
        self.client.close()


# ═══════════════════════════════════════════════════════════════════════════
#  Token acquisition (from ORES instances — async bridge)
# ═══════════════════════════════════════════════════════════════════════════

def _get_token_for_instance(inst) -> str:
    """Get an access token for an OsduInstance (sync wrapper)."""
    # For client_credentials or refresh_token modes, mint a token
    if inst.auth_mode in ("client_credentials", "refresh_token",
                          "refresh_token+client_credentials"):
        token = asyncio.run(inst.get_access_token())
        if token:
            return token

    # For per_user_pkce — need an existing token from env or az cli
    if inst.auth_mode == "per_user_pkce":
        import subprocess
        try:
            # OSDU/ADME first-party app resource ID
            resource = inst.client_id or "bd0c9d90-89ad-4bb3-97bc-d787b9f69cdc"
            # scope may have /.default suffix — strip for az cli resource
            if inst.scope:
                resource = inst.scope.split()[0].replace("/.default", "")
            result = subprocess.run(
                ["az", "account", "get-access-token", "--resource", resource],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                token = data.get("accessToken")
                if token:
                    print(f"    [auth] Token from az cli (per_user_pkce)")
                    return token
        except Exception:
            pass

    # Last resort: env var
    token = os.environ.get("OSDU_TOKEN") or os.environ.get("RDDMS_TOKEN")
    if token:
        print(f"    [auth] Token from env var")
        return token

    raise RuntimeError(
        f"Cannot get token for instance '{inst.name}' (auth_mode={inst.auth_mode}). "
        f"Ensure k8s/secret.yaml has the required credentials."
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Ingestion Logic
# ═══════════════════════════════════════════════════════════════════════════

def load_payloads(dataset_dir: Path) -> dict:
    """Load all JSON payload files from a dataset directory."""
    payloads = {}
    for json_file in sorted(dataset_dir.glob("*.json")):
        if json_file.name == "manifest.json":
            continue
        with open(json_file) as f:
            data = json.load(f)
        payloads[json_file.stem] = data
    return payloads


def ingest_dataset(client: RddmsV2Client, dataset_name: str,
                   dataspace: str, dry_run: bool = False) -> dict:
    """Ingest one dataset into RDDMS via transactional API.

    Uses multi-phase approach:
      Phase 1: wells.json (trajectories + frames)
      Phase 2: logs.json + regions.json (properties referencing frames)
    """
    dataset_dir = PAYLOADS_DIR / dataset_name
    if not dataset_dir.exists():
        print(f"    SKIP: No payloads at {dataset_dir}")
        return {}

    payloads = load_payloads(dataset_dir)
    if not payloads:
        print(f"    SKIP: No JSON files in {dataset_dir}")
        return {}

    summary = {"dataset": dataset_name}

    # Phase 1: wells (trajectories + frames) — must commit before properties
    phase1 = ["wells"]
    # Phase 2: properties (reference frames from phase 1)
    phase2 = ["logs", "regions", "markers"]

    for phase_name, phase_keys in [("phase1:wells", phase1), ("phase2:props", phase2)]:
        phase_objects = []
        for key in phase_keys:
            if key in payloads:
                phase_objects.extend(payloads[key])

        if not phase_objects:
            continue

        n = len(phase_objects)
        if dry_run:
            print(f"    [dry-run] {phase_name}: {n} objects")
            summary[phase_name] = n
        else:
            t0 = time.time()
            ingested = client.put_objects_transactional(dataspace, phase_objects)
            elapsed = time.time() - t0
            status = "ok" if ingested == n else "PARTIAL"
            print(f"    {phase_name}: {ingested}/{n} objects ({elapsed:.1f}s) [{status}]")
            summary[phase_name] = ingested

    return summary


def ingest_to_instance(inst_name: str, instances: dict, datasets: list,
                       dry_run: bool = False) -> dict:
    """Ingest all datasets into one RDDMS instance using ORES auth."""
    # Handle "local" specially
    if inst_name == "local":
        print(f"\n{'_' * 50}")
        print(f"  Instance: Local RDDMS (WSL docker)")
        print(f"  URL: {LOCAL_RDDMS_URL}")
        print(f"  Dataspace: {TARGET_DATASPACE}")
        print(f"{'_' * 50}")

        if dry_run:
            results = {}
            for ds in datasets:
                print(f"\n  [{ds}]")
                results[ds] = ingest_dataset(None, ds, TARGET_DATASPACE, dry_run=True)
            return results

        client = RddmsV2Client(
            LOCAL_RDDMS_URL, "dummy", "opendes", ssl_verify=False)
        try:
            results = {}
            for ds in datasets:
                print(f"\n  [{ds}]")
                results[ds] = ingest_dataset(client, ds, TARGET_DATASPACE)
            return results
        finally:
            client.close()

    # ORES instance
    if inst_name not in instances:
        print(f"\n  ERROR: Instance '{inst_name}' not found in ORES config.")
        print(f"  Available: {list(instances.keys())}")
        return {}

    inst = instances[inst_name]
    rddms_url = f"https://{inst.hostname}/api/reservoir-ddms/v2"

    print(f"\n{'_' * 50}")
    print(f"  Instance: {inst_name}")
    print(f"  Hostname: {inst.hostname}")
    print(f"  RDDMS URL: {rddms_url}")
    print(f"  Partition: {inst.data_partition_id}")
    print(f"  Auth mode: {inst.auth_mode}")
    print(f"  Dataspace: {TARGET_DATASPACE}")
    print(f"{'_' * 50}")

    if dry_run:
        results = {}
        for ds in datasets:
            print(f"\n  [{ds}]")
            results[ds] = ingest_dataset(None, ds, TARGET_DATASPACE, dry_run=True)
        return results

    # Get token
    print(f"  Acquiring token ({inst.auth_mode})...")
    try:
        token = _get_token_for_instance(inst)
        print(f"  Token acquired (len={len(token)})")
    except Exception as e:
        print(f"  Auth failed: {e}")
        return {}

    client = RddmsV2Client(
        rddms_url, token, inst.data_partition_id,
        ssl_verify=inst.ssl_verify,
    )
    try:
        # Check connectivity
        if client.check_dataspace(TARGET_DATASPACE):
            print(f"  Dataspace '{TARGET_DATASPACE}' exists")
        else:
            print(f"  Dataspace '{TARGET_DATASPACE}' not found (will try to write anyway)")

        results = {}
        for ds in datasets:
            print(f"\n  [{ds}]")
            results[ds] = ingest_dataset(client, ds, TARGET_DATASPACE)
        return results
    finally:
        client.close()


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Ingest WeCo demo wells into RDDMS (using ORES k8s auth)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--instance", nargs="+", default=["eqndev"],
        help="Target instance(s): eqndev, interop, preship, local (default: eqndev)",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Ingest to all configured instances + local",
    )
    parser.add_argument(
        "--dataset",
        help="Ingest only one dataset (default: all available)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate payloads without sending to RDDMS",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  WeCo Demo Well Ingestion -> RDDMS (ORES k8s auth)")
    print("=" * 60)

    # Check payloads exist
    if not PAYLOADS_DIR.exists():
        print(f"\nERROR: Payloads not found at {PAYLOADS_DIR}")
        print("Run first: python demo/resqml/generate_payloads.py")
        sys.exit(1)

    available = [d for d in PAYLOADS_DIR.iterdir()
                 if d.is_dir() and (d / "wells.json").exists()]
    if not available:
        print(f"\nERROR: No dataset payloads found in {PAYLOADS_DIR}")
        print("Run first: python demo/resqml/generate_payloads.py")
        sys.exit(1)

    datasets = [args.dataset] if args.dataset else [d.name for d in available]
    print(f"\n  Datasets: {datasets}")
    print(f"  Target dataspace: {TARGET_DATASPACE}")

    # Load ORES env from k8s config
    print(f"\n  Loading ORES k8s config...")
    _load_ores_env()

    # Load instances
    instances = _get_instances()
    print(f"  Available instances: {list(instances.keys())}")

    # Determine target instances
    if args.all:
        target_instances = list(instances.keys()) + ["local"]
    else:
        target_instances = args.instance

    # Ingest
    all_results = {}
    for inst_name in target_instances:
        all_results[inst_name] = ingest_to_instance(
            inst_name, instances, datasets, dry_run=args.dry_run)

    # Summary
    print(f"\n{'=' * 60}")
    print("  Summary")
    print(f"{'=' * 60}")
    for inst_name, results in all_results.items():
        if not results:
            print(f"\n  {inst_name}: FAILED / SKIPPED")
            continue
        print(f"\n  {inst_name}:")
        for ds_name, ds_result in results.items():
            total = sum(v for k, v in ds_result.items() if k != "dataset")
            print(f"    {ds_name}: {total} objects")


if __name__ == "__main__":
    main()
