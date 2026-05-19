"""
weco.json_format — WeCo JSON Format (OSDU-schema inspired)
============================================================

Defines a portable JSON schema for WeCo projects following OSDU patterns:
- kind/version/id envelope
- Typed well log data and region arrays
- Correlation options and results
- Self-describing metadata

Schema kinds:
    weco:wbs:WellList:1.0.0          — wells + data + regions
    weco:wbs:CorrelationProject:1.0.0 — full project (wells + options + results)
    weco:wbs:CorrelationResult:1.0.0  — result graph only

Usage::

    from weco.json_format import (
        welllist_to_json, json_to_welllist,
        project_to_json, json_to_project,
        result_to_json, json_to_result,
    )
    # Export
    doc = welllist_to_json(well_list, include_meta=True)
    Path("project.weco.json").write_text(json.dumps(doc, indent=2))

    # Import
    doc = json.loads(Path("project.weco.json").read_text())
    wl = json_to_welllist(doc)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from .data import Well, WellList, ResFile

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

SCHEMA_VERSION = "1.0.0"
KIND_WELLLIST = f"weco:wbs:WellList:{SCHEMA_VERSION}"
KIND_PROJECT = f"weco:wbs:CorrelationProject:{SCHEMA_VERSION}"
KIND_RESULT = f"weco:wbs:CorrelationResult:{SCHEMA_VERSION}"


def _new_id() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ═══════════════════════════════════════════════════════════════════════════
# §1  Well / WellList  →  JSON
# ═══════════════════════════════════════════════════════════════════════════

def _well_to_dict(well: Well) -> Dict[str, Any]:
    """Serialize a single Well to a JSON-friendly dict."""
    w: Dict[str, Any] = {
        "name": well.name,
        "size": well.size,
        "location": {
            "x": well.x,
            "y": well.y,
            "z": well.z,
            "h": well.h,
        },
    }

    # Data channels (continuous log arrays)
    if well.data:
        channels = []
        for name, values in well.data.items():
            ch: Dict[str, Any] = {
                "name": name,
                "size": len(values),
                "values": [round(v, 8) if isinstance(v, float) else v for v in values],
            }
            # Include metadata if available
            if hasattr(well, "meta") and name in well.meta:
                ch["meta"] = well.meta[name]
            channels.append(ch)
        w["data"] = channels

    # Regions (discrete interval arrays)
    if well.region:
        regions = []
        for name, intervals in well.region.items():
            reg = {
                "name": name,
                "intervals": [
                    {"id": rid, "start": start, "length": length}
                    for rid, start, length in intervals
                ],
            }
            regions.append(reg)
        w["regions"] = regions

    return w


def welllist_to_json(
    wl: WellList,
    *,
    doc_id: Optional[str] = None,
    include_meta: bool = True,
) -> Dict[str, Any]:
    """Convert WellList to WeCo JSON document.

    Parameters
    ----------
    wl : WellList
        The well list to serialize.
    doc_id : str, optional
        Document UUID. Auto-generated if not provided.
    include_meta : bool
        Include metadata envelope (kind, version, timestamps).

    Returns
    -------
    dict
        JSON-serializable document.
    """
    doc: Dict[str, Any] = {
        "kind": KIND_WELLLIST,
        "id": doc_id or _new_id(),
        "version": SCHEMA_VERSION,
        "createTime": _now_iso(),
    }

    if include_meta:
        doc["meta"] = {
            "dataChannels": wl.get_data_names(),
            "regionNames": wl.get_region_names(),
            "wellCount": wl.nbr_wells(),
        }

    doc["wells"] = [_well_to_dict(w) for w in wl.wells]
    return doc


# ═══════════════════════════════════════════════════════════════════════════
# §2  JSON  →  Well / WellList
# ═══════════════════════════════════════════════════════════════════════════

def _dict_to_well(d: Dict[str, Any]) -> Well:
    """Deserialize a well dict back to a Well object."""
    w = Well(d["name"])
    w.size = d.get("size", 0)

    loc = d.get("location", {})
    w.x = loc.get("x", 0.0)
    w.y = loc.get("y", 0.0)
    w.z = loc.get("z", 0.0)
    w.h = loc.get("h", 0.0)

    # Data channels
    for ch in d.get("data", []):
        w.data[ch["name"]] = tuple(ch["values"])
        if "meta" in ch:
            w.meta[ch["name"]] = ch["meta"]

    # Regions
    for reg in d.get("regions", []):
        intervals = tuple(
            (iv["id"], iv["start"], iv["length"])
            for iv in reg["intervals"]
        )
        w.region[reg["name"]] = intervals

    return w


def json_to_welllist(doc: Dict[str, Any]) -> WellList:
    """Parse a WeCo JSON document into a WellList.

    Accepts documents with kind ``weco:wbs:WellList:*`` or
    ``weco:wbs:CorrelationProject:*`` (extracts wells section).

    Parameters
    ----------
    doc : dict
        Parsed JSON document.

    Returns
    -------
    WellList

    Raises
    ------
    ValueError
        If the document kind is unrecognized.
    """
    kind = doc.get("kind", "")
    if "WellList" not in kind and "CorrelationProject" not in kind:
        raise ValueError(f"Unrecognized document kind: {kind}")

    wells_data = doc.get("wells", [])
    wl = WellList()
    for wd in wells_data:
        wl.add_well(_dict_to_well(wd))
    return wl


# ═══════════════════════════════════════════════════════════════════════════
# §3  Correlation Options
# ═══════════════════════════════════════════════════════════════════════════

def options_to_dict(opts: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize option dict to JSON-safe types with OSDU-style keys."""
    result = {}
    for k, v in opts.items():
        # Keep underscore keys (Python style) — convert on engine call
        if isinstance(v, (int, float, str, bool)):
            result[k] = v
        elif isinstance(v, np.integer):
            result[k] = int(v)
        elif isinstance(v, np.floating):
            result[k] = float(v)
        else:
            result[k] = str(v)
    return result


# ═══════════════════════════════════════════════════════════════════════════
# §4  Correlation Result  →  JSON
# ═══════════════════════════════════════════════════════════════════════════

def result_to_json(
    res: ResFile,
    wl: Optional[WellList] = None,
    *,
    doc_id: Optional[str] = None,
    max_paths: int = 10,
) -> Dict[str, Any]:
    """Convert correlation result to WeCo JSON.

    Parameters
    ----------
    res : ResFile
        Correlation result.
    wl : WellList, optional
        Well list for name resolution.
    doc_id : str, optional
        Document UUID.
    max_paths : int
        Maximum number of result paths to include.

    Returns
    -------
    dict
        JSON-serializable correlation result document.
    """
    doc: Dict[str, Any] = {
        "kind": KIND_RESULT,
        "id": doc_id or _new_id(),
        "version": SCHEMA_VERSION,
        "createTime": _now_iso(),
    }

    # Well mapping
    well_names = []
    if wl:
        for wid in res.well_id:
            if 0 <= wid < wl.nbr_wells():
                well_names.append(wl.wells[wid].name)
            else:
                well_names.append(f"Well_{wid}")
    else:
        well_names = [f"Well_{wid}" for wid in res.well_id]

    doc["wells"] = {
        "ids": list(res.well_id),
        "names": well_names,
        "sizes": list(res.well_size) if res.well_size else [],
    }

    # Correlation graph (nodes + transitions)
    doc["graph"] = {
        "nodeCount": res.size,
        "nodes": [
            {"id": i, "markers": list(res.nodes[i])}
            for i in range(min(res.size, 5000))  # cap for very large graphs
        ],
    }

    # N-best paths
    paths = []
    n_results = min(max_paths, res.nbr_cor())
    for i in range(n_results):
        path_data = {
            "rank": i,
            "cost": res.get_result_cost(i),
        }
        full_path = res.get_result_full_path(i)
        if full_path:
            path_data["markers"] = [list(node) for node in full_path]
        paths.append(path_data)
    doc["paths"] = paths
    doc["totalCorrelations"] = res.nbr_cor()

    return doc


def json_to_result(doc: Dict[str, Any]) -> ResFile:
    """Parse a WeCo JSON result document back into a ResFile.

    Note: This reconstructs the paths/costs but not the full graph
    (backward_trans, forward_trans) which requires the original
    correlation run.
    """
    kind = doc.get("kind", "")
    if "CorrelationResult" not in kind and "CorrelationProject" not in kind:
        raise ValueError(f"Unrecognized document kind: {kind}")

    # If it's a project doc, extract the result section
    if "CorrelationProject" in kind:
        doc = doc.get("result", doc)

    rf = ResFile()
    wells_sec = doc.get("wells", {})
    rf.well_id = tuple(wells_sec.get("ids", []))
    rf.well_size = tuple(wells_sec.get("sizes", []))

    # Reconstruct nodes
    graph = doc.get("graph", {})
    nodes_list = graph.get("nodes", [])
    rf.nodes = tuple(tuple(n["markers"]) for n in nodes_list)
    rf.size = len(rf.nodes)

    # Reconstruct paths
    paths = doc.get("paths", [])
    rf.results = []
    for p in paths:
        rf.results.append((p["cost"], p.get("markers", [])))

    return rf


# ═══════════════════════════════════════════════════════════════════════════
# §5  Full Project  →  JSON
# ═══════════════════════════════════════════════════════════════════════════

def project_to_json(
    wl: WellList,
    opts: Dict[str, Any],
    res: Optional[ResFile] = None,
    *,
    doc_id: Optional[str] = None,
    max_paths: int = 10,
) -> Dict[str, Any]:
    """Create a full WeCo CorrelationProject JSON document.

    Parameters
    ----------
    wl : WellList
        Input wells.
    opts : dict
        Correlation options.
    res : ResFile, optional
        Results (if correlation has been run).
    doc_id : str, optional
        Document UUID.
    max_paths : int
        Maximum number of result paths.

    Returns
    -------
    dict
        Complete project document.
    """
    doc: Dict[str, Any] = {
        "kind": KIND_PROJECT,
        "id": doc_id or _new_id(),
        "version": SCHEMA_VERSION,
        "createTime": _now_iso(),
    }

    # Meta section
    doc["meta"] = {
        "dataChannels": wl.get_data_names(),
        "regionNames": wl.get_region_names(),
        "wellCount": wl.nbr_wells(),
        "engine": "weco",
        "engineVersion": _get_version(),
    }

    # Options
    doc["options"] = options_to_dict(opts)

    # Wells
    doc["wells"] = [_well_to_dict(w) for w in wl.wells]

    # Results
    if res and res.size > 0:
        doc["result"] = result_to_json(res, wl, max_paths=max_paths)

    return doc


def json_to_project(doc: Dict[str, Any]) -> Tuple[WellList, Dict[str, Any], Optional[ResFile]]:
    """Parse a full CorrelationProject JSON back to components.

    Returns
    -------
    tuple of (WellList, options_dict, ResFile or None)
    """
    kind = doc.get("kind", "")
    if "CorrelationProject" not in kind:
        raise ValueError(f"Expected CorrelationProject, got: {kind}")

    wl = json_to_welllist(doc)
    opts = doc.get("options", {})

    res = None
    if "result" in doc:
        res = json_to_result(doc["result"])

    return wl, opts, res


# ═══════════════════════════════════════════════════════════════════════════
# §6  File I/O convenience
# ═══════════════════════════════════════════════════════════════════════════

def save_json(doc: Dict[str, Any], path: Union[str, Path]) -> None:
    """Write a WeCo JSON document to file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    logger.info("Saved %s -> %s", doc.get("kind", "?"), path)


def load_json(path: Union[str, Path]) -> Dict[str, Any]:
    """Load a WeCo JSON document from file."""
    path = Path(path)
    doc = json.loads(path.read_text())
    if "kind" not in doc:
        raise ValueError(f"Not a WeCo JSON document (missing 'kind'): {path}")
    return doc


def load_welllist(path: Union[str, Path]) -> WellList:
    """Load a WellList from either .weco.json or legacy .txt format."""
    path = Path(path)
    if path.suffix == ".json" or path.name.endswith(".weco.json"):
        return json_to_welllist(load_json(path))
    # Fallback to legacy text format
    return WellList(str(path))


# ═══════════════════════════════════════════════════════════════════════════
# §7  Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _get_version() -> str:
    """Get WeCo version string."""
    try:
        from importlib.metadata import version
        return version("WeCo")
    except Exception:
        try:
            ver_file = Path(__file__).parent.parent / "VERSION"
            if ver_file.exists():
                return ver_file.read_text().strip()
        except Exception:
            pass
    return "unknown"


# ═══════════════════════════════════════════════════════════════════════════
# §8  Dataset conversion utility
# ═══════════════════════════════════════════════════════════════════════════

def convert_txt_to_json(
    txt_path: Union[str, Path],
    json_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Convert a legacy WeCo .txt well list to .weco.json format.

    Parameters
    ----------
    txt_path : path
        Input WeCo text file.
    json_path : path, optional
        Output path. If None, uses same directory with .weco.json extension.

    Returns
    -------
    dict
        The generated JSON document.
    """
    txt_path = Path(txt_path)
    wl = WellList(str(txt_path))

    doc = welllist_to_json(wl)
    doc["meta"]["sourceFile"] = txt_path.name
    doc["meta"]["convertedAt"] = _now_iso()

    if json_path is None:
        json_path = txt_path.with_suffix(".weco.json")
    else:
        json_path = Path(json_path)

    save_json(doc, json_path)
    return doc
