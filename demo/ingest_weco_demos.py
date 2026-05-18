#!/usr/bin/env python3
"""
ingest_weco_demos.py — Ingest all WeCo demo datasets into RDDMS.

Creates dataspace `maap/weco` and populates it with:
  - WellboreTrajectoryRepresentation (geometry: XY + MD)
  - WellboreFrameRepresentation (log curves: GR, RT, DEN, etc.)
  - Discrete property arrays for facies/region data

Uses ORES's native osdu.py client (same as the web app).

Usage:
  # Ingest all demos into default instance:
  python demo/ingest_weco_demos.py

  # Ingest into a specific instance:
  python demo/ingest_weco_demos.py --instance interop

  # Only specific datasets:
  python demo/ingest_weco_demos.py --only coal quaternary bryson

  # Dry run (show what would be created):
  python demo/ingest_weco_demos.py --dry-run

  # Custom dataspace:
  python demo/ingest_weco_demos.py --dataspace maap/weco-test
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid as uuid_mod
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Paths ─────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
WECO_ROOT = REPO_ROOT / "weco_engine"   # submodule
if not WECO_ROOT.exists():
    # Try local weco checkout
    WECO_ROOT = Path(os.environ.get("WECO_ROOT", Path.home() / "weco"))

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(WECO_ROOT))

# ── RDDMS Schema Types ───────────────────────────────────────────────
TRAJ_TYPE = "resqml20.obj_WellboreTrajectoryRepresentation"
FRAME_TYPE = "resqml20.obj_WellboreFrameRepresentation"
CONT_PROP_TYPE = "resqml20.obj_ContinuousProperty"
DISC_PROP_TYPE = "resqml20.obj_DiscreteProperty"

# ── Default config ────────────────────────────────────────────────────
DEFAULT_DATASPACE = "maap/weco"
DEFAULT_INSTANCE = os.environ.get("DEFAULT_INSTANCE", "eqndev")

# ── Dataset catalogue ─────────────────────────────────────────────────
DATASETS = {
    "ds1.1": {"path": "data/data_set_1.1", "wells_file": "wells.txt",
              "title": "Synthetic Basic (3 wells)"},
    "ds1.2": {"path": "data/data_set_1.2", "wells_file": "wells.txt",
              "title": "Synthetic No-Crossing (4 wells)"},
    "ds1.3": {"path": "data/data_set_1.3", "wells_file": "wells.txt",
              "title": "Synthetic Distality (4 wells)"},
    "ds1.4": {"path": "data/data_set_1.4", "wells_file": "wells.txt",
              "title": "Synthetic Multi-Distality (5 wells)"},
    "ds1.5": {"path": "data/data_set_1.5", "wells_file": "wells.txt",
              "title": "Synthetic B3D (5 wells)"},
    "ds2": {"path": "data/data_set_2", "wells_file": "wells.txt",
            "title": "10-Well Synthetic"},
    "coal": {"path": "data/data_set_coal", "wells_file": "wells_10.txt",
             "title": "Coal Basin (10 wells)"},
    "quaternary": {"path": "data/data_set_quaternary", "wells_file": "wells_20.txt",
                   "title": "Quaternary Glacial (20 wells)"},
    "bryson": {"path": "data/data_set_bryson", "wells_file": "wells.txt",
               "title": "Bryson Appalachian (7 wells)"},
    "fluvial": {"path": "data/data_set_fluvial", "wells_file": "wells.txt",
                "title": "Fluvial Channel (20 wells)"},
    "shallow_marine": {"path": "data/data_set_shallow_marine", "wells_file": "wells.txt",
                       "title": "Shallow Marine (20 wells)"},
    "carbonate": {"path": "data/data_set_carbonate", "wells_file": "wells.txt",
                  "title": "Carbonate Platform (15 wells)"},
    "delta": {"path": "data/data_set_delta", "wells_file": "wells.txt",
              "title": "Deltaic System (20 wells)"},
    "eage2024": {"path": "data/data_set_eage2024", "wells_file": "wells.txt",
                 "title": "EAGE 2024 Real LAS (8 wells)"},
    "sigrun": {"path": "data/data_set_sigrun", "wells_file": "wells.txt",
               "title": "Sigrun North Sea (12 wells)"},
    "troll": {"path": "data/data_set_troll", "wells_file": "wells.txt",
              "title": "Troll North Sea (10 wells)"},
}


# ═══════════════════════════════════════════════════════════════════════
#  Auth (reuses ORES demo/_auth.py)
# ═══════════════════════════════════════════════════════════════════════

sys.path.insert(0, str(SCRIPT_DIR))
from _auth import load_instance, mint_from_env  # noqa: E402

import time
_token_cache: Optional[str] = None
_token_exp: float = 0.0


def get_token(instance_cfg: dict) -> str:
    global _token_cache, _token_exp
    if _token_cache and time.time() < _token_exp:
        return _token_cache
    _token_cache = mint_from_env(instance_cfg)
    _token_exp = time.time() + 3000
    return _token_cache


# ═══════════════════════════════════════════════════════════════════════
#  RDDMS Client (async, using osdu.py)
# ═══════════════════════════════════════════════════════════════════════

import httpx
import urllib.parse


class RDDMSClient:
    """Thin RDDMS v2 client for ingestion."""

    def __init__(self, host: str, partition: str, token_fn):
        self.host = host.rstrip("/")
        self.partition = partition
        self.token_fn = token_fn
        self._base = f"https://{host}/api/os-reservoir-ddms/v2" if "://" not in host else f"{host}/api/os-reservoir-ddms/v2"

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token_fn()}",
            "Content-Type": "application/json",
            "data-partition-id": self.partition,
            "Accept": "application/json",
        }

    async def create_dataspace(self, path: str, legal_tag: str,
                               owners: list, viewers: list, countries: list):
        """Create dataspace if not exists."""
        url = f"{self._base}/dataspaces"
        payload = [{
            "DataspaceId": path,
            "Path": path,
            "CustomData": {
                "legaltags": [legal_tag],
                "otherRelevantDataCountries": countries,
                "viewers": viewers,
                "owners": owners,
            }
        }]
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, headers=self._headers(), json=payload)
            if r.status_code == 409:
                print(f"  Dataspace '{path}' already exists (OK)")
                return
            r.raise_for_status()
            print(f"  Created dataspace '{path}'")

    async def begin_transaction(self, ds_path: str) -> str:
        enc = urllib.parse.quote(ds_path, safe="")
        url = f"{self._base}/dataspaces/{enc}/transactions"
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, headers=self._headers())
            r.raise_for_status()
            return r.text.strip().strip('"')

    async def commit_transaction(self, ds_path: str, tx_id: str):
        enc = urllib.parse.quote(ds_path, safe="")
        url = f"{self._base}/dataspaces/{enc}/transactions/{tx_id}"
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.put(url, headers=self._headers())
            r.raise_for_status()

    async def put_resources(self, ds_path: str, objects: list, tx_id: str):
        """PUT RESQML objects into dataspace."""
        enc = urllib.parse.quote(ds_path, safe="")
        url = f"{self._base}/dataspaces/{enc}/resources"
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.put(
                url, headers=self._headers(), json=objects,
                params={"transactionId": tx_id}
            )
            r.raise_for_status()
            return r.json() if r.text else {}

    async def put_array(self, ds_path: str, obj_type: str, obj_uuid: str,
                        path_in_resource: str, values: list, tx_id: str):
        """PUT array data for a resource."""
        enc = urllib.parse.quote(ds_path, safe="")
        url = (f"{self._base}/dataspaces/{enc}/resources/{obj_type}/{obj_uuid}"
               f"/arrays/{path_in_resource}")
        payload = {"values": values}
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.put(
                url, headers=self._headers(), json=payload,
                params={"transactionId": tx_id}
            )
            r.raise_for_status()


# ═══════════════════════════════════════════════════════════════════════
#  RESQML Object builders
# ═══════════════════════════════════════════════════════════════════════

def new_uuid() -> str:
    return str(uuid_mod.uuid4())


# Deterministic UUID namespace for WeCo demo data
# Using UUID5 so objects can be reliably found by demo_key + well_name
WECO_NAMESPACE = uuid_mod.UUID("a3f8c1e0-7b2d-4e5f-9a1c-6d8e0f2b4a7c")


def demo_uuid(demo_key: str, well_name: str, suffix: str = "") -> str:
    """Generate a deterministic UUID5 for a demo object.

    This ensures the same demo+well always gets the same UUID,
    allowing the web GUI to find ingested data without a lookup table.
    """
    seed = f"{demo_key}/{well_name}"
    if suffix:
        seed += f"/{suffix}"
    return str(uuid_mod.uuid5(WECO_NAMESPACE, seed))


def build_trajectory(well_name: str, well_uuid: str,
                     x: float, y: float, size: int,
                     md_values: list, dataset_tag: str) -> dict:
    """Build a WellboreTrajectoryRepresentation RESQML object."""
    return {
        "SchemaVersion": "2.0",
        "UUID": well_uuid,
        "Citation": {
            "Title": well_name,
            "Description": f"WeCo demo well from {dataset_tag}",
            "Format": "WeCo",
        },
        "MdUom": "m",
        "StartMd": md_values[0] if md_values else 0.0,
        "FinishMd": md_values[-1] if md_values else float(size),
        "MdDatum": {
            "ContentType": "resqml20.obj_MdDatum",
            "UUID": new_uuid(),
            "Title": f"{well_name}_MdDatum",
        },
        "Geometry": {
            "ControlPoints": [[x, y, md] for md in (md_values or list(range(size)))],
            "ControlPointCount": size,
        },
        "CustomData": {
            "WeCo_Dataset": dataset_tag,
            "WeCo_WellName": well_name,
            "SampleCount": size,
        }
    }


def build_frame(well_name: str, frame_uuid: str, traj_uuid: str,
                size: int, md_values: list, dataset_tag: str) -> dict:
    """Build a WellboreFrameRepresentation for log data."""
    return {
        "SchemaVersion": "2.0",
        "UUID": frame_uuid,
        "Citation": {
            "Title": f"{well_name}_Logs",
            "Description": f"Well log frame for {well_name}",
            "Format": "WeCo",
        },
        "NodeCount": size,
        "RepresentedInterpretation": {
            "ContentType": TRAJ_TYPE,
            "UUID": traj_uuid,
            "Title": well_name,
        },
        "NodeMd": {
            "UOM": "m",
            "Values": md_values,
        },
        "CustomData": {
            "WeCo_Dataset": dataset_tag,
            "WeCo_WellName": well_name,
        }
    }


def build_continuous_property(well_name: str, prop_uuid: str, frame_uuid: str,
                              log_name: str, values: list) -> dict:
    """Build a ContinuousProperty for a log curve (GR, RT, DEN, etc.)."""
    return {
        "SchemaVersion": "2.0",
        "UUID": prop_uuid,
        "Citation": {
            "Title": f"{well_name}_{log_name}",
            "Description": f"Log curve {log_name}",
            "Format": "WeCo",
        },
        "Count": 1,
        "IndexableElement": "nodes",
        "SupportingRepresentation": {
            "ContentType": FRAME_TYPE,
            "UUID": frame_uuid,
            "Title": f"{well_name}_Logs",
        },
        "PropertyKind": {
            "Title": log_name,
        },
        "PatchOfValues": [{
            "Values": {"PathInHdfFile": f"/RESQML/{prop_uuid}/values_patch0"},
        }],
        "CustomData": {
            "WeCo_LogName": log_name,
            "WeCo_WellName": well_name,
        }
    }


def build_discrete_property(well_name: str, prop_uuid: str, frame_uuid: str,
                            region_name: str, intervals: list, size: int) -> dict:
    """Build a DiscreteProperty for region/facies data.

    intervals: list of (region_id, start_sample, length) tuples from WeCo
    """
    # Convert WeCo region intervals to per-sample array
    values = [0] * size
    for rid, start, length in intervals:
        for i in range(start, min(start + length, size)):
            values[i] = rid

    return {
        "SchemaVersion": "2.0",
        "UUID": prop_uuid,
        "Citation": {
            "Title": f"{well_name}_{region_name}",
            "Description": f"Region/facies {region_name}",
            "Format": "WeCo",
        },
        "Count": 1,
        "IndexableElement": "nodes",
        "SupportingRepresentation": {
            "ContentType": FRAME_TYPE,
            "UUID": frame_uuid,
            "Title": f"{well_name}_Logs",
        },
        "PropertyKind": {
            "Title": region_name,
            "IsAbstract": False,
        },
        "PatchOfValues": [{
            "Values": {"PathInHdfFile": f"/RESQML/{prop_uuid}/values_patch0"},
        }],
        "CustomData": {
            "WeCo_RegionName": region_name,
            "WeCo_WellName": well_name,
            "WeCo_RegionIntervals": json.dumps(intervals),
        },
        "_array_values": values,  # transient: used for array write
    }


# ═══════════════════════════════════════════════════════════════════════
#  Main ingestion logic
# ═══════════════════════════════════════════════════════════════════════

async def ingest_dataset(client: RDDMSClient, ds_path: str,
                         ds_key: str, ds_info: dict, dry_run: bool = False):
    """Ingest one WeCo dataset into RDDMS."""
    from weco.data import WellList

    wells_path = WECO_ROOT / ds_info["path"] / ds_info["wells_file"]
    if not wells_path.exists():
        print(f"  SKIP {ds_key}: file not found ({wells_path})")
        return 0

    wl = WellList(str(wells_path))
    n_wells = wl.nbr_wells()
    print(f"\n  [{ds_key}] {ds_info['title']} — {n_wells} wells")

    if dry_run:
        for i in range(n_wells):
            w = wl.get_well(i)
            print(f"    {w.name}: {w.size} samples, data={list(w.data.keys())}, "
                  f"regions={list(w.region.keys())}")
        return n_wells

    # Start transaction
    tx_id = await client.begin_transaction(ds_path)
    print(f"    Transaction: {tx_id[:12]}...")

    total_objects = 0
    try:
        for i in range(n_wells):
            w = wl.get_well(i)

            # Generate deterministic UUIDs (same demo+well → same UUID)
            traj_uuid = demo_uuid(ds_key, w.name, "traj")
            frame_uuid = demo_uuid(ds_key, w.name, "frame")

            # Depth/MD
            md_values = list(w.data.get("Depth", w.data.get("DEPTH", [])))
            if not md_values:
                md_values = list(range(w.size))
            md_values = [float(v) for v in md_values[:w.size]]

            # Build trajectory
            traj_obj = build_trajectory(
                w.name, traj_uuid, w.x, w.y, w.size,
                md_values, ds_key
            )

            # Build frame
            frame_obj = build_frame(
                w.name, frame_uuid, traj_uuid,
                w.size, md_values, ds_key
            )

            # PUT trajectory and frame
            await client.put_resources(ds_path, [traj_obj], tx_id)
            await client.put_resources(ds_path, [frame_obj], tx_id)
            total_objects += 2

            # Continuous properties (log curves)
            skip_keys = {"Depth", "DEPTH", "X", "Y", "Z", "MD"}
            for log_name, values in w.data.items():
                if log_name in skip_keys or log_name.startswith("_"):
                    continue
                if not values:
                    continue

                prop_uuid = demo_uuid(ds_key, w.name, f"cont_{log_name}")
                prop_obj = build_continuous_property(
                    w.name, prop_uuid, frame_uuid, log_name,
                    [float(v) if v is not None else 0.0 for v in values[:w.size]]
                )
                await client.put_resources(ds_path, [prop_obj], tx_id)

                # Write array data
                arr_values = [float(v) if v is not None else 0.0 for v in values[:w.size]]
                await client.put_array(
                    ds_path, CONT_PROP_TYPE, prop_uuid,
                    f"values_patch0", arr_values, tx_id
                )
                total_objects += 1

            # Discrete properties (regions/facies)
            for region_name, intervals in w.region.items():
                prop_uuid = demo_uuid(ds_key, w.name, f"disc_{region_name}")
                prop_obj = build_discrete_property(
                    w.name, prop_uuid, frame_uuid,
                    region_name, intervals, w.size
                )
                arr_values = prop_obj.pop("_array_values")
                await client.put_resources(ds_path, [prop_obj], tx_id)

                await client.put_array(
                    ds_path, DISC_PROP_TYPE, prop_uuid,
                    f"values_patch0", arr_values, tx_id
                )
                total_objects += 1

            print(f"    ✓ {w.name}: {w.size} samples, "
                  f"{len(w.data)-len(skip_keys.intersection(w.data.keys()))} logs, "
                  f"{len(w.region)} regions")

        # Commit transaction
        await client.commit_transaction(ds_path, tx_id)
        print(f"    Committed: {total_objects} objects")
        return n_wells

    except Exception as e:
        print(f"    ERROR: {e}")
        try:
            enc = urllib.parse.quote(ds_path, safe="")
            async with httpx.AsyncClient(timeout=30) as hc:
                await hc.delete(
                    f"{client._base}/dataspaces/{enc}/transactions/{tx_id}",
                    headers=client._headers()
                )
            print(f"    Rolled back transaction")
        except Exception:
            pass
        raise


async def main():
    parser = argparse.ArgumentParser(description="Ingest WeCo demos into RDDMS")
    parser.add_argument("--instance", default=DEFAULT_INSTANCE,
                        help=f"Target OSDU instance (default: {DEFAULT_INSTANCE})")
    parser.add_argument("--dataspace", default=DEFAULT_DATASPACE,
                        help=f"Target dataspace (default: {DEFAULT_DATASPACE})")
    parser.add_argument("--only", nargs="+", metavar="DATASET",
                        help="Only ingest specific datasets (keys from catalogue)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be ingested without writing")
    parser.add_argument("--list", action="store_true",
                        help="List available datasets and exit")
    args = parser.parse_args()

    if args.list:
        print("Available WeCo demo datasets:")
        for key, info in DATASETS.items():
            print(f"  {key:20s} {info['title']}")
        return

    # Load instance config
    print(f"Target instance: {args.instance}")
    inst_cfg = load_instance(args.instance)
    print(f"  Host: {inst_cfg['host']}")
    print(f"  Partition: {inst_cfg['partition']}")

    # Resolve ACL from instance
    p = inst_cfg["partition"]
    legal_tag = inst_cfg.get("legal_tag") or f"{p}-private-default"
    owners = inst_cfg.get("owners") or [f"data.default.owners@{p}.dataservices.energy"]
    viewers = inst_cfg.get("viewers") or [f"data.default.viewers@{p}.dataservices.energy"]
    countries = inst_cfg.get("countries") or ["NO"]

    if isinstance(owners, str):
        owners = [owners]
    if isinstance(viewers, str):
        viewers = [viewers]

    print(f"  Legal tag: {legal_tag}")
    print(f"  Owners: {owners}")
    print(f"  Viewers: {viewers}")
    print(f"  Dataspace: {args.dataspace}")

    # Create client
    token_fn = lambda: get_token(inst_cfg)  # noqa: E731
    rddms = RDDMSClient(inst_cfg["host"], inst_cfg["partition"], token_fn)

    # Create dataspace
    if not args.dry_run:
        print(f"\nCreating dataspace '{args.dataspace}'...")
        await rddms.create_dataspace(
            args.dataspace, legal_tag, owners, viewers, countries
        )

    # Select datasets
    datasets_to_ingest = DATASETS
    if args.only:
        datasets_to_ingest = {k: v for k, v in DATASETS.items() if k in args.only}
        if not datasets_to_ingest:
            print(f"ERROR: No matching datasets. Available: {list(DATASETS.keys())}")
            return

    # Ingest each dataset
    total_wells = 0
    results = {}
    print(f"\nIngesting {len(datasets_to_ingest)} datasets...")

    for ds_key, ds_info in datasets_to_ingest.items():
        try:
            n = await ingest_dataset(rddms, args.dataspace, ds_key, ds_info,
                                     dry_run=args.dry_run)
            results[ds_key] = ("OK", n)
            total_wells += n
        except Exception as e:
            results[ds_key] = ("ERROR", str(e))
            print(f"  FAILED: {e}")

    # Summary
    print(f"\n{'='*60}")
    print(f"INGESTION COMPLETE: {total_wells} wells across {len(results)} datasets")
    print(f"Dataspace: {args.dataspace}")
    print(f"{'='*60}")
    for k, (status, detail) in results.items():
        icon = "✓" if status == "OK" else "✗"
        print(f"  {icon} {k:20s} {status} ({detail})")


if __name__ == "__main__":
    asyncio.run(main())
