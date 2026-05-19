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

# ── Dataset catalogue (matches weco.api._DEMO_CATALOGUE) ─────────────
DATASETS = {
    "ds1.1": {"path": "demo/data/data_set_1.1", "wells_file": "wells.txt",
              "title": "Data Set 1.1 – Variance Weights"},
    "ds1.2": {"path": "demo/data/data_set_1.2", "wells_file": "wells.txt",
              "title": "Data Set 1.2 – No-Crossing Regions"},
    "ds1.3": {"path": "demo/data/data_set_1.3", "wells_file": "wells_A.txt",
              "title": "Data Set 1.3 – Same-Region Cost"},
    "ds1.4": {"path": "demo/data/data_set_1.4", "wells_file": "wells_A.weco",
              "title": "Data Set 1.4 – Multi-Distality"},
    "ds1.5": {"path": "demo/data/data_set_1.5", "wells_file": "wells.txt",
              "title": "Data Set 1.5 – Polarity / Dip"},
    "ds2": {"path": "demo/data/data_set_2", "wells_file": "wells.txt",
            "title": "Data Set 2 – Distance / Gap Cost"},
    "ds3": {"path": "demo/data/data_set_3", "wells_file": "wells.txt",
            "title": "Data Set 3 – Distality / Facies"},
    "ds4": {"path": "demo/data/data_set_4", "wells_file": "wells.txt",
            "title": "Data Set 4 – Biozone Constraint"},
    "coal": {"path": "demo/data/data_set_coal", "wells_file": "wells_10.txt",
             "title": "Coal Basin – Seam Correlation"},
    "quaternary": {"path": "demo/data/data_set_quaternary", "wells_file": "wells_20.txt",
                   "title": "Quaternary – Hydrogeology"},
    "shallow_marine": {"path": "demo/data/data_set_shallow_marine", "wells_file": "wells.txt",
                       "title": "Shallow Marine – Reservoir"},
    "bryson": {"path": "demo/data/data_set_bryson", "wells_file": "wells.txt",
               "title": "Bryson – Appalachian Basin"},
    "fluvial": {"path": "demo/data/data_set_fluvial", "wells_file": "wells.txt",
                "title": "Fluvial – Channel Belt"},
    "delta": {"path": "demo/data/data_set_delta", "wells_file": "wells.txt",
              "title": "Delta – Deltaic System"},
    "sigrun": {"path": "demo/data/data_set_sigrun", "wells_file": "wells.txt",
               "title": "Sigrun – North Sea"},
    "troll": {"path": "demo/data/data_set_troll", "wells_file": "wells.txt",
              "title": "Troll – North Sea"},
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
        self._base = f"https://{host}/api/reservoir-ddms/v2" if "://" not in host else f"{host}/api/reservoir-ddms/v2"

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
            if r.status_code == 400 and "already exists" in (r.text or ""):
                print(f"  Dataspace '{path}' already exists (OK)")
                return
            if r.status_code >= 400:
                print(f"  !! create_dataspace {r.status_code}: {r.text}")
            r.raise_for_status()
            print(f"  Created dataspace '{path}'")

    async def begin_transaction(self, ds_path: str) -> str:
        enc = urllib.parse.quote(ds_path, safe="")
        url = f"{self._base}/dataspaces/{enc}/transactions"
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, headers=self._headers())
            if r.status_code >= 400:
                print(f"  !! begin_transaction {r.status_code}: {r.text[:500]}")
            r.raise_for_status()
            return r.text.strip().strip('"')

    async def commit_transaction(self, ds_path: str, tx_id: str):
        enc = urllib.parse.quote(ds_path, safe="")
        url = f"{self._base}/dataspaces/{enc}/transactions/{tx_id}"
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.put(url, headers=self._headers())
            if r.status_code >= 400:
                print(f"  !! commit_transaction {r.status_code}: {r.text[:1000]}")
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
            if r.status_code >= 400:
                print(f"  !! put_resources {r.status_code}: {r.text[:500]}")
            r.raise_for_status()
            return r.json() if r.text else {}

    async def put_arrays(self, ds_path: str, array_defs: list, tx_id: str):
        """PUT array data (bulk) to dataspace."""
        enc = urllib.parse.quote(ds_path, safe="")
        url = f"{self._base}/dataspaces/{enc}/resources/arrays"
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.put(
                url, headers=self._headers(),
                content=json.dumps(array_defs),
                params={"transactionId": tx_id}
            )
            if r.status_code >= 400:
                print(f"  !! put_arrays {r.status_code}: {r.text[:500]}")
            r.raise_for_status()


# ═══════════════════════════════════════════════════════════════════════
#  RESQML JSON builders (RDDMS v2 format)
# ═══════════════════════════════════════════════════════════════════════

from datetime import datetime, timezone

def new_uuid() -> str:
    return str(uuid_mod.uuid4())


# Deterministic UUID namespace for WeCo demo data
WECO_NAMESPACE = uuid_mod.UUID("a3f8c1e0-7b2d-4e5f-9a1c-6d8e0f2b4a7c")

# HDF proxy UUID (shared across all objects in this ingestion)
HDF_PROXY_UUID = str(uuid_mod.uuid5(WECO_NAMESPACE, "hdf_proxy"))


def demo_uuid(demo_key: str, well_name: str, suffix: str = "") -> str:
    """Deterministic UUID5 for a demo object."""
    seed = f"{demo_key}/{well_name}"
    if suffix:
        seed += f"/{suffix}"
    return str(uuid_mod.uuid5(WECO_NAMESPACE, seed))


def _citation(title: str) -> dict:
    return {
        "$type": "eml20.Citation",
        "Title": title,
        "Originator": "weco-ingest",
        "Creation": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "Format": "WeCo:ingest",
    }


def _data_object_ref(resqml_type: str, uid: str, title: str) -> dict:
    """DataObjectReference as expected by RDDMS."""
    # Determine content-type string
    if resqml_type.startswith("resqml"):
        ns = resqml_type.split(".")[0]
        bare = resqml_type.split(".", 1)[1]
        ver = ns.replace("resqml", "")
        ver = f"{ver[0]}.{ver[1]}" if len(ver) == 2 else ver
        ct = f"application/x-resqml+xml;version={ver};type={bare}"
    elif resqml_type.startswith("eml"):
        ns = resqml_type.split(".")[0]
        bare = resqml_type.split(".", 1)[1]
        ver = ns.replace("eml", "")
        ver = f"{ver[0]}.{ver[1]}" if len(ver) == 2 else ver
        ct = f"application/x-eml+xml;version={ver};type={bare}"
    else:
        bare = resqml_type if resqml_type.startswith("obj_") else f"obj_{resqml_type}"
        ct = f"application/x-resqml+xml;version=2.0;type={bare}"
    return {
        "$type": "eml20.DataObjectReference",
        "ContentType": ct,
        "Title": title,
        "UUID": uid,
    }


def _hdf5_dataset(path: str) -> dict:
    return {
        "$type": "eml20.Hdf5Dataset",
        "PathInHdfFile": path,
        "HdfProxy": _data_object_ref(
            "eml20.obj_EpcExternalPartReference", HDF_PROXY_UUID, "HDF"),
    }


def _h5_path(rep_uuid: str, dataset: str) -> str:
    return f"/RESQML/{rep_uuid}/{dataset}"


def _base_object(rtype: str, uid: str, title: str) -> dict:
    return {
        "$type": rtype,
        "SchemaVersion": "2.0",
        "Uuid": uid,
        "Citation": _citation(title),
    }


def _array_def(values: list, dtype: str, hdf_path: str) -> dict:
    """Build an array definition for put_arrays."""
    if dtype == "float":
        atype = "Float64Array"
        data = [float(v) for v in values]
    else:
        atype = "Int32Array"
        data = [int(v) for v in values]
    dims = [len(data)]
    return {
        "ContainerType": "eml20.obj_EpcExternalPartReference",
        "ContainerUuid": HDF_PROXY_UUID,
        "PathInResource": hdf_path,
        "Dimensions": dims,
        "Data": data,
        "ArrayType": atype,
    }


def _point3d(x: float, y: float, z: float) -> dict:
    return {
        "$type": "resqml20.Point3d",
        "Coordinate1": x,
        "Coordinate2": y,
        "Coordinate3": z,
    }


CRS_UUID = str(uuid_mod.uuid5(WECO_NAMESPACE, "crs"))


def _crs_ref() -> dict:
    return _data_object_ref("resqml20.obj_LocalDepth3dCrs", CRS_UUID, "WeCo CRS")


def build_crs() -> dict:
    """Build a LocalDepth3dCrs object (needed as reference)."""
    obj = _base_object("resqml20.obj_LocalDepth3dCrs", CRS_UUID, "WeCo CRS")
    obj["ArealRotation"] = {"$type": "eml20.PlaneAngleMeasure", "Value": 0.0, "Uom": "rad"}
    obj["ProjectedAxisOrder"] = "easting northing"
    obj["ProjectedUom"] = "m"
    obj["VerticalUom"] = "m"
    obj["VerticalIsUp"] = False
    obj["XOffset"] = 0.0
    obj["YOffset"] = 0.0
    obj["ZOffset"] = 0.0
    return obj


def build_hdf_proxy() -> dict:
    """Build the EpcExternalPartReference (HDF proxy) object."""
    obj = _base_object("eml20.obj_EpcExternalPartReference", HDF_PROXY_UUID, "HDF")
    obj["MimeType"] = "application/x-hdf5"
    return obj


def build_well_objects(well_name: str, ds_key: str,
                       x: float, y: float, size: int,
                       md_values: list, data: dict, region: dict):
    """Build all RESQML objects + array defs for one well.

    Returns (json_objects: list[dict], array_defs: list[dict])
    """
    traj_uuid = demo_uuid(ds_key, well_name, "traj")
    feat_uuid = demo_uuid(ds_key, well_name, "feat")
    interp_uuid = demo_uuid(ds_key, well_name, "interp")
    datum_uuid = demo_uuid(ds_key, well_name, "datum")
    frame_uuid = demo_uuid(ds_key, well_name, "frame")

    json_objs = []
    arrs = []

    # ── Feature ──
    feat = _base_object("resqml20.obj_WellboreFeature", feat_uuid, well_name)
    json_objs.append(feat)

    # ── Interpretation ──
    interp = _base_object("resqml20.obj_WellboreInterpretation", interp_uuid, well_name)
    interp["InterpretedFeature"] = _data_object_ref(
        "resqml20.obj_WellboreFeature", feat_uuid, well_name)
    interp["IsDrilled"] = False
    json_objs.append(interp)

    # ── MdDatum ──
    datum = _base_object("resqml20.obj_MdDatum", datum_uuid, f"{well_name} md datum")
    datum["Location"] = _point3d(x, y, 0.0)
    datum["MdReference"] = "kelly bushing"
    datum["LocalCrs"] = _crs_ref()
    json_objs.append(datum)

    # ── Trajectory ──
    pts_path = _h5_path(traj_uuid, "controlPoints")
    md_path = _h5_path(traj_uuid, "controlPointParameters")

    rep = _base_object(
        "resqml20.obj_WellboreTrajectoryRepresentation", traj_uuid, well_name)
    rep["RepresentedInterpretation"] = _data_object_ref(
        "resqml20.obj_WellboreInterpretation", interp_uuid, well_name)
    rep["MdDatum"] = _data_object_ref(
        "resqml20.obj_MdDatum", datum_uuid, f"{well_name} md datum")
    rep["MdUom"] = "m"
    rep["StartMd"] = md_values[0] if md_values else 0.0
    rep["FinishMd"] = md_values[-1] if md_values else float(size)
    rep["Geometry"] = {
        "$type": "resqml20.ParametricLineGeometry",
        "LocalCrs": _crs_ref(),
        "KnotCount": size,
        "LineKindIndex": 1,
        "ControlPoints": {
            "$type": "resqml20.Point3dHdf5Array",
            "Coordinates": _hdf5_dataset(pts_path),
        },
        "ControlPointParameters": {
            "$type": "resqml20.DoubleHdf5Array",
            "Values": _hdf5_dataset(md_path),
        },
    }
    json_objs.append(rep)

    # Arrays for trajectory: control points (N*3 flattened) and MD
    pts_flat = []
    for md in md_values:
        pts_flat.extend([x, y, md])
    arrs.append({
        "ContainerType": "eml20.obj_EpcExternalPartReference",
        "ContainerUuid": HDF_PROXY_UUID,
        "PathInResource": pts_path,
        "Dimensions": [size, 3],
        "Data": [float(v) for v in pts_flat],
        "ArrayType": "Float64Array",
    })
    arrs.append(_array_def(md_values, "float", md_path))

    # ── WellboreFrameRepresentation (log frame) ──
    frame_md_path = _h5_path(frame_uuid, "nodeMd")
    frame = _base_object(
        "resqml20.obj_WellboreFrameRepresentation", frame_uuid, f"{well_name}_Logs")
    frame["RepresentedInterpretation"] = _data_object_ref(
        "resqml20.obj_WellboreInterpretation", interp_uuid, well_name)
    frame["Trajectory"] = _data_object_ref(
        "resqml20.obj_WellboreTrajectoryRepresentation", traj_uuid, well_name)
    frame["NodeCount"] = size
    frame["NodeMd"] = {
        "$type": "resqml20.DoubleHdf5Array",
        "Values": _hdf5_dataset(frame_md_path),
    }
    json_objs.append(frame)
    arrs.append(_array_def(md_values, "float", frame_md_path))

    # ── Continuous properties (log curves) ──
    skip_keys = {"Depth", "DEPTH", "X", "Y", "Z", "MD"}
    for log_name, values in data.items():
        if log_name in skip_keys or log_name.startswith("_"):
            continue
        if not values:
            continue

        prop_uuid = demo_uuid(ds_key, well_name, f"cont_{log_name}")
        vals_path = _h5_path(prop_uuid, "values_patch0")

        prop = _base_object("resqml20.obj_ContinuousProperty", prop_uuid,
                            f"{well_name}_{log_name}")
        prop["Count"] = 1
        prop["IndexableElement"] = "nodes"
        prop["SupportingRepresentation"] = _data_object_ref(
            "resqml20.obj_WellboreFrameRepresentation", frame_uuid,
            f"{well_name}_Logs")
        prop["UnitOfMeasure"] = "m"
        prop["PropertyKind"] = {
            "$type": "resqml20.StandardPropertyKind",
            "Kind": "continuous",
        }
        float_vals = [float(v) if v is not None else 0.0 for v in values[:size]]
        prop["PatchOfValues"] = [{
            "$type": "resqml20.PatchOfValues",
            "RepresentationPatchIndex": 0,
            "Values": {
                "$type": "resqml20.DoubleHdf5Array",
                "Values": _hdf5_dataset(vals_path),
            },
        }]
        prop["MinimumValue"] = [min(float_vals)]
        prop["MaximumValue"] = [max(float_vals)]
        json_objs.append(prop)
        arrs.append(_array_def(float_vals, "float", vals_path))

    # ── Discrete properties (regions/facies) ──
    for region_name, intervals in region.items():
        prop_uuid = demo_uuid(ds_key, well_name, f"disc_{region_name}")
        vals_path = _h5_path(prop_uuid, "values_patch0")

        # Convert WeCo region intervals to per-sample array
        int_values = [0] * size
        for rid, start, length in intervals:
            for i in range(start, min(start + length, size)):
                int_values[i] = rid

        prop = _base_object("resqml20.obj_DiscreteProperty", prop_uuid,
                            f"{well_name}_{region_name}")
        prop["Count"] = 1
        prop["IndexableElement"] = "nodes"
        prop["SupportingRepresentation"] = _data_object_ref(
            "resqml20.obj_WellboreFrameRepresentation", frame_uuid,
            f"{well_name}_Logs")
        prop["PropertyKind"] = {
            "$type": "resqml20.StandardPropertyKind",
            "Kind": "discrete",
        }
        prop["PatchOfValues"] = [{
            "$type": "resqml20.PatchOfValues",
            "RepresentationPatchIndex": 0,
            "Values": {
                "$type": "resqml20.IntegerHdf5Array",
                "NullValue": -99999,
                "Values": _hdf5_dataset(vals_path),
            },
        }]
        prop["MinimumValue"] = [min(int_values)]
        prop["MaximumValue"] = [max(int_values)]
        json_objs.append(prop)
        arrs.append(_array_def(int_values, "int", vals_path))

    return json_objs, arrs


# ═══════════════════════════════════════════════════════════════════════
#  Strat Column builder
# ═══════════════════════════════════════════════════════════════════════

def build_strat_column(col_uuid: str, col_name: str,
                       ranks: list, horizons: list = None):
    """Build StratigraphicColumn + ranks + units + horizons.

    Parameters
    ----------
    col_uuid : str
        UUID for the column object.
    col_name : str
        Title for the column.
    ranks : list of dicts
        Each rank: {"name": str, "units": [{"name": str, ...}, ...]}
    horizons : list of dicts, optional
        Each horizon: {"name": str, "feature_name": str (optional)}

    Returns (json_objects, [])  — no arrays needed.
    """
    json_objs = []
    hz_uuids = {}  # name → (hz_uuid, feat_uuid)
    unit_uuids = {}  # name → unit_uuid
    rank_uuids = []

    # ── Horizons ──
    for hz in (horizons or []):
        feat_uuid = new_uuid()
        hz_uuid = new_uuid()
        hz_name = hz["name"]
        feat_name = hz.get("feature_name", hz_name)
        hz_uuids[hz_name] = (hz_uuid, feat_uuid)

        feat = _base_object("resqml20.obj_BoundaryFeature", feat_uuid, feat_name)
        json_objs.append(feat)

        interp = _base_object("resqml20.obj_HorizonInterpretation", hz_uuid, hz_name)
        interp["Domain"] = "depth"
        interp["InterpretedFeature"] = _data_object_ref(
            "resqml20.obj_BoundaryFeature", feat_uuid, feat_name)
        json_objs.append(interp)

    # ── Units per rank ──
    for rk in ranks:
        for unit in rk.get("units", []):
            feat_uuid = new_uuid()
            unit_uuid = new_uuid()
            unit_name = unit["name"]
            feat_name = unit.get("feature_name", unit_name)
            unit_uuids[unit_name] = unit_uuid

            feat = _base_object("resqml20.obj_GeologicUnitFeature", feat_uuid, feat_name)
            json_objs.append(feat)

            interp = _base_object(
                "resqml20.obj_StratigraphicUnitInterpretation", unit_uuid, unit_name)
            interp["InterpretedFeature"] = _data_object_ref(
                "resqml20.obj_GeologicUnitFeature", feat_uuid, feat_name)
            json_objs.append(interp)

    # ── Ranks ──
    for rk in ranks:
        rk_uuid = new_uuid()
        rank_uuids.append(rk_uuid)

        rk_obj = _base_object(
            "resqml20.obj_StratigraphicColumnRankInterpretation",
            rk_uuid, rk["name"])
        rk_obj["OrderingCriteria"] = "olderToYounger"

        unit_refs = []
        for unit in rk.get("units", []):
            u_uid = unit_uuids.get(unit["name"], "")
            if u_uid:
                unit_refs.append(_data_object_ref(
                    "resqml20.obj_StratigraphicUnitInterpretation",
                    u_uid, unit["name"]))
        if unit_refs:
            rk_obj["StratigraphicUnits"] = unit_refs
        json_objs.append(rk_obj)

    # ── Column ──
    col = _base_object("resqml20.obj_StratigraphicColumn", col_uuid, col_name)
    rank_refs = []
    for i, rk_uid in enumerate(rank_uuids):
        rk_name = ranks[i]["name"]
        rank_refs.append(_data_object_ref(
            "resqml20.obj_StratigraphicColumnRankInterpretation",
            rk_uid, rk_name))
    if rank_refs:
        col["Ranks"] = rank_refs
    json_objs.append(col)

    return json_objs, []  # no arrays


# ═══════════════════════════════════════════════════════════════════════
#  Well Markers (WellboreMarkerFrameRepresentation) builder
# ═══════════════════════════════════════════════════════════════════════

def build_marker_frame(frame_uuid: str, well_name: str,
                       traj_uuid: str, interp_uuid: str,
                       marker_names: list, marker_mds: list):
    """Build a WellboreMarkerFrameRepresentation.

    Parameters
    ----------
    frame_uuid : str
        UUID for this marker frame object.
    well_name : str
        Well name (for title).
    traj_uuid : str
        UUID of the parent WellboreTrajectoryRepresentation.
    interp_uuid : str
        UUID of the parent WellboreInterpretation.
    marker_names : list[str]
        Names of the markers (horizon names).
    marker_mds : list[float]
        Measured depths at which the markers are placed.

    Returns (json_objects, array_defs)
    """
    json_objs = []
    arrs = []

    md_path = _h5_path(frame_uuid, "nodeMd")

    frame = _base_object(
        "resqml20.obj_WellboreMarkerFrameRepresentation",
        frame_uuid, f"{well_name}_Markers")
    frame["Trajectory"] = _data_object_ref(
        "resqml20.obj_WellboreTrajectoryRepresentation", traj_uuid, well_name)
    frame["NodeCount"] = len(marker_mds)
    frame["NodeMd"] = {
        "$type": "resqml20.DoubleHdf5Array",
        "Values": _hdf5_dataset(md_path),
    }

    # Marker entries
    wellbore_markers = []
    for i, (mname, md) in enumerate(zip(marker_names, marker_mds)):
        marker = {
            "$type": "resqml20.WellboreMarker",
            "Citation": _citation(mname),
            "FluidContact": None,
            "GeologicBoundaryKind": "horizon",
        }
        wellbore_markers.append(marker)

    frame["WellboreMarker"] = wellbore_markers
    json_objs.append(frame)

    # Array: marker MDs
    arrs.append(_array_def(marker_mds, "float", md_path))

    return json_objs, arrs


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

    all_json_objs = []
    all_arrs = []

    # Add CRS and HDF proxy objects (shared, required by all objects)
    all_json_objs.append(build_crs())
    all_json_objs.append(build_hdf_proxy())

    try:
        for i in range(n_wells):
            w = wl.get_well(i)

            # Depth/MD
            md_values = list(w.data.get("Depth", w.data.get("DEPTH", [])))
            if not md_values:
                md_values = list(range(w.size))
            md_values = [float(v) for v in md_values[:w.size]]

            # Build all RESQML objects + arrays for this well
            json_objs, arrs = build_well_objects(
                w.name, ds_key, w.x, w.y, w.size,
                md_values, dict(w.data), dict(w.region)
            )
            all_json_objs.extend(json_objs)
            all_arrs.extend(arrs)

            skip_keys = {"Depth", "DEPTH", "X", "Y", "Z", "MD"}
            print(f"    ✓ {w.name}: {w.size} samples, "
                  f"{len(w.data)-len(skip_keys.intersection(w.data.keys()))} logs, "
                  f"{len(w.region)} regions "
                  f"({len(json_objs)} objs, {len(arrs)} arrays)")

        # Upload all resource objects in one call
        print(f"    Uploading {len(all_json_objs)} resource objects...")
        await client.put_resources(ds_path, all_json_objs, tx_id)

        # Upload arrays in chunks (avoid payload size limits)
        CHUNK = 10
        print(f"    Uploading {len(all_arrs)} arrays...")
        for i in range(0, len(all_arrs), CHUNK):
            chunk = all_arrs[i:i + CHUNK]
            await client.put_arrays(ds_path, chunk, tx_id)

        # Commit transaction
        await client.commit_transaction(ds_path, tx_id)
        print(f"    Committed: {len(all_json_objs)} objects, {len(all_arrs)} arrays")
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
