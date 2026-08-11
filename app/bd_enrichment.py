"""
BusinessDecision enrichment helpers.

Pure-logic functions that normalise volumes, GeoLabelSets, production
forecasts, etc. and async helpers that fetch linked WPC records from
the OSDU Storage API.  Extracted from main.py to keep the main module
focused on app wiring and page routes.
"""
from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

from . import osdu

log = logging.getLogger("rddms-admin")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers - volume / BD enrichment
# ──────────────────────────────────────────────────────────────────────────────


def _normalize_volumes(data_block: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize OSDU ColumnBasedTable / ReservoirEstimatedVolumes data to:
    {
      "KeyColumns": [ {ColumnName, ColumnRole, ValueType, ...}, ... ],
      "Columns":    [ {ColumnName, ColumnRole, ValueType, ...}, ... ],
      "ColumnValues": { "<ColumnName>": [v0, v1, ...], ... }
    }
    Handles two layouts:
      - REV/GLS records: table nested under data['Volumes']
      - ColumnBasedTable records: table at the top level of data{}
    Handles cases where ColumnValues may arrive as a dict or a list of objects.
    Leaves other shapes untouched (best-effort).
    """
    # Look for the table in data['Volumes'] (REV), data['Table'] (CBT), or top-level
    vol = (data_block or {}).get("Volumes", {}) or {}
    if not vol.get("ColumnValues"):
        vol = (data_block or {}).get("Table", {}) or {}
    if not vol.get("ColumnValues") and (data_block or {}).get("ColumnValues"):
        vol = data_block
    key_cols = vol.get("KeyColumns", []) or []
    value_cols = vol.get("Columns", []) or []
    raw_vals = vol.get("ColumnValues", {}) or {}

    if isinstance(raw_vals, dict):
        col_values = raw_vals
    elif isinstance(raw_vals, list):
        # list of dicts like {"ColumnName": "...", "Values": [...]}
        if raw_vals and all(isinstance(x, dict) for x in raw_vals):
            out: Dict[str, List[Any]] = {}
            for x in raw_vals:
                name = x.get("ColumnName") or x.get("name")
                vals = (
                    x.get("Values")
                    or x.get("values")
                    or x.get("Data")
                    or x.get("data")
                    or []
                )
                if name:
                    out[name] = vals if isinstance(vals, list) else [vals]
            col_values = out
        else:
            col_values = raw_vals
    else:
        col_values = raw_vals

    return {
        "KeyColumns": key_cols,
        "Columns": value_cols,
        "ColumnValues": col_values,
    }


async def _enrich_bd_volumes(
    data_block: Dict[str, Any],
    client: httpx.AsyncClient,
    storage_url: str,
    hdr: dict,
) -> Dict[str, Any]:
    """For BusinessDecision records, fetch volumes from the stat REV WPC
    referenced in ``Parameters``.

    Returns a normalized volumes dict (may be empty if nothing found).
    The strategy:
      1. Walk ``data.Parameters`` for entries whose ``DataObjectParameter``
         points to a ReservoirEstimatedVolumes WPC.
      2. Prefer the one tagged ``REV-stats``; fall back to any REV WPC.
      3. Fetch that record and return its ``_normalize_volumes()`` output.
    """
    params = data_block.get("Parameters") or []
    if not isinstance(params, list):
        return {}

    stat_id: str = ""
    any_rev_id: str = ""
    for p in params:
        if not isinstance(p, dict):
            continue
        dop = p.get("DataObjectParameter") or ""
        if "ReservoirEstimatedVolumes" not in dop:
            continue
        # Check StringParameterKey for "stats"
        keys = p.get("Keys") or []
        is_stat = any(
            "stat" in (kv.get("StringParameterKey") or "").lower()
            for kv in keys if isinstance(kv, dict)
        )
        if is_stat:
            stat_id = dop
            break
        if not any_rev_id:
            any_rev_id = dop

    target_id = stat_id or any_rev_id
    if not target_id:
        return {}

    try:
        r = await client.get(f"{storage_url}/{target_id}", headers=hdr)
        if r.status_code != 200:
            return {}
        d = (r.json() or {}).get("data", {}) or {}
        return _normalize_volumes(d)
    except Exception as e:
        log.warning("[BD-VOLUMES] Failed to fetch stat REV %s: %s", target_id, e)
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# GeoLabelSet & ColumnBasedTable dynamic enrichment
# ──────────────────────────────────────────────────────────────────────────────

def _normalize_geolabel(data_block: Dict[str, Any]) -> Dict[str, Any]:
    """Extract a flat, template-friendly dict from a GeoLabelSet record.

    Returns::

        {
          "volumes_by_segment": {
              "<SegmentID>": {"Oil.P90": v, "Oil.P50": v, "Oil.P10": v, ...},
              ...
          },
          "properties": {
              "Porosity": {"Channel": 0.22, "Crevasse": 0.17, ...},
              "NetToGross": 0.85,
              "Permeability": 450,
              ...
          },
          "uncertainty": {
              "Recoverable.P90": v, "Recoverable.P50": v, ...
              "RecoveryFactor.P90": v, ...
          },
          "raw_geolabels": <original GeoLabels block>,
        }
    """
    gl = (data_block or {}).get("GeoLabels") or {}
    cv = gl.get("ColumnValues") or {}
    if not cv:
        # Fallback: some GeoLabelSet records use 'Table' instead of 'GeoLabels'
        gl = (data_block or {}).get("Table") or {}
        cv = gl.get("ColumnValues") or {}
    if not cv:
        return {}

    segments = cv.get("SegmentID") or cv.get("Zone") or []
    facies = cv.get("Facies") or []
    n_rows = len(segments)

    # Identify value column names (exclude key columns)
    key_names = {c.get("ColumnName") for c in (gl.get("KeyColumns") or [])}
    val_col_names = [k for k in cv if k not in key_names]

    # Volumetric columns (Oil.P*, Recoverable.*, RecoveryFactor.*)
    vol_prefixes = ("Oil.", "Gas.", "AssociatedGas.", "Bulk.", "Net.",
                    "Pore.", "HydrocarbonPore.")
    unc_prefixes = ("Recoverable.", "RecoveryFactor.")
    # Property columns (everything else)

    volumes_by_seg: Dict[str, Dict[str, Any]] = {}
    properties: Dict[str, Any] = {}
    uncertainty: Dict[str, Any] = {}

    for i in range(n_rows):
        seg = segments[i] if i < len(segments) else "TOTAL"
        # Normalise common "totals" variants → canonical "TOTAL" key
        if seg.lower() in ("totals", "total", "grand total"):
            seg = "TOTAL"
        fac = facies[i] if i < len(facies) else "ALL"

        for col in val_col_names:
            vals = cv.get(col) or []
            v = vals[i] if i < len(vals) else None
            if v is None:
                continue

            if col.startswith(unc_prefixes):
                # Uncertainty summary (field-level, TOTAL/ALL)
                uncertainty[col] = v
            elif col.startswith(vol_prefixes):
                # Per-segment volumes
                seg_dict = volumes_by_seg.setdefault(seg, {})
                seg_dict[col] = v
            else:
                # Property column
                if fac != "ALL":
                    # Facies-specific property (e.g. Porosity per facies)
                    prop_dict = properties.setdefault(col, {})
                    if isinstance(prop_dict, dict):
                        prop_dict[fac] = v
                else:
                    # Field-level scalar
                    properties[col] = v

    return {
        "volumes_by_segment": volumes_by_seg,
        "properties": properties,
        "uncertainty": uncertainty,
        "raw_geolabels": gl,
    }


async def _enrich_bd_geolabel(
    data_block: Dict[str, Any],
    client: httpx.AsyncClient,
    storage_url: str,
    hdr: dict,
) -> Dict[str, Any]:
    """Fetch the GeoLabelSet referenced in BD Parameters[] and normalise it.

    Looks for a Parameters entry with StringParameterKey 'GeoLabelSet'.
    """
    params = data_block.get("Parameters") or []
    if not isinstance(params, list):
        return {}

    target_id = ""
    for p in params:
        if not isinstance(p, dict):
            continue
        dop = p.get("DataObjectParameter") or ""
        if "GeoLabelSet" not in dop:
            continue
        keys = p.get("Keys") or []
        if any("GeoLabelSet" in (kv.get("StringParameterKey") or "")
               for kv in keys if isinstance(kv, dict)):
            target_id = dop
            break
        if not target_id:
            target_id = dop

    if not target_id:
        return {}

    d: Optional[Dict[str, Any]] = None
    try:
        r = await client.get(f"{storage_url}/{target_id}", headers=hdr)
        if r.status_code == 200:
            d = (r.json() or {}).get("data", {}) or {}
        else:
            log.warning("[BD-GLS] GeoLabelSet %s returned %d", target_id, r.status_code)
    except Exception as e:
        log.warning("[BD-GLS] OSDU fetch failed for %s: %s", target_id, e)

    if not d:
        return {}

    try:
        result = _normalize_geolabel(d)
        if result:
            log.info("[BD-GLS] Loaded GeoLabelSet %s (%d segments, %d props)",
                     target_id,
                     len(result.get("volumes_by_segment", {})),
                     len(result.get("properties", {})))
        return result
    except Exception as e:
        log.warning("[BD-GLS] Failed to normalise GeoLabelSet %s: %s", target_id, e)
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# BD enrichment: Activity record → bd_activity dict
# ──────────────────────────────────────────────────────────────────────────────

async def _enrich_bd_activity(
    data_block: Dict[str, Any],
    client: httpx.AsyncClient,
    storage_url: str,
    hdr: dict,
) -> Dict[str, Any]:
    """Fetch Activity record linked from BD PriorActivityIDs[].

    Returns a dict with the Activity's data block if found, keyed for
    easy template rendering: Name, Description, Parameters[], etc.
    """
    # Try PriorActivityIDs first
    prior_ids = data_block.get("PriorActivityIDs") or []
    if isinstance(prior_ids, str):
        prior_ids = [prior_ids]

    target_id = ""
    for pid in prior_ids:
        if isinstance(pid, str) and "Activity:" in pid and "ActivityTemplate" not in pid:
            target_id = pid
            break

    # Also check Parameters[] for ActivityTemplate or Activity refs
    if not target_id:
        params = data_block.get("Parameters") or []
        for p in params:
            if not isinstance(p, dict):
                continue
            dop = p.get("DataObjectParameter") or ""
            if "Activity:" in dop and "ActivityTemplate" not in dop:
                target_id = dop
                break

    if not target_id:
        return {}

    try:
        r = await client.get(f"{storage_url}/{target_id}", headers=hdr)
        if r.status_code == 200:
            full = r.json()
            d = full.get("data") or {}
            log.info("[BD-ACT] Loaded Activity %s: %s", target_id, d.get("Name", ""))

            # Resolve names for DataObjectParameter refs in Parameters
            param_labels: Dict[str, str] = {}
            params_list = d.get("Parameters") or []
            dop_ids = []
            for p in params_list:
                if isinstance(p, dict):
                    dop = p.get("DataObjectParameter") or ""
                    if dop and dop not in param_labels:
                        dop_ids.append(dop)
            # Parallel-fetch names (up to 15)
            async def _fetch_label(did: str) -> tuple:
                try:
                    lr = await client.get(f"{storage_url}/{did}", headers=hdr)
                    if lr.status_code == 200:
                        nm = (lr.json().get("data") or {}).get("Name") or ""
                        if nm:
                            return (did, nm)
                except Exception:
                    pass
                return (did, "")
            if dop_ids:
                results = await asyncio.gather(*[_fetch_label(d) for d in dop_ids[:15]])
                for did, nm in results:
                    if nm:
                        param_labels[did] = nm

            return {
                "id": full.get("id", target_id),
                "kind": full.get("kind", ""),
                "Name": d.get("Name", ""),
                "Description": d.get("Description", ""),
                "WorkflowStatus": d.get("WorkflowStatus", ""),
                "CreationDateTime": d.get("CreationDateTime", ""),
                "Originator": d.get("Originator", ""),
                "ActivityTemplateID": d.get("ActivityTemplateID", ""),
                "Parameters": params_list,
                "param_labels": param_labels,
            }
        else:
            log.warning("[BD-ACT] Activity %s returned %d", target_id, r.status_code)
    except Exception as e:
        log.warning("[BD-ACT] OSDU fetch failed for %s: %s", target_id, e)

    return {}


# ──────────────────────────────────────────────────────────────────────────────
# BD enrichment: discover Grid2d depth maps from linked RDDMS dataspaces
# ──────────────────────────────────────────────────────────────────────────────

def _is_proper_grid2d_map(title: str) -> bool:
    """Return True if the Grid2d title looks like an actual depth/property map.

    RESQML 2.0.1 has no dedicated table object, so resqpy DataFrames
    (parameter tables, volume tables) are stored as Grid2dRepresentation.
    Those should NOT be plotted as maps.

    Heuristic: real FMU maps have short prefixed names (DS_, TS_, GS_, …);
    table-disguised Grid2d have long titles with keywords like 'Parameters',
    'Volumes', 'Estimated', 'statistics', 'per realisation', etc.
    """
    t = title.strip()
    tl = t.lower()

    # Known table markers - skip these
    _TABLE_MARKERS = (
        "parameter", "volume", "estimated", "statistic",
        "per realisation", "per realization", "raw,", "(raw",
        "dataframe", "table",
    )
    if any(m in tl for m in _TABLE_MARKERS):
        return False

    # Known map-like prefixes (FMU convention)
    _MAP_PREFIXES = ("ds_", "ts_", "gs_", "fs_")
    if any(tl.startswith(p) for p in _MAP_PREFIXES):
        return True

    # Titles containing depth/horizon/surface keywords are maps
    _MAP_KEYWORDS = (
        "depth", "horizon", "surface", "geogrid", "simgrid",
        "extract", "interp", "filter", "velocity", "facies",
        "hum_", "gf_", "residual", "isochore", "thickness",
    )
    if any(k in tl for k in _MAP_KEYWORDS):
        return True

    # Short single-word or underscore-delimited names are likely maps
    if "_" in t and len(t) < 60:
        return True

    # Default: include (be inclusive rather than hiding data)
    return True


async def _enrich_bd_maps(
    data_block: Dict[str, Any],
    client: httpx.AsyncClient,
    storage_url: str,
    hdr: dict,
) -> Dict[str, List[Dict[str, Any]]]:
    """Discover Grid2dRepresentation objects in the BD's linked RDDMS dataspaces.

    Walks the BD ``Parameters[]`` for ETPDataspace refs, fetches each to
    extract the EML URI, then lists Grid2d objects in each dataspace via
    the Reservoir DDMS API.

    Returns a dict with two keys::

        {
          "maps":  [...],   # proper depth/property maps (plotted as images)
          "all":   [...],   # all Grid2d objects (shown in activity refs)
        }

    Each entry: ``{"ds", "uuid", "title", "ds_name"}``
    """
    params = data_block.get("Parameters") or []
    # Collect ETPDataspace record IDs
    ds_ids: List[str] = []
    for p in params:
        if not isinstance(p, dict):
            continue
        dop = p.get("DataObjectParameter") or ""
        if "etpdataspace" in dop.lower():
            ds_ids.append(dop)

    if not ds_ids:
        log.debug("[BD-MAPS] No ETPDataspace refs in Parameters[]")
        return {"maps": [], "all": []}

    all_objs: List[Dict[str, Any]] = []
    at = hdr.get("Authorization", "").replace("Bearer ", "")
    log.info("[BD-MAPS] Found %d ETPDataspace refs: %s", len(ds_ids), ds_ids)

    for ds_id in ds_ids[:3]:  # limit to 3 dataspaces
        try:
            # 1. Fetch the ETPDataspace OSDU record to get the EML URI
            r_ds = await client.get(f"{storage_url}/{ds_id}", headers=hdr)
            if r_ds.status_code != 200:
                continue
            ds_rec = r_ds.json()
            ds_data = ds_rec.get("data") or {}
            ds_name = ds_data.get("Name") or ""
            raw_uri = (ds_data.get("DatasetProperties") or {}).get("URI") or ""

            # Extract dataspace path from EML URI:
            #   eml:///dataspace('maap/drogon_dg') → maap/drogon_dg   (quoted)
            #   eml:///dataspace(maap/drogon_dg)   → maap/drogon_dg   (unquoted)
            ds_path = ""
            m = re.search(r"dataspace\(['\"]?([^'\")\s]+)['\"]?\)", raw_uri)
            if m:
                ds_path = m.group(1)
            # Fallback: also try Name field itself (often equals the ds path)
            if not ds_path and "/" in ds_name:
                ds_path = ds_name
            if not ds_path:
                log.warning("[BD-MAPS] Cannot extract ds_path from URI=%r name=%r", raw_uri, ds_name)
                continue

            # 2. List Grid2d objects in this dataspace
            enc = urllib.parse.quote(ds_path, safe="")
            grid2d_type = "resqml20.obj_Grid2dRepresentation"
            try:
                objs = await osdu.list_resources(at, enc, grid2d_type)
            except Exception:
                objs = []

            for obj in (objs or []):
                uid = obj.get("Uuid") or obj.get("UUID") or obj.get("uuid") or ""
                uri = obj.get("uri") or ""
                if not uid and "(" in uri and ")" in uri:
                    uid = uri.split("(")[-1].rstrip(")")
                # RDDMS listing returns title in "name"; individual fetch uses "Citation.Title"
                title = (
                    obj.get("name")
                    or (obj.get("Citation") or {}).get("Title")
                    or uid
                )
                if uid:
                    all_objs.append({
                        "ds": ds_path,
                        "uuid": uid,
                        "title": title,
                        "ds_name": ds_name or ds_path,
                    })
        except Exception as e:
            log.warning("[BD-MAPS] Failed to discover maps in %s: %s", ds_id, e)

    # Split: proper maps vs everything (tables stay only in activity refs)
    proper_maps = [o for o in all_objs if _is_proper_grid2d_map(o["title"])]

    # Sort proper maps: preferred hero first, then alphabetical by title.
    # Preference order: DS_extract_simgrid > DS_extract_geogrid > DS_extract.
    def _map_sort_key(mp: Dict[str, Any]) -> tuple:
        t = mp["title"].lower()
        for i, pref in enumerate(("ds_extract_simgrid", "ds_extract_geogrid", "ds_extract")):
            if t.startswith(pref):
                return (i, t)
        return (99, t)

    proper_maps.sort(key=_map_sort_key)

    # ── Enrich each proper map with horizon name (RepresentedInterpretation) ──
    # Parallel individual Grid2d fetches - lightweight (no array data).
    grid2d_type = "resqml20.obj_Grid2dRepresentation"

    async def _fetch_interpretation(mp: Dict[str, Any]) -> None:
        try:
            enc = urllib.parse.quote(mp["ds"], safe="")
            obj = await osdu.get_resource(at, enc, grid2d_type, mp["uuid"])
            norm = osdu._normalize_obj(obj, mp["uuid"])
            interp_ref = norm.get("RepresentedInterpretation") or {}
            interp_title = interp_ref.get("Title") or ""
            if interp_title:
                mp["interpretation"] = interp_title
        except Exception as e:
            log.debug("[BD-MAPS] interpretation fetch failed for %s: %s", mp["uuid"], e)

    if proper_maps:
        await asyncio.gather(*[_fetch_interpretation(mp) for mp in proper_maps])

    log.info("[BD-MAPS] Discovered %d Grid2d objects (%d proper maps, hero=%s) across %d dataspaces",
             len(all_objs), len(proper_maps),
             proper_maps[0]["title"] if proper_maps else "none", len(ds_ids))
    return {"maps": proper_maps, "all": all_objs, "maps_total": len(proper_maps)}


async def _enrich_bd_production(
    data_block: Dict[str, Any],
    client: httpx.AsyncClient,
    storage_url: str,
    hdr: dict,
) -> Dict[str, Any]:
    """Fetch ColumnBasedTable production forecast from BD Parameters[].

    The OSDU ColumnBasedTable 1.4.0 schema stores column data under
    ``data.Table``:

    - ``Table.KeyColumns`` – list of key column defs (e.g. Year)
    - ``Table.Columns`` – list of value column defs
    - ``Table.ColumnValues`` – **positional array** of objects, each with
      either ``IntegerColumn`` or ``NumberColumn`` holding the values.
      Index *i* in the array corresponds to the column at the same index
      in *KeyColumns + Columns*.

    Returns a flat dict with template-friendly names::

        {"Years": [...], "OilRate_kSm3d": [...], ...}
    """
    params = data_block.get("Parameters") or []
    if not isinstance(params, list):
        return {}

    target_id = ""
    for p in params:
        if not isinstance(p, dict):
            continue
        dop = p.get("DataObjectParameter") or ""
        if "ColumnBasedTable" not in dop:
            continue
        keys = p.get("Keys") or []
        if any(k in (kv.get("StringParameterKey") or "")
               for kv in keys if isinstance(kv, dict)
               for k in ("ProductionForecast", "ProductionProfile")):
            target_id = dop
            break

    if not target_id:
        return {}

    d: Optional[Dict[str, Any]] = None
    try:
        r = await client.get(f"{storage_url}/{target_id}", headers=hdr)
        if r.status_code == 200:
            d = (r.json() or {}).get("data", {}) or {}
        else:
            log.warning("[BD-PROD] CBT %s returned %d", target_id, r.status_code)
    except Exception as e:
        log.warning("[BD-PROD] OSDU fetch failed for %s: %s", target_id, e)

    if not d:
        return {}

    try:
        return _parse_cbt_production(d, target_id)
    except Exception as e:
        log.warning("[BD-PROD] Failed to parse production CBT %s: %s", target_id, e)
        return {}


def _parse_cbt_production(d: Dict[str, Any], target_id: str = "") -> Dict[str, Any]:
    """Parse a ColumnBasedTable ``data`` block into template-friendly dict."""
    tbl = d.get("Table") or {}
    key_cols = tbl.get("KeyColumns") or []
    val_cols = tbl.get("Columns") or []
    col_values = tbl.get("ColumnValues") or []
    if not col_values:
        return {}

    # Build ordered column name list: KeyColumns first, then Columns
    all_col_defs = key_cols + val_cols

    # Extract values — handle both positional-array and dict formats
    col_data: Dict[str, list] = {}
    if isinstance(col_values, dict):
        # Dict format: {"Year": [...], "OilRate_Sm3d": [...], ...}
        col_data = {k: v for k, v in col_values.items() if isinstance(v, list)}
    else:
        # Positional-array format: [{"IntegerColumn": [...]}, ...]
        if len(all_col_defs) != len(col_values):
            log.warning("[BD-PROD] Column count mismatch: %d defs vs %d value arrays",
                        len(all_col_defs), len(col_values))
        for i, cv_entry in enumerate(col_values):
            if not isinstance(cv_entry, dict):
                continue
            name = all_col_defs[i].get("ColumnName", f"col_{i}") if i < len(all_col_defs) else f"col_{i}"
            # Pick whichever typed array is present
            vals = (cv_entry.get("IntegerColumn")
                    or cv_entry.get("NumberColumn")
                    or cv_entry.get("StringColumn")
                    or cv_entry.get("BooleanColumn")
                    or [])
            col_data[name] = vals

    # Map CBT column names → template keys
    # Supports both generic names (OilRate) and OPM Flow names (FOPR)
    name_map = {
        # Generic / legacy names
        "OilRate": "OilRate_kSm3d",
        "GasRate": "GasRate_kSm3d",
        "WaterRate": "WaterRate_kSm3d",
        "WaterInjRate": "WaterInjRate_kSm3d",
        "YearlyOil": "YearlyOil_MSm3",
        "CumulativeOil": "CumOil_MSm3",
        "WaterCut": "WaterCut_pct",
        "RecoveryFactor": "RecoveryFactor_pct",
        "WellsOnline": "WellsOnline",
        # OPM Flow / Eclipse summary vector names
        "FOPR": "OilRate_kSm3d",
        "FGPR": "GasRate_kSm3d",
        "FWPR": "WaterRate_kSm3d",
        "FWIR": "WaterInjRate_kSm3d",
        "FOPT": "CumOil_MSm3",
        "FPR": "FPR_barsa",
        "FWCT": "WaterCut_pct",
        "FGOR": "FGOR",
        "ProducersOnline": "WellsOnline",
        "InjectorsOnline": "InjectorsOnline",
        # Omega-style explicit-unit column names
        "OilRate_Sm3d": "OilRate_kSm3d",
        "GasRate_kSm3d": "GasRate_kSm3d",
        "WaterRate_Sm3d": "WaterRate_kSm3d",
        "WaterInjection_Sm3d": "WaterInjRate_kSm3d",
        "CumulativeOil_MSm3": "CumOil_MSm3",
    }

    result: Dict[str, Any] = {}
    # Key column → Years (handles both "Year" and "Date" column names)
    for kc in key_cols:
        cn = kc.get("ColumnName", "")
        if cn in col_data:
            result["Years"] = col_data[cn]

    # Value columns
    for vc in val_cols:
        cn = vc.get("ColumnName", "")
        if cn in col_data:
            tpl_key = name_map.get(cn, cn)
            result[tpl_key] = col_data[cn]

    # Extract summary from ext.equinor.ForecastSummary if present
    ext_eq = (d.get("ext") or {}).get("equinor") or {}
    summary = ext_eq.get("ForecastSummary") or {}
    if summary:
        result["summary"] = summary
    # Also carry forward the Note
    note = ext_eq.get("Note") or d.get("Description") or ""
    if note:
        result["Note"] = note

    if result.get("Years"):
        log.info("[BD-PROD] Loaded production forecast: %d years, %d columns",
                 len(result["Years"]), len(result) - 1)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# BD enrichment: DevelopmentConcept WPC → ext.equinor.DevelopmentConcept
# ──────────────────────────────────────────────────────────────────────────────

# Fields to extract from the DevelopmentConcept v4 WPC data block.
# v4 uses structured sub-objects with OSDU *ID fields; we pass them through wholesale.
_DEVCONCEPT_FIELDS = (
    "Name", "Summary", "DecisionGate", "DecisionLevelID",
    "FacilityConcept", "WellPlan", "DrainageStrategy",
    "ReservoirTarget", "ProductionTechnology",
    "ConceptID",
)


async def _enrich_bd_developmentconcept(
    data_block: Dict[str, Any],
    client: httpx.AsyncClient,
    storage_url: str,
    hdr: dict,
) -> None:
    """Fetch DevelopmentConcept WPC from BD Parameters[] and inject into
    ``data.ext.equinor.DevelopmentConcept`` so templates render it unchanged.

    Looks for a Parameters entry with StringParameterKey 'DevelopmentConcept'.
    Falls back to local demo record if OSDU fetch fails.
    Only overwrites ext.equinor.DevelopmentConcept when WPC data is found.
    """
    params = data_block.get("Parameters") or []
    if not isinstance(params, list):
        return

    # Find the DevelopmentConcept WPC reference
    target_id = ""
    for p in params:
        if not isinstance(p, dict):
            continue
        dop = p.get("DataObjectParameter") or ""
        if "DevelopmentConcept" not in dop:
            continue
        keys = p.get("Keys") or []
        if any("DevelopmentConcept" in (kv.get("StringParameterKey") or "")
               for kv in keys if isinstance(kv, dict)):
            target_id = dop
            break

    if not target_id:
        return

    d: Optional[Dict[str, Any]] = None
    try:
        r = await client.get(f"{storage_url}/{target_id}", headers=hdr)
        if r.status_code == 200:
            d = (r.json() or {}).get("data", {}) or {}
        else:
            log.warning("[BD-DC] DevelopmentConcept %s returned %d", target_id, r.status_code)
    except Exception as e:
        log.warning("[BD-DC] OSDU fetch failed for %s: %s", target_id, e)

    if not d:
        return

    # Extract DevelopmentConcept fields from the WPC data block
    dcon: Dict[str, Any] = {}
    for key in _DEVCONCEPT_FIELDS:
        if key in d:
            dcon[key] = d[key]

    if not dcon:
        return

    # Inject into ext.equinor.DevelopmentConcept
    ext_eq = data_block.setdefault("ext", {}).setdefault("equinor", {})
    ext_eq["DevelopmentConcept"] = dcon
    log.info("[BD-DC] Injected DevelopmentConcept from WPC %s (%d fields)",
             target_id, len(dcon))


# ──────────────────────────────────────────────────────────────────────────────
# BD enrichment: CollaborationProject → lifecycle events + gate checklist
# ──────────────────────────────────────────────────────────────────────────────

async def _enrich_bd_collaboration(
    data_block: Dict[str, Any],
    client: httpx.AsyncClient,
    search_url: str,
    storage_url: str,
    hdr: dict,
) -> Dict[str, Any]:
    """Find the CollaborationProject linked to this BD and extract:
    - LifecycleEvents[] for activity feed/timeline
    - ActivityStates[] (gate-prefixed milestones) for checklist progress
    - Parameters[].Keys[] with relationship semantics for graph rendering

    Search strategy: reverse-lookup CPs whose ParentProjectID = this BD's id,
    or whose Parameters[].DataObjectParameter references this BD.
    """
    bd_id = data_block.get("_record_id") or ""
    if not bd_id:
        return {}

    # Strategy 1: search for CP with ParentProjectID pointing to this BD
    try:
        payload = {
            "kind": "*:*:master-data--CollaborationProject:*",
            "query": f'"{bd_id}"',
            "limit": 5,
            "returnedFields": ["id"],
        }
        r = await client.post(f"{search_url}/query", json=payload, headers=hdr)
        cp_ids = []
        if r.status_code == 200:
            for hit in (r.json().get("results") or []):
                cp_ids.append(hit.get("id"))
    except Exception:
        cp_ids = []

    if not cp_ids:
        return {}

    # Fetch first CP record
    try:
        r = await client.get(f"{storage_url}/{cp_ids[0]}", headers=hdr)
        if r.status_code != 200:
            return {}
        cp_data = r.json().get("data") or {}
    except Exception:
        return {}

    # Extract lifecycle events
    events = cp_data.get("LifecycleEvents") or []

    # Extract gate checklist from ActivityStates (items with hyphenated MilestoneID)
    all_states = cp_data.get("ActivityStates") or []
    checklist = []
    schedule = []
    for st in all_states:
        if not isinstance(st, dict):
            continue
        mid = st.get("MilestoneID") or ""
        if "-" in mid and not mid.startswith("DG"):
            # e.g. "DG2-Volumes" — this is a checklist item
            checklist.append(st)
        elif "-" in mid:
            # e.g. "DG2-Volumes" with "DG" prefix — also checklist
            checklist.append(st)
        else:
            schedule.append(st)

    # Count completed checklist items
    completed = sum(
        1 for s in checklist
        if "completed" in (s.get("ActivityStatusID") or "").lower()
    )

    # Extract relationship graph from Parameters[]
    cp_params = cp_data.get("Parameters") or []
    relationships = []
    for p in cp_params:
        if not isinstance(p, dict):
            continue
        keys = p.get("Keys") or []
        rel = None
        for k in keys:
            if isinstance(k, dict) and k.get("ParameterKey") == "relationship":
                rel = k.get("StringParameterKey")
                break
        if rel:
            relationships.append({
                "title": p.get("Title") or "",
                "target": p.get("DataObjectParameter") or "",
                "relationship": rel,
                "selection": p.get("Selection") or "",
            })

    return {
        "cp_id": cp_ids[0],
        "cp_name": cp_data.get("ProjectName") or "",
        "events": events,
        "checklist": checklist,
        "checklist_completed": completed,
        "checklist_total": len(checklist),
        "relationships": relationships,
    }
