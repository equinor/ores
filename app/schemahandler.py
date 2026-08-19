
# app/schemahandler.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple, Union, Iterable, Set
import re

# Local import used to synthesize canonical EML URIs in metadata
from . import osdu  # for _eml_uri_from_parts

# ---------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------
Scalar = Union[str, int, float, bool, None]

# ---------------------------------------------------------------------
# OSDU ID detection (master-data, work-product/work-product-component, dataset)
# Excludes reference-data by design.
#
# Examples accepted:
#   "dev:master-data--Reservoir:f9585655-83d8-4549-ae3e-2dffc2cd5937:1"
#   "dev:work-product-component--ReservoirEstimatedVolumes:5033c9e2-b1cf-424a-86c9-76b846942cf8:1"
#   "dev:dataset--FileCollection.Bluware.OpenVDS:drogon-amplitude-far-time-20180101"
#   "opendes:work-product-component--SeismicTraceData:drogon-amp-far-time-20180101:"
# ---------------------------------------------------------------------
_OSDU_ID_RE = re.compile(
    r"""^[\w\-.]+:
        (?:(?:work-product(?:-component)?)|master-data|dataset)--[\w\-.]+:
        [\w\-.:%]+
        (?::[0-9]+)?$""",
    re.VERBOSE,
)


def _looks_like_osdu_id(s: str) -> bool:
    """Return True for master-data or WPC record IDs; reject reference-data."""
    if not isinstance(s, str):
        return False
    if "reference-data--" in s:
        return False
    return bool(_OSDU_ID_RE.match(s.strip()))


def _role_from_path(path: str) -> str:
    """Heuristic role labeling derived from the JSON path inside data{}."""
    p = (path or "").lower()
    if "riskids" in p:
        return "risk"
    if "priordecisionid" in p:
        return "supersedes"
    if "prioractivityids" in p:
        return "prior-activity"
    if "parentworkproductid" in p:
        return "parent-work-product"
    if "parentobjectid" in p:
        return "parent-object"
    if "evidencecollectionid" in p or "trustedcollectionid" in p:
        return "evidence"
    if "collaborationprojectid" in p:
        return "project"
    if "parameters" in p and ("objectparameterkey" in p or "dataobjectparameter" in p):
        return "parameter-object"
    if "ancestry.parents" in p:
        return "ancestry-parent"
    if "ancestry.children" in p:
        return "ancestry-child"
    # RESQML FIRP relationship fields
    if "featureid" in p:
        return "feature"
    if "interpretationid" in p:
        return "interpretation"
    if "representationid" in p:
        return "representation"
    return "ref"


def _walk_collect_ids(x: Any, base: str = "") -> Iterable[Dict[str, Any]]:
    """Recursive walk of dict/list collecting record IDs with their source path."""
    if isinstance(x, dict):
        for k, v in x.items():
            sub = f"{base}.{k}" if base else k
            if isinstance(v, str) and _looks_like_osdu_id(v):
                yield {"id": v, "role": _role_from_path(sub), "source_path": sub}
            else:
                yield from _walk_collect_ids(v, sub)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            sub = f"{base}[{i}]"
            if isinstance(v, str) and _looks_like_osdu_id(v):
                yield {"id": v, "role": _role_from_path(base), "source_path": sub}
            else:
                yield from _walk_collect_ids(v, sub)


def extract_osdu_links(data_block: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Return a *deduped* list of {id, role, source_path} for WPC/master-data IDs
    found in the record's `data` (and in ancestry parents/children if present).
    Reference-data catalog references are excluded by design.
    """
    if not isinstance(data_block, dict):
        return []

    links: List[Dict[str, Any]] = []

    # ancestry parents/children
    anc = data_block.get("ancestry") or {}
    for p in (anc.get("parents") or []):
        if isinstance(p, str) and _looks_like_osdu_id(p):
            links.append({"id": p, "role": "ancestry-parent", "source_path": "ancestry.parents"})
    for c in (anc.get("children") or []):
        if isinstance(c, str) and _looks_like_osdu_id(c):
            links.append({"id": c, "role": "ancestry-child", "source_path": "ancestry.children"})

    # generic walk across all properties - skip 'ancestry' (handled above)
    for k, v in data_block.items():
        if k == "ancestry":
            continue
        # Direct string values (e.g. FeatureID, InterpretationID)
        if isinstance(v, str) and _looks_like_osdu_id(v):
            links.append({"id": v, "role": _role_from_path(k), "source_path": k})
            continue
        for found in _walk_collect_ids(v, k):
            links.append(found)

    # de-duplicate by ID.  When the same record appears under multiple
    # roles keep the most specific one (anything other than "ref" wins).
    # Also strip trailing colons from IDs (RDDMS manifest appends ":"
    # to FIRP references but actual record IDs don't have them).
    seen: Dict[str, Dict[str, Any]] = {}   # id → link dict
    for l in links:
        rid = l.get("id", "").rstrip(":")
        l["id"] = rid
        prev = seen.get(rid)
        if prev is None:
            seen[rid] = l
        elif prev.get("role") == "ref" and l.get("role") != "ref":
            seen[rid] = l          # prefer the specific role
    return list(seen.values())


# ---------------------------------------------------------------------
# Metadata extractor for RESQML / EML objects
# ---------------------------------------------------------------------

def _is_scalar(x: Any) -> bool:
    """Return True for JSON-safe scalar types (including None)."""
    return isinstance(x, (str, int, float, bool)) or x is None


def _shorten(s: Any, max_len: int = 300) -> Any:
    """Truncate long strings for compact metadata views.  Non-strings pass through."""
    if not isinstance(s, str):
        return s
    return s if len(s) <= max_len else (s[:max_len] + "…")


def extract_metadata_generic(
    obj: Dict[str, Any],
    *,
    ds: str,
    typ: str,
    uuid: str,
    arrays: List[Dict[str, Any]] | None = None,
    max_string_len: int = 300,
    max_preview_items: int = 5,
    exclude_keys: Tuple[str, ...] = (
        # common heavy/noisy keys we don't inline in metadata (arrays & blobs)
        "Points", "Values", "BinaryData", "Binary", "Hdf5", "Hdf5Proxy",
        "ExternalData", "DataBuffer", "RawData", "Samples", "Traces",
    ),
) -> Dict[str, Any]:
    """
    Metadata extractor for RESQML/EML objects (those with Citation, $type, etc.).

    Collects:
      • Identity/classification (uuid, typePath, $type/contentType, SchemaVersion,
        Citation.Title, URI)
      • All scalar leaves as dot-path keys (with string truncation)
      • Compact summaries for lists (count + small scalar preview)
      • Compact summaries for dicts (key count)
      • A rendering-friendly flat 'pairs' list [{name, value}, ...]
    Large arrays/binary blocks are skipped via 'exclude_keys'.
    """
    arrays = arrays or []
    md: Dict[str, Any] = {}

    # Identity & classification (stable top-level)
    citation = obj.get("Citation") or {}
    title = citation.get("Title") or uuid
    schema = obj.get("SchemaVersion") or obj.get("schemaVersion") or ""
    ctype = obj.get("$type") or obj.get("contentType") or ""
    uri = obj.get("uri") or osdu._eml_uri_from_parts(ds, typ, uuid)

    md.update(
        {
            "uuid": uuid,
            "typePath": typ,
            "title": title,
            "schemaVersion": schema,
            "contentType": ctype,
            "uri": uri,
            "arrayCount": len(arrays),
            "hasArrays": bool(arrays),
        }
    )

    # Identity pairs (added first - no duplication with curated_keys below)
    pairs: List[Dict[str, Any]] = [
        {"name": "Title", "value": title},
        {"name": "UUID", "value": uuid},
        {"name": "Type", "value": typ},
        {"name": "SchemaVersion", "value": schema},
        {"name": "ContentType/$type", "value": ctype},
        {"name": "URI", "value": uri},
        {"name": "Arrays", "value": len(arrays)},
    ]

    # Track which names are already in pairs to avoid duplicates
    _pairs_names: Set[str] = {p["name"] for p in pairs}

    # Recursive walk producing dot-path keys
    def visit(path: str, value: Any) -> None:
        base = path.rsplit(".", 1)[-1] if path else ""
        if base in exclude_keys:
            return
        if _is_scalar(value):
            if path:
                md[path] = _shorten(value, max_len=max_string_len) if isinstance(value, str) else value
            return
        if isinstance(value, dict):
            if path:
                md[f"{path}.keys"] = len(value.keys())
            for k, v in value.items():
                subpath = f"{path}.{k}" if path else k
                visit(subpath, v)
            return
        if isinstance(value, list):
            if path:
                md[f"{path}.count"] = len(value)
            # Recurse into list items (dicts and nested lists)
            preview: List[Scalar] = []
            for i, itm in enumerate(value):
                if _is_scalar(itm):
                    if len(preview) < max_preview_items:
                        preview.append(
                            _shorten(itm, max_len=max_string_len) if isinstance(itm, str) else itm
                        )
                elif isinstance(itm, (dict, list)):
                    visit(f"{path}[{i}]" if path else f"[{i}]", itm)
            if preview and path:
                md[f"{path}.preview"] = preview
            return
        # fallback for other JSON-ish types
        if path:
            md[path] = _shorten(str(value), max_len=max_string_len)

    visit("", obj)

    # Optional compact hints for common types (safe no-op for others)
    grid = obj.get("Grid2dPatch") or {}
    fast = grid.get("FastestAxisCount")
    slow = grid.get("SlowestAxisCount")
    if isinstance(fast, int):
        md["Grid2dPatch.FastestAxisCount"] = fast
    if isinstance(slow, int):
        md["Grid2dPatch.SlowestAxisCount"] = slow

    # Curated keys → pairs (skip if already present under that name)
    curated_keys = [
        "Grid2dPatch.FastestAxisCount",
        "Grid2dPatch.SlowestAxisCount",
    ]
    for ck in curated_keys:
        if ck in md and ck not in _pairs_names:
            pairs.append({"name": ck, "value": md[ck]})
            _pairs_names.add(ck)

    md["pairs"] = pairs
