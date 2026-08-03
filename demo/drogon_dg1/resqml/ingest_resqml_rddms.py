#!/usr/bin/env python3
"""
ingest_resqml_rddms.py - Import RESQML 2.0.1 EPC files into the
OSDU Reservoir DDMS via the open-etp Docker client image.

Supports two modes:
  --local   Target a local RDDMS at ws://localhost:9100 (no auth needed)
  (default) Target the cloud OSDU RDDMS via wss:// (AAD auth from .env)

Steps:
  1. (cloud only) Authenticate via AAD refresh_token grant
  2. Create a dataspace (if not already present)
  3. Import each EPC file into the dataspace
  4. List dataspaces and print stats to confirm

Prerequisites:
  - Docker Desktop running (docker info must succeed)
  - Docker image tagged as 'osdu-etp-client' (local) or 'osdu-etp-sslclient' (cloud)
  - For cloud mode: .env file with refresh_token, tenant, client_id, etc.

Usage - local RDDMS (localhost:9100):
  py demo/drogon_dg1/resqml/ingest_resqml_rddms.py --local
  py demo/drogon_dg1/resqml/ingest_resqml_rddms.py --local --dry-run
  py demo/drogon_dg1/resqml/ingest_resqml_rddms.py --local --dataspace demo/Drogon

Usage - cloud OSDU RDDMS:
  py demo/drogon_dg1/resqml/ingest_resqml_rddms.py
  py demo/drogon_dg1/resqml/ingest_resqml_rddms.py --dataspace maap/drogon-resqml
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent          # demo/drogon_dg1/resqml/
DROGON = HERE.parent                            # demo/drogon_dg1/
REPO_ROOT = DROGON.parent.parent                # ores/

# EPC files to import (order matters: tables first, then activity)
EPC_FILES = [
    HERE / "drogon_tables.epc",
    HERE / "drogon_activity.epc",
]

# Docker images - tagged locally for convenience
IMAGE_LOCAL = "osdu-etp-client"          # non-SSL, for ws://localhost
IMAGE_CLOUD = "osdu-etp-sslclient"      # SSL-enabled, for wss://

# Defaults
LOCAL_ETP_URL     = "ws://localhost:9100/"
DEFAULT_DATASPACE = "maap/drogon-resqml"
LOCAL_DATASPACE   = "demo/Drogon"


# ─────────────── Auth & env (via central _auth module) ────────────────────── #

import sys as _sys
_sys.path.insert(0, str(REPO_ROOT / "demo"))
from _auth import (                                              # noqa: E402
    load_env as _auth_load_env,
    load_instance as _auth_load_instance,
    get_token as _auth_get_token,
    mint_from_env as get_access_token,
)


def load_env_from_instance(name: str) -> Dict[str, str]:
    """Build an env dict from a named instance (k8s/secret+configmap).

    Returns the same key layout as load_env() so the rest of the script
    works unchanged.
    """
    inst = _auth_load_instance(name)
    host = inst["host"].rstrip("/")
    partition = inst["partition"]
    owners = inst.get("owners", [])
    viewers = inst.get("viewers", [])
    return {
        "host":          host,
        "partition":     partition,
        "tenant":        inst.get("tenant", ""),
        "client_id":     inst.get("client_id", ""),
        "client_secret": inst.get("client_secret", ""),
        "refresh_token": inst.get("refresh_token", ""),
        "scope":         inst.get("scope", ""),
        "etp_url":       f"wss://{host.replace('https://', '')}/api/reservoir-ddms-etp/v2/",
        "legal_tag":     inst.get("legal_tag", f"{partition}-public-usa-dataset-1"),
        "owners":        owners[0] if owners else f"data.default.owners@{partition}.dataservices.energy",
        "viewers":       viewers[0] if viewers else f"data.default.viewers@{partition}.dataservices.energy",
    }


def load_env(path: Path) -> Dict[str, str]:
    """Load env from .env file, with extra ETP/legal fields.

    Delegates core auth fields to the central _auth module, then adds
    RDDMS-specific fields (etp_url, legal_tag, owners, viewers).
    """
    env = _auth_load_env([str(path)])
    host = env.get("host", "").rstrip("/")
    partition = env.get("partition", "")
    env["etp_url"]   = f"wss://{host.replace('https://', '')}/api/reservoir-ddms-etp/v2/"
    dom = f"{partition}.dataservices.energy"
    env["legal_tag"] = f"{partition}-equinor-private-default"
    env["owners"]    = f"data.default.owners@{dom}"
    env["viewers"]   = f"data.default.viewers@{dom}"
    return env


# ─────────────── Docker helpers ───────────────────────────────────────────── #

def run_docker(args: List[str], *, dry_run: bool = False, label: str = "") -> int:
    cmd = ["docker"] + args
    if label:
        print(f"\n--- {label} ---")
    display = " ".join(f'"{a}"' if " " in a else a for a in cmd)
    if dry_run:
        print(f"  [DRY-RUN] {display}")
        return 0
    print(f"  $ {display}")
    result = subprocess.run(cmd, capture_output=False, text=True)
    return result.returncode


def etp_base_cmd(server_url: str, *, partition: str = "",
                 token: str = "") -> str:
    """Build the common openETPServer space CLI flags."""
    parts = [f"--server-url {server_url}"]
    if partition:
        parts.append(f"--data-partition-id {partition}")
    if token:
        parts.append(f"--auth bearer --jwt-token {token}")
    return " ".join(parts)


def docker_run_args(image: str, inner_cmd: str, *,
                    network_host: bool = False,
                    volume: str = "") -> List[str]:
    """Build the docker run argument list."""
    args = ["run", "--rm"]
    if network_host:
        args.append("--network=host")
    if volume:
        args.extend(["-v", volume])
    args.extend(["--entrypoint=sh", image, "-c", inner_cmd])
    return args


# ── Dataspace operations ──────────────────────────────────────────────────── #

def list_dataspaces(server_url: str, image: str, *,
                    network_host: bool = False,
                    partition: str = "", token: str = "",
                    dry_run: bool = False) -> int:
    base = etp_base_cmd(server_url, partition=partition, token=token)
    inner = f"/bin/openETPServer space {base} --list"
    return run_docker(
        docker_run_args(image, inner, network_host=network_host),
        dry_run=dry_run, label="List dataspaces"
    )


def create_dataspace(server_url: str, image: str, dataspace: str, *,
                     network_host: bool = False,
                     partition: str = "", token: str = "",
                     xdata: Optional[Dict] = None,
                     dry_run: bool = False) -> int:
    base = etp_base_cmd(server_url, partition=partition, token=token)
    inner = f"/bin/openETPServer space {base} --new -s {dataspace}"
    if xdata:
        xdata_json = json.dumps(xdata)
        inner += f" --xdata '{xdata_json}'"
    return run_docker(
        docker_run_args(image, inner, network_host=network_host),
        dry_run=dry_run, label=f"Create dataspace '{dataspace}'"
    )


def import_epc(server_url: str, image: str, dataspace: str, epc_path: Path, *,
               network_host: bool = False,
               partition: str = "", token: str = "",
               dry_run: bool = False) -> int:
    base = etp_base_cmd(server_url, partition=partition, token=token)
    epc_name = epc_path.name
    mount_dir = str(epc_path.parent).replace("\\", "/")
    inner = f"/bin/openETPServer space {base} -s {dataspace} --import-epc /data/{epc_name}"
    return run_docker(
        docker_run_args(image, inner,
                        network_host=network_host,
                        volume=f"{mount_dir}:/data"),
        dry_run=dry_run, label=f"Import {epc_name}"
    )


def dataspace_stats(server_url: str, image: str, dataspace: str, *,
                    network_host: bool = False,
                    partition: str = "", token: str = "",
                    dry_run: bool = False) -> int:
    base = etp_base_cmd(server_url, partition=partition, token=token)
    inner = f"/bin/openETPServer space {base} -s {dataspace} --stats"
    return run_docker(
        docker_run_args(image, inner, network_host=network_host),
        dry_run=dry_run, label=f"Stats for '{dataspace}'"
    )


# ─────────────── main ─────────────── #

def main():
    parser = argparse.ArgumentParser(
        description="Import RESQML EPC files into OSDU Reservoir DDMS via Docker ETP client"
    )
    parser.add_argument("--local", action="store_true",
                        help="Target local RDDMS at ws://localhost:9100 (no auth)")
    parser.add_argument("--server-url",
                        help="Override ETP server URL (default depends on --local)")
    parser.add_argument("--instance", "-i",
                        help="Named instance from k8s/secret+configmap (e.g. preship, eqndev)")
    parser.add_argument("--env-file", default=str(REPO_ROOT / ".env"),
                        help="Path to .env file - cloud mode only (default: <repo>/.env)")
    parser.add_argument("--dataspace",
                        help=f"Dataspace path (default: {LOCAL_DATASPACE} local, "
                             f"{DEFAULT_DATASPACE} cloud)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print Docker commands without executing")
    parser.add_argument("--skip-create", action="store_true",
                        help="Skip creating the dataspace (use if it already exists)")
    parser.add_argument("--epc", nargs="*",
                        help="Specific EPC files to import (default: all in resqml/)")
    args = parser.parse_args()

    # ── Resolve mode ──
    is_local = args.local
    if is_local:
        server_url    = args.server_url or LOCAL_ETP_URL
        image         = IMAGE_LOCAL
        network_host  = True
        partition     = ""
        token         = ""
        dataspace     = args.dataspace or LOCAL_DATASPACE
        xdata         = None          # no ACL for local
    else:
        # Prefer --instance over --env-file
        if args.instance:
            env = load_env_from_instance(args.instance)
        else:
            env = load_env(Path(args.env_file))
        server_url    = args.server_url or env["etp_url"]
        image         = IMAGE_CLOUD
        network_host  = False
        partition     = env["partition"]
        dataspace     = args.dataspace or DEFAULT_DATASPACE
        countries     = ["US"] if args.instance == "preship" else ["NO"]
        xdata         = {
            "legaltags": [env["legal_tag"]],
            "otherRelevantDataCountries": countries,
            "owners": [env["owners"]],
            "viewers": [env["viewers"]],
        }

    mode_label = "LOCAL" if is_local else "CLOUD"
    print(f"=== Mode: {mode_label} ===")
    print(f"  Server URL: {server_url}")
    print(f"  Image:      {image}")
    print(f"  Dataspace:  {dataspace}")

    # ── Auth (cloud only) ──
    if not is_local:
        print("\n=== Authenticate ===")
        token = get_access_token(env)

    # Common kwargs for all docker operations
    kw = dict(server_url=server_url, image=image,
              network_host=network_host, partition=partition,
              token=token, dry_run=args.dry_run)

    # ── List existing dataspaces ──
    print("\n=== List dataspaces ===")
    list_dataspaces(**kw)

    # ── Create dataspace ──
    if not args.skip_create:
        rc = create_dataspace(**kw, dataspace=dataspace, xdata=xdata)
        if rc != 0 and not args.dry_run:
            print("  WARNING: create may have failed (dataspace might already exist)")
    else:
        print(f"\n  Skipping dataspace creation (using '{dataspace}')")

    # ── Import EPC files ──
    epc_files = [Path(p) for p in args.epc] if args.epc else EPC_FILES
    print(f"\n=== Import {len(epc_files)} EPC file(s) ===")
    for epc in epc_files:
        if not epc.exists() and not args.dry_run:
            print(f"  ERROR: {epc} not found - run gen_resqml.py first")
            sys.exit(1)
        rc = import_epc(**kw, dataspace=dataspace, epc_path=epc)
        if rc != 0 and not args.dry_run:
            print(f"  ERROR: import of {epc.name} failed (exit code {rc})")
            sys.exit(1)

    # ── Verify ──
    print(f"\n=== Verify ===")
    dataspace_stats(**kw, dataspace=dataspace)

    print("\nDone.")


if __name__ == "__main__":
    main()
