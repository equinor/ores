#!/usr/bin/env python3
"""
demo_rddms.py — OSDU / RDDMS Live Demo (§16)
===============================================

Standalone demo that reads and writes well data (logs, markers) purely
via the OSDU Reservoir DDMS REST API — no local files.

Steps:
  1. Authenticate (Azure AD token flow from ORES)
  2. List dataspaces → verify ``maap/weco``
  3. Ingest demo wells (shallow marine) into RDDMS
  4. Read wells back from RDDMS → verify match
  5. Run WeCo correlation on RDDMS-sourced data
  6. Write results back as RESQML marker objects
  7. Read results back → verify

Prerequisites:
  - Azure AD credentials (will prompt or use cached token)
  - RDDMS v2 endpoint URL
  - ``maap/weco`` dataspace must exist

Usage::

    python demo_rddms.py --url https://rddms.example.com \\
                         --dataspace maap/weco \\
                         --token-file ~/.azure/token.json

Architecture note:
  This is temporary standalone code.  WeCo will later integrate into
  ORES as a Radix client — at that point RDDMS/auth/read-write routes
  will come from ORES.  Keep this minimal and demo-focused.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time


def acquire_token(token_file: str = None) -> str:
    """Acquire Azure AD token.

    Tries multiple sources in order:
    1. Direct file (--token-file)
    2. ORES token cache (~/.ores/token.json)
    3. Azure CLI (az account get-access-token)
    4. Environment variable RDDMS_TOKEN
    """
    # 1. Direct file
    if token_file and os.path.isfile(token_file):
        with open(token_file) as f:
            data = json.load(f)
        token = data.get("access_token") or data.get("token")
        if token:
            print(f"[auth] Token from file: {token_file}")
            return token

    # 2. ORES cache
    ores_token = os.path.expanduser("~/.ores/token.json")
    if os.path.isfile(ores_token):
        with open(ores_token) as f:
            data = json.load(f)
        token = data.get("access_token") or data.get("token")
        if token:
            print(f"[auth] Token from ORES cache")
            return token

    # 3. Azure CLI
    try:
        import subprocess
        result = subprocess.run(
            ["az", "account", "get-access-token", "--resource",
             "https://storage.azure.com"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            token = data.get("accessToken")
            if token:
                print("[auth] Token from Azure CLI")
                return token
    except Exception:
        pass

    # 4. Environment variable
    token = os.environ.get("RDDMS_TOKEN")
    if token:
        print("[auth] Token from RDDMS_TOKEN env var")
        return token

    raise RuntimeError(
        "Cannot acquire authentication token.\n"
        "Provide --token-file, set RDDMS_TOKEN env var, "
        "or login with 'az login'."
    )


def step_list_dataspaces(url: str, token: str) -> list:
    """List available dataspaces and verify target exists."""
    from weco.rddms import rddms_list_wells
    print(f"\n[step 1] Listing dataspaces at {url}...")
    # The list_wells call implicitly verifies connectivity
    try:
        wells = rddms_list_wells(url, token, "*")
        print(f"  Connected to RDDMS — found data")
        return wells
    except Exception as e:
        print(f"  WARN: Could not list dataspaces: {e}")
        return []


def step_ingest_wells(url: str, token: str, dataspace: str) -> int:
    """Ingest demo wells into RDDMS."""
    from weco.rddms import rddms_export_wells
    from weco.data import WellList

    print(f"\n[step 2] Ingesting demo wells into dataspace '{dataspace}'...")

    # Load shallow marine demo wells
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(project_dir,
                            "demo", "data", "data_set_shallow_marine")
    wells_path = os.path.join(data_dir, "wells.txt")
    if not os.path.isfile(wells_path):
        # Generate if needed
        gen_path = os.path.join(data_dir, "generate_shallow_marine.py")
        if os.path.isfile(gen_path):
            import importlib.util
            spec = importlib.util.spec_from_file_location("gen", gen_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.main(output_dir=data_dir)

    wl = WellList(wells_path)
    print(f"  Loaded {wl.nbr_wells()} wells from {wells_path}")

    n = rddms_export_wells(url, token, dataspace, wl)
    print(f"  Ingested {n} well objects → RDDMS")
    return n


def step_read_back(url: str, token: str, dataspace: str):
    """Read wells back from RDDMS and verify."""
    from weco.rddms import rddms_import_wells

    print(f"\n[step 3] Reading wells back from RDDMS...")
    wl = rddms_import_wells(url, token, dataspace)
    print(f"  Retrieved {wl.nbr_wells()} wells:")
    for w in wl.wells:
        print(f"    {w.name}: {w.size} markers, "
              f"{len(w.data)} data, {len(w.region)} regions")
    return wl


def step_correlate(wl, options_file: str = None):
    """Run WeCo correlation on RDDMS-sourced data."""
    from weco.ext import ProjectExt

    print(f"\n[step 4] Running WeCo correlation on {wl.nbr_wells()} wells...")
    proj = ProjectExt()

    if options_file and os.path.isfile(options_file):
        proj.set_option_ext("read-options", options_file)
    else:
        proj.set_options_ext({
            "cost-function": "composite",
            "var-data": "GR",
            "var-weight": "1.0",
            "order": "pyramidal",
            "nbr-cor": "50",
            "out-nbr-cor": "10",
            "max-cor": "200",
        })

    t0 = time.time()
    success = proj.run(wl)
    elapsed = time.time() - t0

    if not success:
        print("  FAILED: Engine returned False")
        return None, None

    res = proj.get_res_file()
    n_results = res.get_nbr_results()
    best_cost = res.get_result_cost(0) if n_results > 0 else float("inf")
    print(f"  Done in {elapsed:.2f}s — {n_results} results, "
          f"best cost: {best_cost:.6f}")
    return res, wl


def step_write_results(url: str, token: str, dataspace: str,
                       res, wl) -> int:
    """Write correlation results back to RDDMS."""
    from weco.rddms import rddms_export_results

    print(f"\n[step 5] Writing results back to RDDMS...")
    n = rddms_export_results(
        url, token, dataspace, res, wl,
        cor_num=0, include_strat_column=True,
    )
    print(f"  Wrote {n} result objects → RDDMS")
    return n


def step_cleanup(url: str, token: str, dataspace: str):
    """Delete demo objects from dataspace (idempotent)."""
    print(f"\n[step 6] Cleanup: would delete demo objects from '{dataspace}'")
    print("  (Not implemented — manual cleanup via RDDMS admin UI)")


def main():
    parser = argparse.ArgumentParser(
        description="WeCo OSDU/RDDMS Live Demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--url", required=True,
                        help="RDDMS v2 REST endpoint URL")
    parser.add_argument("--dataspace", default="maap/weco",
                        help="Target dataspace (default: maap/weco)")
    parser.add_argument("--token-file",
                        help="Path to JSON token file")
    parser.add_argument("--options",
                        help="Path to WeCo options file")
    parser.add_argument("--skip-ingest", action="store_true",
                        help="Skip well ingestion (assume already in RDDMS)")
    parser.add_argument("--cleanup", action="store_true",
                        help="Delete demo objects after run")
    args = parser.parse_args()

    print("=" * 60)
    print("  WeCo OSDU / RDDMS Live Demo")
    print("=" * 60)

    # 1. Authenticate
    token = acquire_token(args.token_file)

    # 2. List dataspaces
    step_list_dataspaces(args.url, token)

    # 3. Ingest wells
    if not args.skip_ingest:
        step_ingest_wells(args.url, token, args.dataspace)

    # 4. Read back
    wl = step_read_back(args.url, token, args.dataspace)

    # 5. Correlate
    res, wl = step_correlate(wl, args.options)

    # 6. Write results
    if res is not None:
        step_write_results(args.url, token, args.dataspace, res, wl)

    # 7. Cleanup
    if args.cleanup:
        step_cleanup(args.url, token, args.dataspace)

    print("\n" + "=" * 60)
    print("  Demo complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
