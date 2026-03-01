
from __future__ import annotations
import os
import re
import secrets
import urllib.parse
import logging
import json
from pathlib import Path
from collections import Counter
from typing import List, Dict, Any, Optional, Set

from dotenv import load_dotenv
load_dotenv()  # must run before any module reads os.getenv at import time

import httpx
from httpx import HTTPStatusError
from fastapi import FastAPI, Request, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from starlette.middleware.sessions import SessionMiddleware

# App modules
from .schemahandler import extract_osdu_links
from .schemahandler import extract_metadata_generic
from app.ingest_router import router as ingest_router
from . import osdu
from .auth import (
    router as auth_router,
    tokens_from_env,
    tokens_from_session,
    AUTH_MODE,
    PUBLIC_PATHS,
)
from .strat import router as strat_router
from .analyse import router as analyse_router
from .addgate import router as addgate_router
from .keys_router import router as keys_router

# ──────────────────────────────────────────────────────────────────────────────
# App setup & logging
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger("rddms-admin")

app = FastAPI(title="RDDMS Admin")

# Session middleware — needed for per-user PKCE auth (cookie-based sessions)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", secrets.token_hex(16)),
    session_cookie="ores_session",
    max_age=8 * 3600,          # 8 h session lifetime
    same_site="lax",
    https_only=False,           # allow http in local dev; set True behind TLS in prod
)

# Security headers & cache hardening
@app.middleware("http")
async def no_transform_headers(request: Request, call_next):
    resp: Response = await call_next(request)
    resp.headers.setdefault("Cache-Control", "no-store, no-transform")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    return resp

# Auth middleware: env-token primary → per-user session fallback → redirect to /login
@app.middleware("http")
async def inject_access_token(request: Request, call_next):
    """
    Resolve an access_token and attach it to request.state.
    Priority: 1) REFRESH_TOKEN from env  2) per-user session token  3) redirect to /login
    """
    path = request.url.path

    # Let public paths through without a token
    if path in PUBLIC_PATHS or path.startswith("/static"):
        return await call_next(request)

    access_token: str | None = None

    # 1. Try shared env-token (fast, no user interaction)
    try:
        env_tokens = await tokens_from_env()
        if env_tokens:
            access_token = env_tokens.get("access_token")
    except Exception as e:
        log.warning("Env-token mint failed: %s", e)

    # 2. Fallback — per-user session token (PKCE flow)
    if not access_token:
        try:
            sess_tokens = await tokens_from_session(request)
            if sess_tokens:
                access_token = sess_tokens.get("access_token")
        except Exception as e:
            log.warning("Session token failed: %s", e)

    # 3. No token at all — redirect to login page (for browser) or 401 (for API)
    if not access_token:
        if path.startswith("/api"):
            return JSONResponse({"error": "Authentication required. No env token and no session."}, status_code=401)
        return RedirectResponse("/login-page")

    request.state.access_token = access_token
    return await call_next(request)

# Attach routers & static
app.include_router(auth_router)  # keeps /auth diagnostics
app.include_router(ingest_router, prefix="/api")
app.include_router(strat_router)
app.include_router(analyse_router)
app.include_router(addgate_router)
app.include_router(keys_router)

app.mount(
    "/static",
    StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")),
    name="static",
)
templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)
# Make auth_mode available in every template (for nav Sign-out link)
templates.env.globals["auth_mode"] = AUTH_MODE

# Log routes at startup (helps when a route goes missing)
log.info("Routes registered: %s", [getattr(r, "path", str(r)) for r in app.routes])

# ──────────────────────────────────────────────────────────────────────────────
# Login landing page (per-user PKCE mode)
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/login-page", response_class=HTMLResponse)
async def login_page(request: Request):
    """Serve the sign-in landing page (only reached when no env token is set)."""
    return templates.TemplateResponse("login.html", {"request": request})

# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────

def _access_token(request: Request) -> str:
    at = getattr(request.state, "access_token", None)
    if not at:
        raise HTTPException(401, "Authentication failed")
    return at


# ──────────────────────────────────────────────────────────────────────────────
# Local record cache & helpers
# ──────────────────────────────────────────────────────────────────────────────
# Registered ext.equinor keys (Alternatives, UncertaintySummary, etc.) survive
# OSDU workflow ingestion.  DevelopmentConcept is stored as a proper WPC
# (kind dev:wks:work-product-component--DevelopmentConcept:1.0.0) linked via
# BD Parameters[] and fetched at render-time by _enrich_bd_developmentconcept().
# ──────────────────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent

# (Local record cache removed — all demo records are now in OSDU.)


def _normalize_volumes(data_block: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize OSDU ColumnBasedTable in data_block['Volumes'] to a structure:
    {
      "KeyColumns": [ {ColumnName, ColumnRole, ValueType, ...}, ... ],
      "Columns":    [ {ColumnName, ColumnRole, ValueType, ...}, ... ],
      "ColumnValues": { "<ColumnName>": [v0, v1, ...], ... }
    }
    Handles cases where ColumnValues may arrive as a dict or a list of objects.
    Leaves other shapes untouched (best-effort).
    """
    vol = (data_block or {}).get("Volumes", {}) or {}
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
        return {}

    segments = cv.get("SegmentID") or []
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
        if any("ProductionForecast" in (kv.get("StringParameterKey") or "")
               for kv in keys if isinstance(kv, dict)):
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
    if len(all_col_defs) != len(col_values):
        log.warning("[BD-PROD] Column count mismatch: %d defs vs %d value arrays",
                    len(all_col_defs), len(col_values))

    # Extract values from each positional entry
    # Each entry is {"IntegerColumn": [...]} or {"NumberColumn": [...]}
    col_data: Dict[str, list] = {}
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
    name_map = {
        "OilRate": "OilRate_kSm3d",
        "GasRate": "GasRate_kSm3d",
        "WaterRate": "WaterRate_kSm3d",
        "YearlyOil": "YearlyOil_MSm3",
        "CumulativeOil": "CumOil_MSm3",
        "WaterCut": "WaterCut_pct",
        "RecoveryFactor": "RecoveryFactor_pct",
        "WellsOnline": "WellsOnline",
    }

    result: Dict[str, Any] = {}
    # Key column → Years
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

# Fields to extract from the DevelopmentConcept WPC data block
_DEVCONCEPT_FIELDS = (
    "Summary", "WellCount", "ContingentWells", "MultilateralWells",
    "TemplateSlots", "DrillingCentres", "ReservoirFormation", "FieldArea",
    "WaterDepth_m", "DistanceToHost_km", "HostFacility", "TargetStartUp",
    "FlowlineSpec", "SubseaBoostingPump", "WaterTreatmentCapacity_m3d",
    "InjectionStrategy", "WellPlan",
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


def _parse_kind_inputs(kind: str, kinds_extra: str) -> List[str]:
    """
    Build an ordered, de-duplicated list of kinds from:
      - primary 'kind' input
      - optional 'kinds_extra' (comma / semicolon / newline separated)
    """
    out: List[str] = []
    seen: Set[str] = set()

    candidates: List[str] = []
    if kind:
        candidates.append(kind)

    if kinds_extra:
        for token in re.split(r"[\n,;]+", kinds_extra):
            token = token.strip()
            if token:
                candidates.append(token)

    for k in candidates:
        if k and k not in seen:
            out.append(k)
            seen.add(k)
    return out


def _collect_manifest_kinds() -> List[Dict[str, Any]]:
    """Return an ordered list of OSDU kinds for the search dropdown.

    Uses a fixed priority list for the most-used kinds (instant, no I/O),
    then appends any additional kinds discovered in repo manifests
    alphabetically.
    """
    # ── Priority kinds (displayed first, in this order) ──
    _PRIORITY_KINDS = [
        "osdu:wks:master-data--BusinessDecision:1.0.0",
        "osdu:wks:work-product-component--ReservoirEstimatedVolumes:1.1.0",
        "osdu:wks:work-product-component--ColumnBasedTable:1.4.0",
        "osdu:wks:work-product-component--GeoLabelSet:1.0.0",
        "dev:wks:work-product-component--DevelopmentConcept:1.0.0",
        "osdu:wks:master-data--Risk:1.2.0",
        "osdu:wks:master-data--Reservoir:2.0.0",
        "osdu:wks:master-data--ReservoirSegment:2.0.0",
        "osdu:wks:work-product-component--Activity:1.0.0",
        "osdu:wks:work-product-component--Document:1.2.0",
        "osdu:wks:work-product-component--StratigraphicColumn:1.2.0",
        "osdu:wks:dataset--ETPDataspace:1.0.0",
    ]

    # ── Scan manifests for counts and extra kinds ──
    repo_root = Path(__file__).resolve().parents[1]
    counter: Counter[str] = Counter()

    for p in sorted(repo_root.glob("demo/**/manifest*.json")):
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
            _walk_kinds(payload, counter)
        except Exception:
            continue

    # Build result: priority kinds first, then remaining alphabetically
    seen: set[str] = set()
    result: List[Dict[str, Any]] = []
    for k in _PRIORITY_KINDS:
        result.append({"kind": k, "count": counter.get(k, 0)})
        seen.add(k)
    for k in sorted(counter.keys()):
        if k not in seen:
            result.append({"kind": k, "count": counter[k]})
    return result


def _walk_kinds(node: Any, counter: Counter) -> None:
    """Recursively count ``kind`` values (osdu: and dev: prefixes)."""
    if isinstance(node, dict):
        k = node.get("kind")
        if isinstance(k, str) and (k.startswith("osdu:") or k.startswith("dev:")):
            counter[k] += 1
        for v in node.values():
            _walk_kinds(v, counter)
    elif isinstance(node, list):
        for v in node:
            _walk_kinds(v, counter)


async def _reverse_lookup(
    record_id: str,
    client: httpx.AsyncClient,
    search_url: str,
    hdr: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Find records that reference *record_id* (reverse relationships).

    Uses OSDU Search API with a wildcard query on the record ID.
    Returns a list of ``{id, role, source_path}`` dicts compatible with
    ``extract_osdu_links()`` output.
    """
    try:
        payload = {
            "kind": "*:*:*:*",
            "query": f'"{record_id}"',
            "limit": 20,
            "returnedFields": ["id", "kind"],
        }
        r = await client.post(search_url, headers=hdr, json=payload)
        if r.status_code != 200:
            log.debug("[REV-LOOKUP] search returned %d for %s", r.status_code, record_id)
            return []
        hits = r.json().get("results") or []
        refs: List[Dict[str, Any]] = []
        for h in hits:
            hid = h.get("id", "")
            if hid == record_id:
                continue  # skip self
            if "reference-data--" in hid:
                continue
            refs.append({
                "id": hid,
                "role": "referenced-by",
                "source_path": "(reverse lookup)",
            })
        if refs:
            log.info("[REV-LOOKUP] %s referenced by %d records", record_id, len(refs))
        return refs
    except Exception as e:
        log.debug("[REV-LOOKUP] Failed for %s: %s", record_id, e)
        return []

# ──────────────────────────────────────────────────────────────────────────────
# Pages & actions
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, summary="Home: list dataspaces")
async def home(request: Request):
    try:
        at = _access_token(request)
        dataspaces = await osdu.list_dataspaces(at)
    except Exception as e:
        log.warning("List dataspaces failed: %s", e)
        dataspaces = []
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "view": "home",
            "dataspaces": dataspaces,
            # Defaults for the "Create Dataspace" form (prefilled values)
            "ds_default": os.getenv("DEFAULT_DATASPACE", ""),
            "default_legal_tag": osdu.DEFAULT_LEGAL_TAG,
            "default_owners": ",".join(osdu.DEFAULT_OWNERS),
            "default_viewers": ",".join(osdu.DEFAULT_VIEWERS),
            "default_countries": ",".join(osdu.DEFAULT_COUNTRIES),
        },
    )

@app.post("/dataspaces/create", summary="Create a dataspace with default legal/ACL")
async def dataspaces_create(
    request: Request,
    path: str = Form(...),
    legal: str = Form(osdu.DEFAULT_LEGAL_TAG),
    owners: str = Form(",".join(osdu.DEFAULT_OWNERS)),
    viewers: str = Form(",".join(osdu.DEFAULT_VIEWERS)),
    countries: str = Form(",".join(osdu.DEFAULT_COUNTRIES)),
    custom_json: str = Form("", description="Optional JSON to merge into CustomData"),
):
    at = _access_token(request)

    # Parse optional JSON block
    extra_custom: Dict[str, Any] = {}
    if custom_json and custom_json.strip():
        try:
            extra_custom = json.loads(custom_json)
            if not isinstance(extra_custom, dict):
                raise ValueError("Custom data must be a JSON object")
        except Exception as ex:
            return templates.TemplateResponse(
                "index.html",
                {
                    "request": request,
                    "view": "home",
                    "dataspaces": [],
                    "ds_default": os.getenv("DEFAULT_DATASPACE", ""),
                    "default_legal_tag": osdu.DEFAULT_LEGAL_TAG,
                    "default_owners": ",".join(osdu.DEFAULT_OWNERS),
                    "default_viewers": ",".join(osdu.DEFAULT_VIEWERS),
                    "default_countries": ",".join(osdu.DEFAULT_COUNTRIES),
                    "error": "Invalid custom JSON",
                    "error_detail": str(ex),
                },
                status_code=400,
            )

    try:
        await osdu.create_dataspace(
            at,
            path,
            legal_tag=legal,
            owners=[x.strip() for x in owners.split(",") if x.strip()],
            viewers=[x.strip() for x in viewers.split(",") if x.strip()],
            countries=[x.strip() for x in countries.split(",") if x.strip()],
            extra_custom=extra_custom,
        )
    except HTTPStatusError as e:
        r = e.response
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "view": "home",
                "dataspaces": [],
                "ds_default": os.getenv("DEFAULT_DATASPACE", ""),
                "default_legal_tag": osdu.DEFAULT_LEGAL_TAG,
                "default_owners": ",".join(osdu.DEFAULT_OWNERS),
                "default_viewers": ",".join(osdu.DEFAULT_VIEWERS),
                "default_countries": ",".join(osdu.DEFAULT_COUNTRIES),
                "error": f"Create failed: {r.status_code} {r.reason_phrase}",
                "error_detail": (r.text[:2000] if r.text else ""),
            },
            status_code=400,
        )
    return RedirectResponse(url=f"/d/{urllib.parse.quote(path, safe='')}", status_code=302)

# ──────────────────────────────────────────────────────────────────────────────
# Search (OSDU search v2) — enrich with storage fetch, ancestry, links, metadata
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/search", response_class=HTMLResponse, summary="Search form (OSDU search v2)")
async def search_page(request: Request):
    # Pre-fill demo values
    kind_options = _collect_manifest_kinds()
    default_kind = "osdu:wks:master-data--BusinessDecision:1.0.0"
    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "kind": default_kind,
            "kinds_extra": "",
            "kind_options": kind_options,
            "q": "*",
            "limit": 10,
            "returnedFields": "id,kind,version",
        },
    )

@app.post("/search/run", response_class=HTMLResponse)
async def search_run(
    request: Request,
    kind: str = Form("osdu:wks:work-product-component--ReservoirEstimatedVolumes:1.1.0"),
    kinds_extra: str = Form(""),
    query: str = Form("*"),
    limit: int = Form(5),
):
    """
    Run an OSDU Search v2 query, then enrich each hit:
    • Fetch the full storage record (data{}).
    • Surface ancestry parents/children.
    • Normalize Volumes (ColumnBasedTable) for REV WPCs.
    • Extract WPC/master-data links from data{} (exclude reference-data).
    • Hydrate labels (Name/kind/version) for linked records (bounded).
    • Build compact metadata_pairs from data{}.
    Renders: templates/search.html with:
    results = {
      results: [{ id, kind, version, data, ancestry_parents, ancestry_children,
                  volumes, links, linked_labels, metadata_pairs }, ...],
      totalCount
    }
    """
    at = _access_token(request)
    search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    hdr = osdu.headers(at)

    search_kinds = _parse_kind_inputs(kind, kinds_extra)
    if not search_kinds:
        search_kinds = [kind]

    try:
        enriched_results: List[Dict[str, Any]] = []
        seen_record_ids: Set[str] = set()
        merged_total_count = 0
        async with httpx.AsyncClient(timeout=60) as client:
            for current_kind in search_kinds:
                payload = {
                    "kind": current_kind,
                    "query": query,
                    "limit": int(limit),
                    "returnedFields": ["id", "kind", "version"],
                    "trackTotalCount": True,
                }

                # 1) Search for one kind
                r = await client.post(search_url, headers=hdr, json=payload)
                r.raise_for_status()
                res = r.json()
                merged_total_count += int(res.get("totalCount") or len(res.get("results", [])))
                log.info(
                    "[SEARCH] kind=%s status=%d hits=%d",
                    current_kind,
                    r.status_code,
                    len(res.get("results", [])),
                )

                # 2) Enrich each hit (de-duplicate by record id)
                for rec in res.get("results", []):
                    if len(enriched_results) >= int(limit):
                        break

                    rid = rec.get("id")
                    if not rid or rid in seen_record_ids:
                        continue
                    seen_record_ids.add(rid)

                    try:
                        # Fetch full storage record
                        r_full = await client.get(f"{storage_url}/{rid}", headers=hdr)
                        if r_full.status_code != 200:
                            log.warning("[SEARCH] Full record fetch failed for %s: %d", rid, r_full.status_code)
                            continue
                        full = r_full.json()

                        # data{} block
                        data_block = full.get("data", {}) or {}

                        # Existing: ancestry & volumes normalization
                        ancestry = data_block.get("ancestry", {}) or {}
                        ancestry_parents = ancestry.get("parents", []) or []
                        ancestry_children = ancestry.get("children", []) or []
                        volumes = _normalize_volumes(data_block)

                        # BusinessDecision: pull headline volumes + linked WPC data
                        bd_geolabel: Dict[str, Any] = {}
                        bd_production: Dict[str, Any] = {}
                        if "businessdecision" in (full.get("kind") or "").lower():
                            if not (volumes or {}).get("ColumnValues"):
                                volumes = await _enrich_bd_volumes(
                                    data_block, client, storage_url, hdr)
                            bd_geolabel = await _enrich_bd_geolabel(
                                data_block, client, storage_url, hdr)
                            bd_production = await _enrich_bd_production(
                                data_block, client, storage_url, hdr)
                            await _enrich_bd_developmentconcept(
                                data_block, client, storage_url, hdr)

                        # Generic WPC/master-data links (exclude reference-data)
                        links = extract_osdu_links(data_block) or []

                        # Reverse-lookup: find records that reference this one
                        rev_links = await _reverse_lookup(
                            rid, client, search_url, hdr)
                        fwd_ids = {l["id"] for l in links}
                        for rl in rev_links:
                            if rl["id"] not in fwd_ids:
                                links.append(rl)

                        # Hydrate labels for linked records (bounded)
                        linked_labels: Dict[str, Dict[str, Any]] = {}
                        try:
                            for l in links[:25]:
                                lid = l.get("id")
                                if not lid or lid in linked_labels:
                                    continue
                                r_link = await client.get(f"{storage_url}/{lid}", headers=hdr)
                                if r_link.status_code == 200:
                                    rr = r_link.json()
                                    nm = (rr.get("data") or {}).get("Name")
                                    entry: Dict[str, Any] = {
                                        "name": nm or lid,
                                        "kind": rr.get("kind"),
                                        "version": rr.get("version"),
                                    }
                                    # Include data block for ETPDataspace so templates
                                    # can render the EML URI and server URL directly.
                                    if "ETPDataspace" in (rr.get("kind") or ""):
                                        entry["data"] = rr.get("data") or {}
                                    linked_labels[lid] = entry
                        except Exception as e:
                            log.warning("[SEARCH] Linked record name hydration failed: %s", e)

                        # Compact metadata pairs from data{}
                        try:
                            md = extract_metadata_generic(
                                data_block,
                                ds="",
                                typ=full.get("kind", "") or "",
                                uuid=full.get("id", "") or "",
                                arrays=None,
                                max_string_len=300,
                                max_preview_items=5,
                            )
                            metadata_pairs = md.get("pairs", []) or []
                            metadata_pairs = [
                                p for p in metadata_pairs
                                if not (
                                    str(p.get("name")).lower() == "uri"
                                    and str(p.get("value") or "").startswith("eml:///")
                                )
                            ]
                        except Exception as e:
                            log.warning("[SEARCH] metadata_pairs extraction failed for %s: %s", rid, e)
                            metadata_pairs = []

                        enriched_results.append({
                            "id": full.get("id"),
                            "kind": full.get("kind"),
                            "version": full.get("version"),
                            "data": data_block,
                            "ancestry_parents": ancestry_parents,
                            "ancestry_children": ancestry_children,
                            "volumes": volumes,
                            "links": links,
                            "linked_labels": linked_labels,
                            "metadata_pairs": metadata_pairs,
                            "bd_geolabel": bd_geolabel,
                            "bd_production": bd_production,
                        })
                    except Exception as e:
                        log.warning("[SEARCH] Exception enriching %s: %s", rid, e)

                if len(enriched_results) >= int(limit):
                    break

        return templates.TemplateResponse(
            "search.html",
            {
                "request": request,
                "results": {
                    "results": enriched_results,
                    "totalCount": merged_total_count or len(enriched_results),
                },
                "kind": kind,
                "kinds_extra": kinds_extra,
                "kind_options": _collect_manifest_kinds(),
                "selected_kinds": search_kinds,
                "q": query,
                "limit": limit,
            },
        )
    except httpx.HTTPStatusError as e:
        r = e.response
        log.warning("[SEARCH] HTTP error: %s %s", r.status_code, r.text[:512] if r.text else "")
        return templates.TemplateResponse(
            "search.html",
            {
                "request": request,
                "error": f"Search failed: {r.status_code} {r.reason_phrase}",
                "error_detail": (r.text[:2000] if r.text else ""),
                "kind": kind,
                "kinds_extra": kinds_extra,
                "kind_options": _collect_manifest_kinds(),
                "q": query,
                "limit": limit,
            },
            status_code=r.status_code or 500,
        )
    except Exception as e:
        log.exception("[SEARCH] Unexpected error: %s", e)
        return templates.TemplateResponse(
            "search.html",
            {
                "request": request,
                "error": "Unexpected error",
                "error_detail": "See server logs",
                "kind": kind,
                "kinds_extra": kinds_extra,
                "kind_options": _collect_manifest_kinds(),
                "q": query,
                "limit": limit,
            },
            status_code=500,
        )

@app.get("/search/view/{record_id}", response_class=HTMLResponse)
async def view_record(request: Request, record_id: str):
    """Fetch a single record by ID and render it through the search template."""
    at = _access_token(request)
    storage_url = f"https://{osdu.OSDU_BASE_URL}/api/storage/v2/records"
    search_url = f"https://{osdu.OSDU_BASE_URL}/api/search/v2/query"
    hdr = osdu.headers(at)
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(f"{storage_url}/{record_id}", headers=hdr)
            r.raise_for_status()
            full = r.json()

            data_block = full.get("data", {}) or {}
            ancestry = data_block.get("ancestry", {}) or {}
            volumes = _normalize_volumes(data_block)

            # BusinessDecision: pull headline volumes + linked WPC data
            bd_geolabel: Dict[str, Any] = {}
            bd_production: Dict[str, Any] = {}
            if "businessdecision" in (full.get("kind") or "").lower():
                if not (volumes or {}).get("ColumnValues"):
                    volumes = await _enrich_bd_volumes(
                        data_block, client, storage_url, hdr)
                bd_geolabel = await _enrich_bd_geolabel(
                    data_block, client, storage_url, hdr)
                bd_production = await _enrich_bd_production(
                    data_block, client, storage_url, hdr)
                await _enrich_bd_developmentconcept(
                    data_block, client, storage_url, hdr)

            links = extract_osdu_links(data_block) or []

            # Reverse-lookup: find records that reference this one
            rev_links = await _reverse_lookup(
                record_id, client, search_url, hdr)
            fwd_ids = {l["id"] for l in links}
            for rl in rev_links:
                if rl["id"] not in fwd_ids:
                    links.append(rl)

            linked_labels: Dict[str, Dict[str, Any]] = {}
            try:
                for l in links[:25]:
                    lid = l.get("id")
                    if not lid or lid in linked_labels:
                        continue
                    r_link = await client.get(f"{storage_url}/{lid}", headers=hdr)
                    if r_link.status_code == 200:
                        rr = r_link.json()
                        nm = (rr.get("data") or {}).get("Name")
                        linked_labels[lid] = {
                            "name": nm or lid,
                            "kind": rr.get("kind"),
                            "version": rr.get("version"),
                        }
            except Exception as e:
                log.warning("[VIEW] Linked record name hydration failed: %s", e)

            try:
                md = extract_metadata_generic(
                    data_block, ds="",
                    typ=full.get("kind", "") or "",
                    uuid=full.get("id", "") or "",
                    arrays=None, max_string_len=300, max_preview_items=5,
                )
                metadata_pairs = [
                    p for p in (md.get("pairs", []) or [])
                    if not (str(p.get("name")).lower() == "uri"
                            and str(p.get("value") or "").startswith("eml:///"))
                ]
            except Exception as e:
                log.warning("[VIEW] metadata_pairs extraction failed: %s", e)
                metadata_pairs = []

            enriched = {
                "id": full.get("id"),
                "kind": full.get("kind"),
                "version": full.get("version"),
                "data": data_block,
                "ancestry_parents": ancestry.get("parents", []) or [],
                "ancestry_children": ancestry.get("children", []) or [],
                "volumes": volumes,
                "links": links,
                "linked_labels": linked_labels,
                "metadata_pairs": metadata_pairs,
                "bd_geolabel": bd_geolabel,
                "bd_production": bd_production,
            }

        return templates.TemplateResponse(
            "search.html",
            {
                "request": request,
                "results": {"results": [enriched], "totalCount": 1},
                "kind": full.get("kind", ""),
                "kinds_extra": "",
                "kind_options": _collect_manifest_kinds(),
                "q": record_id,
                "limit": 1,
            },
        )
    except HTTPStatusError as e:
        return templates.TemplateResponse(
            "search.html",
            {
                "request": request,
                "error": f"Record fetch failed: {e.response.status_code}",
                "error_detail": (e.response.text[:2000] if e.response.text else ""),
                "kind": "",
                "kinds_extra": "",
                "kind_options": _collect_manifest_kinds(),
                "q": record_id,
                "limit": 1,
            },
            status_code=e.response.status_code or 500,
        )
    except Exception as e:
        log.exception("[VIEW] Unexpected error: %s", e)
        return templates.TemplateResponse(
            "search.html",
            {
                "request": request,
                "error": "Unexpected error",
                "error_detail": "See server logs",
                "kind": "",
                "kinds_extra": "",
                "kind_options": _collect_manifest_kinds(),
                "q": record_id,
                "limit": 1,
            },
            status_code=500,
        )

