#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dataspacecopy.py - Copy a dataspace between OSDU RDDMS instances via the
OpenETP Docker client.

Supports three strategies:
  direct   Copy server-to-server (--copy --from-remote). Fastest, but both
           endpoints must be reachable from the Docker container.
  epc      Export → local .epc file → Import into target. Works when direct
           connectivity is blocked.
  local    Export from cloud → import into local RDDMS (ws://localhost:9100).

Prerequisites:
  - Docker running (docker info)
  - Docker image 'osdu-etp-sslclient' (for cloud wss://)
  - Secrets in env: SWEDEV_REFRESH_TOKEN, PRESHIP_CLIENT_ID, PRESHIP_CLIENT_SECRET
    (add to ~/.bashrc)

Usage:
  # Direct copy swedev → preship (default dataspace maap/drogon_dg)
  python demo/dataspacecopy.py

  # Via EPC (export + import, using /tmp as staging area)
  python demo/dataspacecopy.py --strategy epc --epc-dir /tmp/epc-staging

  # Cloud → local RDDMS
  python demo/dataspacecopy.py --to-local --from swedev

  # Dry-run (print docker commands without executing)
  python demo/dataspacecopy.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Paths ─────────────────────────────────────────────────────────────────── #
SCRIPT_DIR = Path(__file__).resolve().parent      # demo/
REPO_ROOT  = SCRIPT_DIR.parent                    # ores/

# Docker images
IMAGE_SSL   = "osdu-etp-sslclient"    # wss:// (cloud endpoints)
IMAGE_LOCAL = "osdu-etp-client"        # ws://  (local RDDMS, no SSL)

LOCAL_ETP_URL = "ws://localhost:9100/"

# ── Instance config & auth via central _auth module ───────────────────────── #
sys.path.insert(0, str(SCRIPT_DIR))
from _auth import load_instance as _load_inst, get_token as _get_token  # noqa: E402

# Also import gettoken for etp_url helper (if available)
try:
    import importlib.util
    _gt_spec = importlib.util.spec_from_file_location("gettoken", SCRIPT_DIR / "gettoken.py")
    _gt = importlib.util.module_from_spec(_gt_spec)
    _gt_spec.loader.exec_module(_gt)
    _has_gt = True
except Exception:
    _has_gt = False


def load_instance(name: str) -> Dict[str, str]:
    """Build an instance dict from the unified _auth resolution chain."""
    inst = _load_inst(name)
    host = inst["host"].replace("https://", "").replace("http://", "").rstrip("/")
    partition = inst.get("partition", "")
    return {
        "name":       inst["name"],
        "host":       host,
        "partition":  partition,
        "etp_url":    f"wss://{host}/api/reservoir-ddms-etp/v2/",
        "legal_tag":  inst.get("legal_tag") or f"{partition}-public-usa-dataset-1",
        "owners":     (inst.get("owners") or [f"data.default.owners@{partition}.dataservices.energy"])[0]
                      if isinstance(inst.get("owners"), list) else
                      inst.get("owners", f"data.default.owners@{partition}.dataservices.energy"),
        "viewers":    (inst.get("viewers") or [f"data.default.viewers@{partition}.dataservices.energy"])[0]
                      if isinstance(inst.get("viewers"), list) else
                      inst.get("viewers", f"data.default.viewers@{partition}.dataservices.energy"),
        "countries":  inst.get("countries", ["NO"])[0] if isinstance(inst.get("countries"), list) else "NO",
    }


def get_access_token(inst: Dict[str, str]) -> str:
    """Mint an access token via the central _auth module."""
    return _get_token(inst["name"], verbose=True)


# ── Docker helpers (reused from ingest_resqml_rddms.py) ──────────────────── #

def run_docker(args: List[str], *, dry_run: bool = False, label: str = "") -> int:
    cmd = ["docker"] + args
    if label:
        print(f"\n--- {label} ---")
    display = " ".join(f'"{a}"' if " " in a else a for a in cmd)
    if dry_run:
        print(f"  [DRY-RUN] {display}")
        return 0
    print(f"  $ {display}")
    result = subprocess.run(cmd, text=True)
    return result.returncode


def etp_flags(server_url: str, partition: str = "", token: str = "") -> str:
    """Build the common openETPServer CLI flags."""
    parts = [f"--server-url {server_url}"]
    if partition:
        parts.append(f"--data-partition-id {partition}")
    if token:
        parts.append(f"--auth bearer --jwt-token {token}")
    return " ".join(parts)


def docker_run(image: str, inner_cmd: str, *,
               network_host: bool = False,
               volume: str = "",
               dry_run: bool = False,
               label: str = "") -> int:
    """Build and run a 'docker run' command."""
    args = ["run", "--rm"]
    if network_host:
        args.append("--network=host")
    if volume:
        args.extend(["-v", volume])
    args.extend(["--entrypoint=sh", image, "-c", inner_cmd])
    return run_docker(args, dry_run=dry_run, label=label)


# ── Dataspace operations ─────────────────────────────────────────────────── #

def list_spaces(server_url: str, image: str, *,
                partition: str = "", token: str = "",
                network_host: bool = False, dry_run: bool = False) -> int:
    flags = etp_flags(server_url, partition, token)
    inner = f"/bin/openETPServer space {flags} --list"
    return docker_run(image, inner, network_host=network_host,
                      dry_run=dry_run, label="List dataspaces")


def create_space(server_url: str, image: str, dataspace: str, *,
                 partition: str = "", token: str = "",
                 xdata: Optional[Dict] = None,
                 network_host: bool = False, dry_run: bool = False) -> int:
    flags = etp_flags(server_url, partition, token)
    inner = f"/bin/openETPServer space {flags} --new -s {dataspace}"
    if xdata:
        xdata_json = json.dumps(xdata)
        inner += f" --xdata '{xdata_json}'"
    return docker_run(image, inner, network_host=network_host,
                      dry_run=dry_run, label=f"Create dataspace '{dataspace}'")


def space_stats(server_url: str, image: str, dataspace: str, *,
                partition: str = "", token: str = "",
                network_host: bool = False, dry_run: bool = False) -> int:
    flags = etp_flags(server_url, partition, token)
    inner = f"/bin/openETPServer space {flags} -s {dataspace} --stats"
    return docker_run(image, inner, network_host=network_host,
                      dry_run=dry_run, label=f"Stats '{dataspace}'")


def export_epc(server_url: str, image: str, dataspace: str, epc_path: Path, *,
               partition: str = "", token: str = "",
               network_host: bool = False, dry_run: bool = False) -> int:
    flags = etp_flags(server_url, partition, token)
    mount_dir = str(epc_path.parent)
    epc_name = epc_path.name
    inner = (f"/bin/openETPServer space {flags} -s {dataspace} "
             f"--export-epc /data/{epc_name} --overwrite -j")
    return docker_run(image, inner, network_host=network_host,
                      volume=f"{mount_dir}:/data",
                      dry_run=dry_run, label=f"Export '{dataspace}' → {epc_name}")


def import_epc(server_url: str, image: str, dataspace: str, epc_path: Path, *,
               partition: str = "", token: str = "",
               network_host: bool = False, dry_run: bool = False) -> int:
    flags = etp_flags(server_url, partition, token)
    mount_dir = str(epc_path.parent)
    epc_name = epc_path.name
    inner = (f"/bin/openETPServer space {flags} -s {dataspace} "
             f"--import-epc /data/{epc_name} -j")
    return docker_run(image, inner, network_host=network_host,
                      volume=f"{mount_dir}:/data",
                      dry_run=dry_run, label=f"Import {epc_name} → '{dataspace}'")


def copy_remote(target_url: str, image: str, dataspace: str, *,
                target_partition: str = "", target_token: str = "",
                source_server: str, source_partition: str = "",
                source_token: str = "", source_space: str = "",
                network_host: bool = False, dry_run: bool = False) -> int:
    """Direct server-to-server copy via --copy --from-remote."""
    flags = etp_flags(target_url, target_partition, target_token)
    source_space = source_space or dataspace
    inner = (
        f"/bin/openETPServer space {flags} -s {dataspace} "
        f"--copy --from-remote "
        f"--source-server {source_server} "
        f"--source-partition {source_partition} "
        f"--source-space {source_space} "
        f"--source-token {source_token} "
        f"-j"
    )
    return docker_run(image, inner, network_host=network_host,
                      dry_run=dry_run,
                      label=f"Copy '{source_space}' → '{dataspace}'")


# ── Strategies ────────────────────────────────────────────────────────────── #

def strategy_direct(src: Dict, dst: Dict, dataspace: str, *,
                    src_token: str, dst_token: str,
                    dst_dataspace: Optional[str] = None,
                    xdata: Optional[Dict] = None,
                    dry_run: bool = False):
    """Server-to-server copy (fastest)."""
    target_ds = dst_dataspace or dataspace
    image = IMAGE_SSL

    # 1. Create target dataspace
    print("\n=== Create target dataspace ===")
    rc = create_space(dst["etp_url"], image, target_ds,
                      partition=dst["partition"], token=dst_token,
                      xdata=xdata, dry_run=dry_run)
    if rc != 0 and not dry_run:
        print("  (may already exist - continuing)")

    # 2. Direct copy
    print("\n=== Direct copy (from-remote) ===")
    rc = copy_remote(
        dst["etp_url"], image, target_ds,
        target_partition=dst["partition"], target_token=dst_token,
        source_server=src["etp_url"],
        source_partition=src["partition"], source_token=src_token,
        source_space=dataspace,
        dry_run=dry_run,
    )
    if rc != 0 and not dry_run:
        sys.exit(f"Copy failed (exit code {rc})")

    # 3. Verify
    print("\n=== Verify target ===")
    space_stats(dst["etp_url"], image, target_ds,
                partition=dst["partition"], token=dst_token,
                dry_run=dry_run)


def strategy_epc(src: Dict, dst: Dict, dataspace: str, *,
                 src_token: str, dst_token: str,
                 dst_dataspace: Optional[str] = None,
                 xdata: Optional[Dict] = None,
                 epc_dir: Optional[str] = None,
                 to_local: bool = False,
                 dry_run: bool = False):
    """Export EPC from source, import into target."""
    target_ds = dst_dataspace or dataspace
    safe_name = dataspace.replace("/", "_")
    staging = Path(epc_dir) if epc_dir else Path(tempfile.mkdtemp(prefix="ores-epc-"))
    staging.mkdir(parents=True, exist_ok=True)
    epc_file = staging / f"{safe_name}.epc"

    src_image = IMAGE_SSL
    if to_local:
        dst_image = IMAGE_LOCAL
        dst_url = LOCAL_ETP_URL
        dst_nh = True
        dst_part = ""
        dst_tok = ""
    else:
        dst_image = IMAGE_SSL
        dst_url = dst["etp_url"]
        dst_nh = False
        dst_part = dst["partition"]
        dst_tok = dst_token

    # 1. Export from source
    print(f"\n=== Export '{dataspace}' from {src['name']} ===")
    print(f"  EPC staging: {epc_file}")
    rc = export_epc(src["etp_url"], src_image, dataspace, epc_file,
                    partition=src["partition"], token=src_token,
                    dry_run=dry_run)
    if rc != 0 and not dry_run:
        sys.exit(f"Export failed (exit code {rc})")

    # 2. Create target dataspace
    print(f"\n=== Create target dataspace '{target_ds}' ===")
    create_space(dst_url, dst_image, target_ds,
                 partition=dst_part, token=dst_tok,
                 xdata=xdata if not to_local else None,
                 network_host=dst_nh, dry_run=dry_run)

    # 3. Import into target
    print(f"\n=== Import into '{target_ds}' on {dst['name'] if not to_local else 'local'} ===")
    rc = import_epc(dst_url, dst_image, target_ds, epc_file,
                    partition=dst_part, token=dst_tok,
                    network_host=dst_nh, dry_run=dry_run)
    if rc != 0 and not dry_run:
        sys.exit(f"Import failed (exit code {rc})")

    # 4. Verify
    print(f"\n=== Verify target ===")
    space_stats(dst_url, dst_image, target_ds,
                partition=dst_part, token=dst_tok,
                network_host=dst_nh, dry_run=dry_run)

    print(f"\n  EPC file kept at: {epc_file}")


# ── Main ──────────────────────────────────────────────────────────────────── #

def main():
    ap = argparse.ArgumentParser(
        description="Copy an OSDU RDDMS dataspace between instances via Docker ETP client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Direct copy swedev → preship (default)
  python demo/dataspacecopy.py

  # Via EPC file (export + import)
  python demo/dataspacecopy.py --strategy epc

  # Cloud → local RDDMS
  python demo/dataspacecopy.py --to-local --from swedev

  # Custom dataspace
  python demo/dataspacecopy.py --dataspace maap/custom --from swedev --to preship
""",
    )
    ap.add_argument("--from", dest="src_instance", default="swedev",
                    help="Source instance name (default: swedev)")
    ap.add_argument("--to", dest="dst_instance", default="preship",
                    help="Target instance name (default: preship)")
    ap.add_argument("--dataspace", default="maap/drogon_dg",
                    help="Source dataspace path (default: maap/drogon_dg)")
    ap.add_argument("--target-dataspace",
                    help="Target dataspace path (default: same as --dataspace)")
    ap.add_argument("--strategy", choices=["direct", "epc"], default="direct",
                    help="Copy strategy: 'direct' (server-to-server) or 'epc' "
                         "(export file + import)")
    ap.add_argument("--epc-dir",
                    help="Directory for EPC staging files (default: temp dir)")
    ap.add_argument("--to-local", action="store_true",
                    help="Target local RDDMS at ws://localhost:9100 (overrides --to)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print Docker commands without executing")
    ap.add_argument("--skip-source-stats", action="store_true",
                    help="Skip printing source dataspace stats before copy")
    args = ap.parse_args()

    # ── Load instances ──
    print("=== Loading instance config ===")
    src = load_instance(args.src_instance)
    print(f"  Source: {src['name']} → {src['host']} / {src['partition']}")

    if args.to_local:
        # Dummy dst for display
        dst = {"name": "local", "host": "localhost:9100", "partition": "",
               "etp_url": LOCAL_ETP_URL}
        print(f"  Target: local RDDMS at {LOCAL_ETP_URL}")
    else:
        dst = load_instance(args.dst_instance)
        print(f"  Target: {dst['name']} → {dst['host']} / {dst['partition']}")

    print(f"  Dataspace: {args.dataspace}")
    print(f"  Strategy: {args.strategy}")

    # ── Authenticate ──
    print("\n=== Authenticate ===")
    src_token = get_access_token(src)
    dst_token = ""
    if not args.to_local:
        dst_token = get_access_token(dst)

    # ── Source stats ──
    if not args.skip_source_stats:
        print("\n=== Source dataspace stats ===")
        space_stats(src["etp_url"], IMAGE_SSL, args.dataspace,
                    partition=src["partition"], token=src_token,
                    dry_run=args.dry_run)

    # ── OSDU xdata for target dataspace ACL ──
    xdata = None
    if not args.to_local:
        xdata = {
            "legaltags": [dst["legal_tag"]],
            "otherRelevantDataCountries": [dst["countries"]],
            "owners": [dst["owners"]],
            "viewers": [dst["viewers"]],
        }

    # ── Execute strategy ──
    target_ds = args.target_dataspace or args.dataspace
    common = dict(
        src=src, dst=dst, dataspace=args.dataspace,
        src_token=src_token, dst_token=dst_token,
        dst_dataspace=target_ds, xdata=xdata,
        dry_run=args.dry_run,
    )

    if args.to_local or args.strategy == "epc":
        strategy_epc(**common, epc_dir=args.epc_dir, to_local=args.to_local)
    else:
        strategy_direct(**common)

    print("\n✓ Done.")


if __name__ == "__main__":
    main()
