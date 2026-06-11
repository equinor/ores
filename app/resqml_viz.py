"""
RESQML visualization – PG-first with REST fallback.

Provides:
  fetch_grid2d_surface()   – Grid2d metadata + z-values + CRS  (for 2-D map)
  render_grid2d_png()       – Matplotlib PNG rendering
  build_xy_mesh()           – X/Y coordinate arrays
  fetch_geometry_3d()       – Generic 3-D geometry for Three.js viewer

All *fetch* functions try local PostgreSQL first (fast), then fall back to
the remote RDDMS REST API when PG is unavailable or has no data.
"""
from __future__ import annotations

import io
import logging
import math
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

log = logging.getLogger("rddms-admin.resqml_viz")


# ── Array response parsing ───────────────────────────────────────────────────

def _flatten_nested(data) -> list:
    """Recursively flatten nested lists/arrays into a flat list of scalars."""
    if isinstance(data, (int, float)):
        return [data]
    if isinstance(data, list):
        result: list = []
        for item in data:
            if isinstance(item, (list, tuple)):
                result.extend(_flatten_nested(item))
            else:
                result.append(item)
        return result
    return []


def _extract_flat_array(body: Any) -> list:
    """Extract a flat numeric array from varying RDDMS response formats.

    Handles:
      - ``{"data": {"data": [...]}}``  (Microsoft RDDMS)
      - ``{"data": [...]}``, ``{"values": [...]}``
      - ``[...]``  (direct list)
      - Nested 2-D/3-D arrays (flattened)
    """
    if isinstance(body, list):
        return _flatten_nested(body)
    if not isinstance(body, dict):
        return []
    inner = body.get("data") or body.get("values") or body
    if isinstance(inner, list):
        return _flatten_nested(inner)
    if isinstance(inner, dict):
        values = inner.get("data") or inner.get("values") or []
        if isinstance(values, list):
            return _flatten_nested(values)
    return []


# ── XML helpers ──────────────────────────────────────────────────────────────

def _strip_ns(tag: str) -> str:
    """Strip XML namespace prefix: ``{http://…}Foo`` → ``Foo``."""
    return tag.split("}", 1)[1] if "}" in tag else tag


def _xfind(elem, *path):
    """Navigate an ElementTree by local names (ignoring namespace)."""
    cur = elem
    for name in path:
        found = None
        if cur is None:
            return None
        for child in cur:
            if _strip_ns(child.tag) == name:
                found = child
                break
        if found is None:
            return None
        cur = found
    return cur


def _xfindall(elem, name: str):
    """All direct children whose local name matches *name*."""
    if elem is None:
        return []
    return [c for c in elem if _strip_ns(c.tag) == name]


def _xtext(elem, *path, default: str = "") -> str:
    e = _xfind(elem, *path)
    return (e.text or default) if e is not None else default


def _xfloat(elem, *path, default: float = 0.0) -> float:
    t = _xtext(elem, *path, default="")
    try:
        return float(t)
    except (ValueError, TypeError):
        return default


# ── Generic XML → dict converter ────────────────────────────────────────────

def _try_numeric(text: str) -> Any:
    """Convert text to int/float/bool when possible; return str otherwise."""
    if not text:
        return ""
    t = text.strip()
    if not t:
        return ""
    tl = t.lower()
    if tl == "true":
        return True
    if tl == "false":
        return False
    try:
        if "." in t or "e" in tl:
            return float(t)
        return int(t)
    except (ValueError, TypeError):
        return t


def _xml_elem_to_val(elem) -> Any:
    """
    Recursively convert an ElementTree element to a JSON-compatible value.

    Mirrors the shape produced by the Reservoir-DDMS REST ``$format=json``.
    """
    from collections import defaultdict

    children = list(elem)
    text = (elem.text or "").strip()

    # Clean attributes – drop xsi:type / xsi:nil, strip namespace prefixes
    attribs: dict[str, str] = {}
    for k, v in elem.attrib.items():
        clean_k = k.split("}")[-1] if "}" in k else k
        if clean_k in ("type", "nil"):
            continue
        attribs[clean_k] = v

    if not children:
        # Leaf element
        val = _try_numeric(text)
        if attribs:
            d: dict[str, Any] = {}
            if text:
                d["_"] = val
            for ak, av in attribs.items():
                # Capitalize first letter for common keys like uom → Uom
                stored_k = ak[0].upper() + ak[1:] if ak and ak[0].islower() else ak
                d[stored_k] = av
            return d if d else val
        return val

    # Element with children
    result: dict[str, Any] = {}

    tag_groups: dict[str, list] = defaultdict(list)
    for child in children:
        tag_groups[_strip_ns(child.tag)].append(child)

    for tag, elems in tag_groups.items():
        if len(elems) == 1:
            result[tag] = _xml_elem_to_val(elems[0])
        else:
            result[tag] = [_xml_elem_to_val(e) for e in elems]

    # Include attributes on non-leaf elements
    for ak, av in attribs.items():
        stored_k = ak[0].upper() + ak[1:] if ak and ak[0].islower() else ak
        result[stored_k] = av

    # If element has text AND children, store text
    if text:
        result["_text"] = _try_numeric(text)

    return result


def xml_to_dict(xml_str: str) -> dict[str, Any]:
    """
    Convert a RESQML/EML XML string into a JSON-like dict.

    The output closely matches the shape returned by the Reservoir-DDMS
    REST API when ``$format=json`` is requested.
    """
    root = ET.fromstring(xml_str)
    val = _xml_elem_to_val(root)
    return val if isinstance(val, dict) else {}


async def pg_get_object_and_arrays(
    pool, ds: str, typ: str, uuid: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None]:
    """
    Fetch an object's content (as JSON-like dict) and arrays list from PG.

    Returns ``(content_dict, arrays_list)`` or ``(None, None)`` if not found.
    """
    from .pg_backend import pg_list_arrays

    obj_id, xml_str = await _pg_get_obj_id_and_xml(pool, ds, uuid)
    if obj_id is None or not xml_str:
        return None, None

    try:
        content = xml_to_dict(xml_str)
    except ET.ParseError:
        return None, None

    arrays = await pg_list_arrays(pool, ds, uuid)
    return content, arrays


# ── Lattice geometry parsing (from JSON – used by REST path) ─────────────────

def _parse_lattice(
    origin_d: dict[str, Any],
    offsets: list[dict[str, Any]],
    n_slow: int,
    n_fast: int,
) -> dict[str, Any]:
    """
    Parse a RESQML Point3dLatticeArray into a geometry dict.

    Returns origin, u_vec, v_vec, u_space, v_space, n_slow, n_fast.
    """
    ox = float(origin_d.get("Coordinate1", 0))
    oy = float(origin_d.get("Coordinate2", 0))
    oz = float(origin_d.get("Coordinate3", 0))

    def _offset_parts(off: dict[str, Any]) -> tuple[float, float, float]:
        o = off.get("Offset") or {}
        return (
            float(o.get("Coordinate1", 0)),
            float(o.get("Coordinate2", 0)),
            float(o.get("Coordinate3", 0)),
        )

    def _spacing(off: dict[str, Any]) -> float:
        s = off.get("Spacing") or {}
        return float(s.get("Value", 1.0))

    u_dx, u_dy, _ = (0.0, 0.0, 0.0)
    v_dx, v_dy, _ = (0.0, 0.0, 0.0)
    u_space = 1.0
    v_space = 1.0

    if len(offsets) >= 1:
        u_dx, u_dy, _ = _offset_parts(offsets[0])
        u_space = _spacing(offsets[0])
    if len(offsets) >= 2:
        v_dx, v_dy, _ = _offset_parts(offsets[1])
        v_space = _spacing(offsets[1])

    return {
        "origin": (ox, oy, oz),
        "u_vec": (u_dx, u_dy),
        "v_vec": (v_dx, v_dy),
        "u_space": u_space,
        "v_space": v_space,
        "n_slow": n_slow,
        "n_fast": n_fast,
    }


# ── CRS rotation ────────────────────────────────────────────────────────────

def _apply_crs_rotation(
    geometry: dict[str, Any],
    crs: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Apply CRS ArealRotation + XOffset/YOffset to the geometry.

    RESQML LocalDepth3dCrs defines:
      - XOffset, YOffset   – translation of local origin w.r.t. projected CRS
      - ArealRotation      – counter-clockwise angle (degrees) from projected
                             CRS north to local CRS Y-axis

    The grid's origin and offset vectors are in local CRS coordinates.
    To map to projected coordinates:
      P_proj = R(θ) · P_local + (XOffset, YOffset)
    """
    if not crs:
        return geometry

    x_off = float(crs.get("XOffset", 0) or 0)
    y_off = float(crs.get("YOffset", 0) or 0)

    rot_obj = crs.get("ArealRotation") or {}
    angle_deg = float(rot_obj.get("_", 0) or rot_obj.get("Value", 0) or 0)
    uom = (rot_obj.get("Uom") or "dega").lower()
    if "rad" in uom:
        angle_rad = angle_deg  # already radians
    else:
        angle_rad = math.radians(angle_deg)

    if abs(angle_rad) < 1e-12 and abs(x_off) < 1e-6 and abs(y_off) < 1e-6:
        return geometry  # nothing to do

    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    ox, oy, oz = geometry["origin"]
    new_ox = cos_a * ox - sin_a * oy + x_off
    new_oy = sin_a * ox + cos_a * oy + y_off

    ux, uy = geometry["u_vec"]
    new_ux = cos_a * ux - sin_a * uy
    new_uy = sin_a * ux + cos_a * uy

    vx, vy = geometry["v_vec"]
    new_vx = cos_a * vx - sin_a * vy
    new_vy = sin_a * vx + cos_a * vy

    return {
        **geometry,
        "origin": (new_ox, new_oy, oz),
        "u_vec": (new_ux, new_uy),
        "v_vec": (new_vx, new_vy),
    }


# ── Coordinate mesh ─────────────────────────────────────────────────────────

def build_xy_mesh(
    geometry: dict[str, Any],
    crs: dict[str, Any] | None = None,
) -> tuple:
    """
    Build 2-D X and Y coordinate arrays (n_slow × n_fast) in projected CRS,
    correctly handling RESQML offset-vector rotation.

    Returns ``(X, Y)`` ndarrays suitable for matplotlib pcolormesh.
    """
    import numpy as np

    geo = _apply_crs_rotation(geometry, crs)

    ox, oy, _ = geo["origin"]
    ux, uy = geo["u_vec"]
    vx, vy = geo["v_vec"]
    u_sp = geo["u_space"]
    v_sp = geo["v_space"]
    n_slow = geo["n_slow"]
    n_fast = geo["n_fast"]

    i = np.arange(n_slow, dtype=np.float64)
    j = np.arange(n_fast, dtype=np.float64)
    II, JJ = np.meshgrid(i, j, indexing="ij")

    X = ox + II * (ux * u_sp) + JJ * (vx * v_sp)
    Y = oy + II * (uy * u_sp) + JJ * (vy * v_sp)
    return X, Y


# ── PNG renderer ─────────────────────────────────────────────────────────────

def render_grid2d_png(
    zvalues: list[float],
    dims: list[int],
    geometry: dict[str, Any],
    crs: dict[str, Any] | None = None,
    *,
    title: str = "",
    cmap: str = "viridis_r",
    figsize: tuple[int, int] = (10, 8),
    dpi: int = 120,
    nan_sentinel: float = 1e30,
    unit: str = "m",
    show_crs_info: bool = True,
    max_render_dim: int = 500,
) -> bytes:
    """
    Render a Grid2dRepresentation depth surface as a PNG image.

    Handles RESQML offset-vector rotation, CRS transforms, colour bar,
    auto-downsampling for large grids.  Returns PNG bytes.
    """
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize
    from matplotlib.ticker import FuncFormatter

    n_slow, n_fast = dims[0], dims[1]
    total = n_slow * n_fast
    if len(zvalues) < total:
        zvalues = list(zvalues) + [float("nan")] * (total - len(zvalues))

    Z = np.array(zvalues[:total], dtype=np.float64).reshape(n_slow, n_fast)
    Z[np.abs(Z) > nan_sentinel] = np.nan

    X, Y = build_xy_mesh(geometry, crs)

    # Downsample large grids
    step_i = max(1, n_slow // max_render_dim)
    step_j = max(1, n_fast // max_render_dim)
    if step_i > 1 or step_j > 1:
        log.info("render_grid2d_png: downsampling %dx%d → %dx%d (step %d×%d)",
                 n_slow, n_fast,
                 n_slow // step_i, n_fast // step_j,
                 step_i, step_j)
        Z = Z[::step_i, ::step_j]
        X = X[::step_i, ::step_j]
        Y = Y[::step_i, ::step_j]

    # Depth display direction
    z_down = True
    if crs and crs.get("ZIncreasingDownward") is False:
        z_down = False
    Z_plot = Z.copy()

    fig, ax = plt.subplots(1, 1, figsize=figsize, dpi=dpi)

    valid = np.isfinite(Z_plot)
    if valid.any():
        vmin = float(np.nanmin(Z_plot))
        vmax = float(np.nanmax(Z_plot))
    else:
        vmin, vmax = 0, 1

    pcm = ax.pcolormesh(X, Y, Z_plot, cmap=cmap, shading="auto",
                        norm=Normalize(vmin=vmin, vmax=vmax))

    cbar = fig.colorbar(pcm, ax=ax, shrink=0.85, pad=0.02)
    depth_label = f"Depth ({unit})"
    if z_down:
        depth_label += " - increasing downward"
    cbar.set_label(depth_label, fontsize=10)

    ax.set_xlabel("Easting (m)", fontsize=10)
    ax.set_ylabel("Northing (m)", fontsize=10)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3, linewidth=0.5)
    ax.tick_params(labelsize=8)

    x_range = X.max() - X.min()
    y_range = Y.max() - Y.min()

    def _fmt_km(val, _):
        return f"{val / 1000:.1f}"

    if x_range > 5000 or y_range > 5000:
        ax.xaxis.set_major_formatter(FuncFormatter(_fmt_km))
        ax.yaxis.set_major_formatter(FuncFormatter(_fmt_km))
        ax.set_xlabel("Easting (km)", fontsize=10)
        ax.set_ylabel("Northing (km)", fontsize=10)

    if title:
        ax.set_title(title, fontsize=12, fontweight="bold")

    # CRS annotation
    if show_crs_info and crs:
        crs_title = (crs.get("Citation") or {}).get("Title", "")
        rot_obj = crs.get("ArealRotation") or {}
        rot_val = rot_obj.get("_", 0) or rot_obj.get("Value", 0) or 0
        wkt_short = ""
        for em in (crs.get("ExtraMetadata") or []):
            if isinstance(em, dict) and "Wkt" in (em.get("Name") or ""):
                wkt = em.get("Value", "")
                import re as _re
                m = _re.search(r'PROJCS\["([^"]+)"', wkt)
                if m:
                    wkt_short = m.group(1)
                break
        info_parts = []
        if crs_title:
            info_parts.append(crs_title)
        if wkt_short:
            info_parts.append(wkt_short)
        if abs(float(rot_val)) > 0.001:
            info_parts.append(f"rot={rot_val}°")
        if info_parts:
            ax.annotate(
                " | ".join(info_parts),
                xy=(0.01, 0.01), xycoords="axes fraction",
                fontsize=7, color="gray", alpha=0.8,
            )

    # Grid rotation annotation
    ux, uy = geometry.get("u_vec", (1, 0))
    angle = math.degrees(math.atan2(ux, uy))
    if abs(angle) > 0.1:
        ax.annotate(
            f"Grid rotation: {angle:.1f}° from N",
            xy=(0.99, 0.01), xycoords="axes fraction",
            fontsize=7, color="gray", alpha=0.8, ha="right",
        )

    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=dpi)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ── PNG renderer for TriangulatedSetRepresentation ───────────────────────────

def render_triset_png(
    positions: list[float],
    indices: list[int],
    *,
    title: str = "",
    cmap: str = "viridis_r",
    figsize: tuple[int, int] = (10, 8),
    dpi: int = 120,
    nan_sentinel: float = 1e30,
    unit: str = "m",
    max_render_tris: int = 200_000,
) -> bytes:
    """
    Render a TriangulatedSetRepresentation as a top-down depth-coloured map.

    Uses matplotlib's ``tripcolor`` for native triangulated surface rendering.
    Returns PNG bytes.
    """
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.tri import Triangulation
    from matplotlib.colors import Normalize
    from matplotlib.ticker import FuncFormatter

    n_verts = len(positions) // 3
    if n_verts < 3:
        raise ValueError(f"Too few vertices ({n_verts}) for triangulation")

    x = np.array([positions[i * 3] for i in range(n_verts)], dtype=np.float64)
    y = np.array([positions[i * 3 + 1] for i in range(n_verts)], dtype=np.float64)
    z = np.array([positions[i * 3 + 2] for i in range(n_verts)], dtype=np.float64)
    z[np.abs(z) > nan_sentinel] = np.nan

    n_tris = len(indices) // 3
    triangles = (
        np.array(indices[: n_tris * 3], dtype=np.int32).reshape(n_tris, 3)
        if n_tris > 0
        else None
    )

    # Downsample very large meshes
    if triangles is not None and n_tris > max_render_tris:
        step = max(1, n_tris // max_render_tris)
        triangles = triangles[::step]
        used = np.unique(triangles.ravel())
        remap = np.full(n_verts, -1, dtype=np.int32)
        remap[used] = np.arange(len(used), dtype=np.int32)
        x, y, z = x[used], y[used], z[used]
        triangles = remap[triangles]
        n_verts = len(used)
        log.info("render_triset_png: downsampled to %d verts, %d tris",
                 n_verts, len(triangles))

    valid = np.isfinite(z)
    if not valid.any():
        raise ValueError("All z-values are NaN or infinite")
    vmin, vmax = float(z[valid].min()), float(z[valid].max())

    if triangles is not None:
        tri = Triangulation(x, y, triangles)
    else:
        tri = Triangulation(x, y)  # Delaunay fallback

    fig, ax = plt.subplots(1, 1, figsize=figsize, dpi=dpi)

    tcf = ax.tripcolor(
        tri, z, cmap=cmap, shading="gouraud",
        norm=Normalize(vmin=vmin, vmax=vmax),
    )

    cbar = fig.colorbar(tcf, ax=ax, shrink=0.85, pad=0.02)
    cbar.set_label(f"Depth ({unit})", fontsize=10)

    ax.set_xlabel("Easting (m)", fontsize=10)
    ax.set_ylabel("Northing (m)", fontsize=10)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3, linewidth=0.5)
    ax.tick_params(labelsize=8)

    x_range = x.max() - x.min()
    y_range = y.max() - y.min()

    def _fmt_km(val, _):
        return f"{val / 1000:.1f}"

    if x_range > 5000 or y_range > 5000:
        ax.xaxis.set_major_formatter(FuncFormatter(_fmt_km))
        ax.yaxis.set_major_formatter(FuncFormatter(_fmt_km))
        ax.set_xlabel("Easting (km)", fontsize=10)
        ax.set_ylabel("Northing (km)", fontsize=10)

    if title:
        ax.set_title(title, fontsize=12, fontweight="bold")

    # Stats annotation
    ax.annotate(
        f"{n_verts:,} verts · {n_tris:,} tris · z: {vmin:.1f}…{vmax:.1f} {unit}",
        xy=(0.01, 0.01), xycoords="axes fraction",
        fontsize=7, color="gray", alpha=0.8,
    )

    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=dpi)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ═══════════════════════════════════════════════════════════════════════════════
# PostgreSQL path  (fast, local)
# ═══════════════════════════════════════════════════════════════════════════════

async def _pg_get_obj_id_and_xml(pool, ds: str, uuid: str):
    """Return ``(obj_id, xml_string)`` from PG, or ``(None, None)``."""
    from .pg_backend import pg_schema_for_dataspace
    schema = await pg_schema_for_dataspace(pool, ds)
    if not schema:
        return None, None
    async with pool.acquire() as conn:
        src = await conn.fetchrow(
            f"SELECT obj_id FROM {schema}.res WHERE guid=$1", uuid,
        )
        if not src:
            return None, None
        obj_id = src["obj_id"]
        row = await conn.fetchrow(
            f"SELECT xml FROM {schema}.obj WHERE id=$1", obj_id,
        )
        xml_str = str(row["xml"]) if row and row["xml"] else None
        return obj_id, xml_str


async def _pg_parse_crs(pool, ds: str, crs_uuid: str) -> dict[str, Any] | None:
    """Parse a CRS object from PG XML into a dict matching REST JSON shape."""
    _, xml_str = await _pg_get_obj_id_and_xml(pool, ds, crs_uuid)
    if not xml_str:
        return None
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return None

    title = _xtext(root, "Citation", "Title")
    x_off = _xfloat(root, "XOffset")
    y_off = _xfloat(root, "YOffset")

    rot_elem = _xfind(root, "ArealRotation")
    rot_val = 0.0
    rot_uom = "dega"
    if rot_elem is not None:
        try:
            rot_val = float(rot_elem.text or 0)
        except (ValueError, TypeError):
            rot_val = 0.0
        rot_uom = rot_elem.get("uom", "dega")

    proj_uom = _xtext(root, "ProjectedUom", default="m")
    vert_uom = _xtext(root, "VerticalUom", default="m")
    z_down_text = _xtext(root, "ZIncreasingDownward", default="true")
    z_down = z_down_text.lower() not in ("false", "0")
    proj_axis = _xtext(root, "ProjectedAxisOrder", default="")

    crs: dict[str, Any] = {
        "Citation": {"Title": title},
        "XOffset": x_off,
        "YOffset": y_off,
        "ArealRotation": {"_": rot_val, "Uom": rot_uom},
        "ProjectedUom": proj_uom,
        "VerticalUom": vert_uom,
        "ZIncreasingDownward": z_down,
        "ProjectedAxisOrder": proj_axis,
    }

    # WKT in ExtraMetadata
    for em in _xfindall(root, "ExtraMetadata"):
        name = _xtext(em, "Name")
        if "Wkt" in name:
            crs.setdefault("ExtraMetadata", []).append({
                "Name": name,
                "Value": _xtext(em, "Value"),
            })
    return crs


async def _pg_grid2d_surface(pool, ds: str, uuid: str) -> dict[str, Any] | None:
    """Fetch Grid2d surface data from PG (XML + arrays)."""
    from .pg_backend import pg_list_arrays, pg_read_array

    _, xml_str = await _pg_get_obj_id_and_xml(pool, ds, uuid)
    if not xml_str:
        return None
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return None

    patch = _xfind(root, "Grid2dPatch")
    if patch is None:
        return None

    n_fast = int(_xtext(patch, "FastestAxisCount", default="0") or 0)
    n_slow = int(_xtext(patch, "SlowestAxisCount", default="0") or 0)
    if n_fast == 0 or n_slow == 0:
        return None

    # Geometry / lattice
    geom = _xfind(patch, "Geometry")
    points = _xfind(geom, "Points") if geom else None
    supporting = _xfind(points, "SupportingGeometry") if points else None
    origin_src = supporting if supporting is not None else points
    origin_elem = _xfind(origin_src, "Origin") if origin_src else None

    ox = _xfloat(origin_elem, "Coordinate1") if origin_elem else 0.0
    oy = _xfloat(origin_elem, "Coordinate2") if origin_elem else 0.0
    oz = _xfloat(origin_elem, "Coordinate3") if origin_elem else 0.0

    offsets = _xfindall(origin_src, "Offset") if origin_src is not None else []

    def _parse_xml_offset(off_elem):
        inner = _xfind(off_elem, "Offset")
        dx = _xfloat(inner, "Coordinate1") if inner else 0.0
        dy = _xfloat(inner, "Coordinate2") if inner else 0.0
        spacing_elem = _xfind(off_elem, "Spacing")
        spacing = _xfloat(spacing_elem, "Value") if spacing_elem else 1.0
        return dx, dy, spacing

    u_dx, u_dy, u_space = 0.0, 0.0, 1.0
    v_dx, v_dy, v_space = 0.0, 0.0, 1.0
    if len(offsets) >= 1:
        u_dx, u_dy, u_space = _parse_xml_offset(offsets[0])
    if len(offsets) >= 2:
        v_dx, v_dy, v_space = _parse_xml_offset(offsets[1])

    geometry = {
        "origin": (ox, oy, oz),
        "u_vec": (u_dx, u_dy),
        "v_vec": (v_dx, v_dy),
        "u_space": u_space,
        "v_space": v_space,
        "n_slow": n_slow,
        "n_fast": n_fast,
    }

    # CRS
    crs = None
    local_crs = _xfind(geom, "LocalCrs") if geom else None
    if local_crs is not None:
        crs_uuid_text = _xtext(local_crs, "UUID") or _xtext(local_crs, "Uuid")
        if crs_uuid_text:
            crs = await _pg_parse_crs(pool, ds, crs_uuid_text.strip())

    # Z-values
    arrays = await pg_list_arrays(pool, ds, uuid)
    zvalues: list[float] = []
    for a in arrays:
        p = a["path"].lower()
        if "points_patch" in p or "zvalues" in p:
            zvalues = await pg_read_array(pool, ds, uuid, a["path"])
            break
    if not zvalues and arrays:
        zvalues = await pg_read_array(pool, ds, uuid, arrays[0]["path"])

    # Build grid dict matching REST JSON shape
    title = _xtext(root, "Citation", "Title")
    grid: dict[str, Any] = {
        "Citation": {"Title": title},
        "Grid2dPatch": {
            "FastestAxisCount": n_fast,
            "SlowestAxisCount": n_slow,
        },
    }
    # RepresentedInterpretation (for map.png title enrichment)
    interp = _xfind(root, "RepresentedInterpretation")
    if interp is not None:
        interp_title = _xtext(interp, "Title")
        if interp_title:
            grid["RepresentedInterpretation"] = {"Title": interp_title}

    return {
        "grid": grid,
        "zvalues": zvalues,
        "dims": [n_slow, n_fast],
        "crs": crs,
        "geometry": geometry,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Unified geometry builder (shared by PG and REST paths)
# ═══════════════════════════════════════════════════════════════════════════════

async def _build_geometry_result(
    typ: str,
    title: str,
    arr_paths: dict[str, str],
    read_fn,
    fallback_paths: list[str],
    marker_labels: list[str] | None = None,
) -> dict[str, Any] | None:
    """Build a geometry result dict from arrays for the Three.js viewer.

    This is the single implementation for all non-Grid2d RESQML types.
    Both PG and REST callers prepare their reader and call this.

    Args:
        typ: RESQML type string (matched case-insensitively).
        title: Display title for the object.
        arr_paths: ``{lowered_path: original_path}`` of available arrays.
        read_fn: ``async (path) -> list[float]`` - reads an array by path.
        fallback_paths: Ordered original paths for positional fallback reads.
        marker_labels: Pre-extracted labels for WellboreMarkerFrame objects.

    Returns a dict with ``kind`` + geometry arrays, or ``None`` if *typ* is
    not recognised.
    """
    tl = typ.lower()

    async def _find_read(*keywords: str) -> list[float]:
        """Read first array whose path contains any keyword."""
        for lk, rp in arr_paths.items():
            if any(kw in lk for kw in keywords):
                return [float(v) for v in await read_fn(rp)]
        return []

    async def _find_read_int(*keywords: str) -> list[int]:
        for lk, rp in arr_paths.items():
            if any(kw in lk for kw in keywords):
                return [int(v) for v in await read_fn(rp)]
        return []

    async def _fallback_read(idx: int, cast=float) -> list:
        if idx < len(fallback_paths):
            return [cast(v) for v in await read_fn(fallback_paths[idx])]
        return []

    def _z_stats(positions: list[float]) -> tuple[float, float]:
        n = len(positions) // 3
        z = [positions[i * 3 + 2] for i in range(n)] if positions else []
        return (min(z) if z else 0, max(z) if z else 1)

    # ── TriangulatedSetRepresentation ─────────────────────────────────
    if "triangulated" in tl:
        positions = await _find_read("points", "node", "coordinates")
        indices = await _find_read_int("triangle", "indices")
        if not positions:
            positions = await _fallback_read(0)
        if not indices:
            indices = await _fallback_read(1, cast=int)
        zmin, zmax = _z_stats(positions)
        return {"kind": "surface", "title": title, "positions": positions,
                "indices": indices, "zmin": zmin, "zmax": zmax}

    # ── PointSetRepresentation ────────────────────────────────────────
    if "pointset" in tl:
        positions = await _find_read("points", "node", "coordinates")
        if not positions:
            positions = await _fallback_read(0)
        zmin, zmax = _z_stats(positions)
        return {"kind": "points", "title": title, "positions": positions,
                "zmin": zmin, "zmax": zmax}

    # ── WellboreTrajectoryRepresentation ──────────────────────────────
    if "trajectory" in tl:
        positions = await _find_read("controlpoints", "points", "xyz")
        if not positions:
            positions = await _fallback_read(0)
        md_values = await _find_read("md", "measureddepth")
        zmin, zmax = _z_stats(positions)
        return {"kind": "trajectory", "title": title, "positions": positions,
                "md": md_values, "zmin": zmin, "zmax": zmax}

    # ── WellboreMarkerFrameRepresentation ─────────────────────────────
    if "marker" in tl:
        md_values = await _find_read("md", "nodemd", "measureddepth")
        positions = await _find_read("points", "xyz", "coordinates")
        zmin = min(md_values) if md_values else 0
        zmax = max(md_values) if md_values else 1
        return {"kind": "markers", "title": title, "positions": positions,
                "md": md_values, "labels": marker_labels or [],
                "zmin": zmin, "zmax": zmax}

    # ── PolylineSetRepresentation ─────────────────────────────────────
    if "polylineset" in tl:
        # Read counts first so we can exclude the count array from positions.
        counts = await _find_read_int("count", "nodecount")
        # Positions: prefer explicit point/coordinate arrays; never pick a
        # "count" array (e.g. node_counts also contains the token "node").
        positions: list[float] = []
        for lk, rp in arr_paths.items():
            if "count" in lk:
                continue
            if any(kw in lk for kw in ("points", "coordinates", "node")):
                positions = [float(v) for v in await read_fn(rp)]
                break
        if not positions:
            # Positional fallback: first non-count array.
            for rp in fallback_paths:
                if "count" not in rp.lower():
                    positions = [float(v) for v in await read_fn(rp)]
                    break
        zmin, zmax = _z_stats(positions)
        return {"kind": "polylines", "title": title, "positions": positions,
                "counts": counts, "zmin": zmin, "zmax": zmax}

    # ── DeviationSurveyRepresentation ─────────────────────────────────
    if "deviationsurvey" in tl:
        md_values = await _find_read("md", "measureddepth")
        if not md_values:
            md_values = await _fallback_read(0)
        inclinations = await _find_read("inclin", "inclination")
        azimuths = await _find_read("azimuth")
        positions = _devsurv_to_xyz(md_values, inclinations, azimuths)
        zmin, zmax = _z_stats(positions)
        return {"kind": "trajectory", "title": title, "positions": positions,
                "md": md_values, "zmin": zmin, "zmax": zmax}

    # ── IjkGridRepresentation ─────────────────────────────────────────
    if "ijkgrid" in tl:
        # IjkGrid stores pillar/corner-point geometry as a large Points array.
        # Render as a point cloud of pillar coordinates for now.
        positions = await _find_read("points", "pillar", "coordinates", "nodes")
        if not positions:
            positions = await _fallback_read(0)
        zmin, zmax = _z_stats(positions)
        return {"kind": "points", "title": title, "positions": positions,
                "zmin": zmin, "zmax": zmax}

    return None


async def _pg_geometry3d(pool, ds: str, typ: str, uuid: str) -> dict[str, Any] | None:
    """Build 3-D geometry dict from local PostgreSQL.

    Returns ``None`` when the object / arrays are not found in PG.
    """
    from .pg_backend import pg_list_arrays, pg_read_array, pg_list_resources

    tl = typ.lower()

    # ── Grid2dRepresentation (use XML + arrays) ───────────────────────
    if "grid2d" in tl:
        surface = await _pg_grid2d_surface(pool, ds, uuid)
        if not surface:
            return None
        return _surface_to_3d(surface)

    # For non-Grid2d types, get title + arrays
    resources = await pg_list_resources(pool, ds, typ, limit=500)
    title = uuid
    for r in resources:
        if r.get("uuid", "").lower() == uuid.lower():
            title = r.get("title") or uuid
            break

    arrays = await pg_list_arrays(pool, ds, uuid)
    if not arrays:
        return None

    arr_paths = {a["path"].lower(): a["path"] for a in arrays}
    fallback_paths = [a["path"] for a in arrays]

    async def _read(path: str) -> list[float]:
        return await pg_read_array(pool, ds, uuid, path)

    # Marker labels from XML
    marker_labels: list[str] | None = None
    if "marker" in tl:
        marker_labels = []
        _, xml_str = await _pg_get_obj_id_and_xml(pool, ds, uuid)
        if xml_str:
            try:
                root = ET.fromstring(xml_str)
                for wm in _xfindall(root, "WellboreMarker"):
                    label = (
                        _xtext(wm, "MarkerName")
                        or _xtext(wm, "Interpretation", "Title")
                        or _xtext(wm, "Citation", "Title")
                    )
                    marker_labels.append(label)
            except ET.ParseError:
                pass

    return await _build_geometry_result(
        typ, title, arr_paths, _read, fallback_paths, marker_labels,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# REST path  (remote RDDMS)
# ═══════════════════════════════════════════════════════════════════════════════

async def _rest_grid2d_surface(
    access_token: str, ds: str, uuid: str,
) -> dict[str, Any]:
    """Fetch Grid2d surface via RDDMS REST API."""
    from . import osdu

    enc = urllib.parse.quote(ds, safe="")
    hdr = osdu.headers(access_token)

    async with osdu._http(timeout=120) as client:
        # Try both RESQML 2.0.1 and 2.2 type names
        grid = None
        base_obj = ""
        for typ in ("resqml20.obj_Grid2dRepresentation", "resqml22.Grid2dRepresentation"):
            url = osdu._rddms_url(f"/dataspaces/{enc}/resources/{typ}/{uuid}")
            try:
                r1 = await client.get(url, headers=hdr, params={"$format": "json"})
                if r1.status_code == 404:
                    continue
                r1.raise_for_status()
                grid = osdu._normalize_obj(r1.json(), uuid)
                if grid:
                    base_obj = url
                    break
            except Exception:
                continue
        if not grid:
            raise ValueError(f"Grid2d {uuid} not found in dataspace {ds}")

        patch = grid.get("Grid2dPatch") or {}
        n_fast = int(patch.get("FastestAxisCount", 0))
        n_slow = int(patch.get("SlowestAxisCount", 0))
        geom = patch.get("Geometry") or {}
        points = geom.get("Points") or {}

        supporting = points.get("SupportingGeometry") or {}
        origin_d = supporting.get("Origin") or points.get("Origin") or {}
        offsets = supporting.get("Offset") or points.get("Offset") or []

        geometry = _parse_lattice(origin_d, offsets, n_slow, n_fast)

        # Resolve CRS (try both 2.0.1 and 2.2 type names)
        crs_ref = geom.get("LocalCrs") or {}
        crs = crs_ref.get("_data")
        if not crs:
            crs_uuid = crs_ref.get("UUID") or crs_ref.get("Uuid")
            if crs_uuid:
                ct = crs_ref.get("ContentType", "")
                if "LocalTime3dCrs" in ct:
                    crs_types = ["resqml20.obj_LocalTime3dCrs", "resqml22.LocalTime3dCrs"]
                else:
                    crs_types = ["resqml20.obj_LocalDepth3dCrs", "resqml22.LocalDepth3dCrs"]
                for crs_typ in crs_types:
                    try:
                        r_crs = await client.get(
                            osdu._rddms_url(f"/dataspaces/{enc}/resources/{crs_typ}/{crs_uuid}"),
                            headers=hdr, params={"$format": "json"},
                        )
                        if r_crs.status_code == 404:
                            continue
                        r_crs.raise_for_status()
                        crs = osdu._normalize_obj(r_crs.json(), crs_uuid)
                        if crs:
                            break
                    except Exception as e:
                        log.warning("_rest_grid2d_surface: CRS fetch failed (%s): %s", crs_typ, e)
                        continue

        # Z-values
        r_al = await client.get(f"{base_obj}/arrays", headers=hdr)
        if r_al.status_code in (404, 405, 412):
            log.warning("_rest_grid2d_surface: HTTP %d on arrays for %s",
                        r_al.status_code, uuid)
            arr_list = []
        else:
            r_al.raise_for_status()
            arr_list = r_al.json() or []

        arr_path = ""
        for a in arr_list:
            uid = a.get("uid") or {}
            pir = uid.get("pathInResource", "")
            if "points_patch" in pir.lower() or "zvalues" in pir.lower() or "z_values" in pir.lower():
                arr_path = pir
                break
        if not arr_path and arr_list:
            arr_path = (arr_list[0].get("uid") or {}).get("pathInResource", "")

        zvalues: list[float] = []
        if arr_path:
            arr_enc = urllib.parse.quote(arr_path, safe="")
            r_arr = await client.get(f"{base_obj}/arrays/{arr_enc}", headers=hdr)
            r_arr.raise_for_status()
            arr_body = r_arr.json() or {}
            zvalues = _extract_flat_array(arr_body)

    return {
        "grid": grid,
        "zvalues": zvalues,
        "dims": [n_slow, n_fast],
        "crs": crs,
        "geometry": geometry,
    }


async def _rest_geometry3d(
    access_token: str, ds: str, typ: str, uuid: str,
) -> dict[str, Any]:
    """Fetch 3-D geometry via RDDMS REST API."""
    from . import osdu

    enc = urllib.parse.quote(ds, safe="")
    hdr = osdu.headers(access_token)

    async with osdu._http(timeout=120) as client:
        obj_url = osdu._rddms_url(f"/dataspaces/{enc}/resources/{typ}/{uuid}")
        r1 = await client.get(obj_url, headers=hdr, params={"$format": "json"})
        r1.raise_for_status()
        obj = osdu._normalize_obj(r1.json(), uuid)

        title = (obj.get("Citation") or {}).get("Title") or uuid
        tl = typ.lower()

        # ── Grid2d is handled by its specialised REST function ────────
        if "grid2d" in tl:
            surface = await _rest_grid2d_surface(access_token, ds, uuid)
            return _surface_to_3d(surface)

        r_al = await client.get(f"{obj_url}/arrays", headers=hdr)
        if r_al.status_code in (404, 405, 412):
            log.warning("_rest_geometry3d: HTTP %d on arrays for %s/%s",
                        r_al.status_code, typ, uuid)
            arr_list = []
        else:
            r_al.raise_for_status()
            arr_list = r_al.json() or []

        async def _read_arr(path: str) -> list:
            arr_enc = urllib.parse.quote(path, safe="")
            r = await client.get(f"{obj_url}/arrays/{arr_enc}", headers=hdr)
            r.raise_for_status()
            body = r.json() or {}
            return _extract_flat_array(body)

        arr_paths: dict[str, str] = {}
        fallback_paths: list[str] = []
        for a in arr_list:
            uid = a.get("uid") or {}
            p = uid.get("pathInResource", "")
            arr_paths[p.lower()] = p
            fallback_paths.append(p)

        # Fallback: if array listing is empty, extract PathInHdfFile from object JSON
        if not arr_paths:
            def _extract_hdf_paths(node: Any, paths: list[str]) -> None:
                if isinstance(node, dict):
                    if "PathInHdfFile" in node:
                        paths.append(node["PathInHdfFile"])
                    for v in node.values():
                        _extract_hdf_paths(v, paths)
                elif isinstance(node, list):
                    for item in node:
                        _extract_hdf_paths(item, paths)
            hdf_paths: list[str] = []
            _extract_hdf_paths(obj, hdf_paths)
            for p in hdf_paths:
                arr_paths[p.lower()] = p
                fallback_paths.append(p)

        # Marker labels from REST JSON object
        marker_labels: list[str] | None = None
        if "marker" in tl:
            marker_labels = []
            for m in obj.get("WellboreMarker") or []:
                label = (
                    m.get("MarkerName")
                    or (m.get("Interpretation") or {}).get("Title")
                    or (m.get("Citation") or {}).get("Title")
                    or ""
                )
                marker_labels.append(label)

        result = await _build_geometry_result(
            typ, title, arr_paths, _read_arr, fallback_paths, marker_labels,
        )
        if result is None:
            raise ValueError(f"Unsupported type for 3D: {typ}")
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# Deviation survey → XYZ conversion
# ═══════════════════════════════════════════════════════════════════════════════

def _devsurv_to_xyz(
    md_values: list[float],
    inclinations: list[float],
    azimuths: list[float],
) -> list[float]:
    """Convert MD + inclination + azimuth arrays to XYZ positions.

    Uses the minimum-curvature method.  Returns interleaved ``[x,y,z,...]``.
    If inclination/azimuth are missing, projects straight down.
    """
    n = len(md_values)
    if n == 0:
        return []
    if not inclinations or not azimuths:
        # Straight-down projection
        return [v for md in md_values for v in (0.0, 0.0, md)]

    positions: list[float] = [0.0, 0.0, 0.0]  # origin
    for i in range(1, min(n, len(inclinations), len(azimuths))):
        md1, md0 = md_values[i], md_values[i - 1]
        dmd = md1 - md0
        inc0 = math.radians(inclinations[i - 1])
        inc1 = math.radians(inclinations[i])
        azi0 = math.radians(azimuths[i - 1])
        azi1 = math.radians(azimuths[i])

        # Minimum curvature
        cos_dl = (
            math.cos(inc1 - inc0)
            - math.sin(inc0) * math.sin(inc1) * (1 - math.cos(azi1 - azi0))
        )
        cos_dl = max(-1.0, min(1.0, cos_dl))
        dl = math.acos(cos_dl)
        rf = 1.0 if abs(dl) < 1e-7 else 2.0 / dl * math.tan(dl / 2.0)

        dx = 0.5 * dmd * (math.sin(inc0) * math.sin(azi0) + math.sin(inc1) * math.sin(azi1)) * rf
        dy = 0.5 * dmd * (math.sin(inc0) * math.cos(azi0) + math.sin(inc1) * math.cos(azi1)) * rf
        dz = 0.5 * dmd * (math.cos(inc0) + math.cos(inc1)) * rf

        positions.append(positions[-3] + dx)
        positions.append(positions[-3] + dy)
        positions.append(positions[-3] + dz)

    return positions


# ═══════════════════════════════════════════════════════════════════════════════
# Surface → 3-D mesh conversion  (shared by PG and REST Grid2d paths)
# ═══════════════════════════════════════════════════════════════════════════════

def _surface_to_3d(surface: dict[str, Any]) -> dict[str, Any]:
    """Convert a ``fetch_grid2d_surface`` result into a Three.js geometry dict."""
    import numpy as np

    geo = surface["geometry"]
    crs = surface["crs"]
    zvals = surface["zvalues"]
    dims = surface["dims"]
    n_slow, n_fast = dims

    X, Y = build_xy_mesh(geo, crs)
    total = n_slow * n_fast
    if len(zvals) < total:
        zvals = list(zvals) + [float("nan")] * (total - len(zvals))
    Z = np.array(zvals[:total], dtype=np.float64).reshape(n_slow, n_fast)
    Z[np.abs(Z) > 1e30] = np.nan

    # Downsample very large grids for WebGL
    max_dim = 300
    step_i = max(1, n_slow // max_dim)
    step_j = max(1, n_fast // max_dim)
    if step_i > 1 or step_j > 1:
        X = X[::step_i, ::step_j]
        Y = Y[::step_i, ::step_j]
        Z = Z[::step_i, ::step_j]
        n_slow, n_fast = Z.shape

    # Flatten to interleaved [x,y,z, x,y,z, ...]
    positions: list[float] = []
    for j in range(n_slow):
        for i in range(n_fast):
            z = float(Z[j, i])
            positions.extend([
                float(X[j, i]), float(Y[j, i]),
                z if not np.isnan(z) else 0.0,
            ])

    # Triangle indices
    indices: list[int] = []
    for j in range(n_slow - 1):
        for i in range(n_fast - 1):
            a = j * n_fast + i
            b = a + 1
            c = a + n_fast
            d = c + 1
            za, zb, zc, zd = Z[j, i], Z[j, i + 1], Z[j + 1, i], Z[j + 1, i + 1]
            if np.isfinite(za) and np.isfinite(zb) and np.isfinite(zc):
                indices.extend([a, b, c])
            if np.isfinite(zb) and np.isfinite(zd) and np.isfinite(zc):
                indices.extend([b, d, c])

    z_arr = Z.flatten()
    valid = z_arr[np.isfinite(z_arr)]
    zmin = float(np.min(valid)) if len(valid) else 0
    zmax = float(np.max(valid)) if len(valid) else 1

    title = (surface["grid"].get("Citation") or {}).get("Title") or ""

    return {
        "kind": "surface",
        "title": title,
        "positions": positions,
        "indices": indices,
        "zmin": zmin,
        "zmax": zmax,
        "dims": [n_slow, n_fast],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Public API  (PG-first, REST fallback)
# ═══════════════════════════════════════════════════════════════════════════════

async def fetch_grid2d_surface(
    access_token: str,
    ds: str,
    uuid: str,
) -> dict[str, Any]:
    """
    Fetch a Grid2dRepresentation surface (metadata, z-values, CRS, geometry).

    Cascades:  local PG → remote RDDMS PG → RDDMS REST API.

    Returns ``{grid, zvalues, dims, crs, geometry}``.
    """
    # ── 1. Local PG (co-located, fastest) ─────────────────────────────
    try:
        from .pg_backend import get_pool
        pool = await get_pool()
        if pool:
            result = await _pg_grid2d_surface(pool, ds, uuid)
            if result:
                log.info("fetch_grid2d_surface: served from local PG ds=%s uuid=%s", ds, uuid)
                return result
    except Exception as e:
        log.warning("fetch_grid2d_surface: local PG failed: %s", e)

    # ── 2. Remote RDDMS PG (direct SQL to cloud DB) ───────────────────
    try:
        from .pg_backend import get_rddms_pool
        rddms_pool = await get_rddms_pool()
        if rddms_pool:
            result = await _pg_grid2d_surface(rddms_pool, ds, uuid)
            if result:
                log.info("fetch_grid2d_surface: served from remote PG ds=%s uuid=%s", ds, uuid)
                return result
    except Exception as e:
        log.warning("fetch_grid2d_surface: remote PG failed, falling back to REST: %s", e)

    # ── 3. REST fallback (any RDDMS instance) ─────────────────────────
    return await _rest_grid2d_surface(access_token, ds, uuid)


# ═══════════════════════════════════════════════════════════════════════════════
# Property visualization helpers
# ═══════════════════════════════════════════════════════════════════════════════

_PROPERTY_KEYWORDS = ("continuousproperty", "discreteproperty", "categoricalproperty")


def _is_property_type(tl: str) -> bool:
    """Return True if type-string (lowered) is a RESQML property type."""
    return any(k in tl for k in _PROPERTY_KEYWORDS)


def _extract_rep_type_from_content_type(ct: str) -> str | None:
    """Extract the RDDMS type name from a ContentType string.

    E.g. 'application/x-resqml+xml;version=2.0;type=obj_IjkGridRepresentation'
      → 'resqml20.obj_IjkGridRepresentation'
    Or  'application/x-resqml+xml;version=2.2;type=IjkGridRepresentation'
      → 'resqml22.IjkGridRepresentation'
    """
    if not ct:
        return None
    # Parse out version and type from ContentType
    version = ""
    obj_type = ""
    for part in ct.split(";"):
        part = part.strip()
        if part.startswith("version="):
            version = part[len("version="):]
        elif part.startswith("type="):
            obj_type = part[len("type="):]
    if not obj_type:
        return None
    if "2.2" in version:
        return f"resqml22.{obj_type}"
    # Default to 2.0.1
    return f"resqml20.{obj_type}" if obj_type.startswith("obj_") else f"resqml20.obj_{obj_type}"


async def _property_geometry(
    access_token: str, ds: str, typ: str, uuid: str,
) -> dict[str, Any]:
    """Fetch property values and the supporting representation geometry.

    Returns the supporting rep's geometry dict with added:
      - propertyValues: list[float|int]
      - propertyMin / propertyMax: value range
      - propertyName: display name
      - colorMap: optional {name, min, max} from GraphicalInformationSet
    """
    from . import osdu

    enc = urllib.parse.quote(ds, safe="")
    hdr = osdu.headers(access_token)

    async with osdu._http(timeout=120) as client:
        # 1. Fetch the property object
        obj_url = osdu._rddms_url(f"/dataspaces/{enc}/resources/{typ}/{uuid}")
        r1 = await client.get(obj_url, headers=hdr, params={"$format": "json"})
        r1.raise_for_status()
        obj = osdu._normalize_obj(r1.json(), uuid)

        title = (obj.get("Citation") or {}).get("Title") or uuid

        # 2. Extract SupportingRepresentation reference
        sup_ref = obj.get("SupportingRepresentation") or {}
        sup_uuid = sup_ref.get("UUID") or sup_ref.get("Uuid") or sup_ref.get("uuid") or ""
        sup_ct = sup_ref.get("ContentType") or sup_ref.get("contentType") or ""
        sup_type = _extract_rep_type_from_content_type(sup_ct)

        if not sup_uuid or not sup_type:
            raise ValueError(
                f"Property {uuid} has no resolvable SupportingRepresentation "
                f"(UUID={sup_uuid!r}, ContentType={sup_ct!r})"
            )

        # 3. Read property values array
        r_al = await client.get(f"{obj_url}/arrays", headers=hdr)
        prop_values: list[float] = []
        if r_al.status_code not in (404, 405, 412):
            r_al.raise_for_status()
            arr_list = r_al.json() or []
            # Property typically has a single "values" array
            for a in arr_list:
                uid = a.get("uid") or {}
                p = uid.get("pathInResource", "")
                if "values" in p.lower() or not prop_values:
                    arr_enc = urllib.parse.quote(p, safe="")
                    r_arr = await client.get(f"{obj_url}/arrays/{arr_enc}", headers=hdr)
                    if r_arr.status_code == 200:
                        prop_values = _extract_flat_array(r_arr.json() or {})
                    if prop_values:
                        break

        # 4. Look for GraphicalInformationSet in the dataspace
        color_map_info = await _find_graphical_info(client, hdr, enc, uuid)

    # 5. Fetch the supporting representation geometry (recursive call)
    geo = await fetch_geometry_3d(access_token, ds, sup_type, sup_uuid)

    # 6. Annotate with property values
    geo["propertyValues"] = prop_values
    if prop_values:
        finite_vals = [v for v in prop_values if v is not None and isinstance(v, (int, float))]
        geo["propertyMin"] = min(finite_vals) if finite_vals else 0
        geo["propertyMax"] = max(finite_vals) if finite_vals else 1
    else:
        geo["propertyMin"] = 0
        geo["propertyMax"] = 1
    geo["propertyName"] = title
    if color_map_info:
        geo["colorMap"] = color_map_info

    return geo


async def _find_graphical_info(client, hdr: dict, enc_ds: str, prop_uuid: str) -> dict | None:
    """Search for a GraphicalInformationSet referencing this property.

    Returns {name, minValue, maxValue, useLog, useReverse} or None.
    """
    from . import osdu

    # Try to list GraphicalInformationSet objects in the dataspace
    for gis_type in ("resqml22.GraphicalInformationSet", "eml23.GraphicalInformationSet"):
        list_url = osdu._rddms_url(f"/dataspaces/{enc_ds}/resources/{gis_type}")
        try:
            r = await client.get(list_url, headers=hdr, params={"$format": "json"})
            if r.status_code != 200:
                continue
            items = r.json()
            if not isinstance(items, list):
                items = [items] if isinstance(items, dict) else []

            for item in items:
                gis_uuid = item.get("Uuid") or item.get("UUID") or item.get("uuid") or ""
                if not gis_uuid:
                    continue
                # Fetch the full object
                gis_url = osdu._rddms_url(
                    f"/dataspaces/{enc_ds}/resources/{gis_type}/{gis_uuid}")
                r2 = await client.get(gis_url, headers=hdr, params={"$format": "json"})
                if r2.status_code != 200:
                    continue
                gis_obj = osdu._normalize_obj(r2.json(), gis_uuid)
                # Look through GraphicalInformation entries for our property
                gi_list = gis_obj.get("GraphicalInformation") or []
                if isinstance(gi_list, dict):
                    gi_list = [gi_list]
                for gi in gi_list:
                    target = gi.get("TargetObject") or {}
                    target_uuid = target.get("UUID") or target.get("Uuid") or ""
                    if target_uuid.lower() != prop_uuid.lower():
                        continue
                    # Found a match – extract color info
                    ci = gi.get("ColorInformation") or {}
                    return {
                        "useLog": ci.get("UseLogarithmicMapping", False),
                        "useReverse": ci.get("UseReverseMapping", False),
                        "minIndex": ci.get("MinIndex"),
                        "maxIndex": ci.get("MaxIndex"),
                        "colorMapName": (ci.get("ColorMap") or {}).get("Title")
                            or (ci.get("ColorMap") or {}).get("Citation", {}).get("Title"),
                        "defaultColor": _extract_color(gi.get("DefaultColor")),
                        "opacity": gi.get("Opacity"),
                    }
        except Exception as e:
            log.debug("_find_graphical_info: %s check failed: %s", gis_type, e)
            continue
    return None


def _extract_color(color_obj) -> str | None:
    """Convert an HsvColor/RgbColor dict to a CSS hex string."""
    if not color_obj or not isinstance(color_obj, dict):
        return None
    # RGB
    if "Red" in color_obj:
        r = int(float(color_obj.get("Red", 0)) * 255)
        g = int(float(color_obj.get("Green", 0)) * 255)
        b = int(float(color_obj.get("Blue", 0)) * 255)
        return f"#{r:02x}{g:02x}{b:02x}"
    # HSV (convert to hex)
    if "Hue" in color_obj:
        import colorsys
        h = float(color_obj.get("Hue", 0)) / 360
        s = float(color_obj.get("Saturation", 1))
        v = float(color_obj.get("Value", 1))
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
    return None


async def fetch_geometry_3d(
    access_token: str,
    ds: str,
    typ: str,
    uuid: str,
) -> dict[str, Any]:
    """
    Generic 3-D geometry fetcher for the Three.js viewer.

    Cascades:  local PG → remote RDDMS PG → RDDMS REST API.

    Supported types:
      - Grid2dRepresentation          → vertices + triangle indices
      - TriangulatedSetRepresentation → vertices + triangle indices
      - PointSetRepresentation        → XYZ points
      - WellboreTrajectoryRepresentation → XYZ polyline
      - WellboreMarkerFrameRepresentation → XYZ markers with MD/labels
      - IjkGridRepresentation         → pillar point cloud
      - ContinuousProperty / DiscreteProperty / CategoricalProperty
        → supporting rep geometry coloured by property values

    Returns a dict with ``kind`` and geometry arrays for Three.js.
    """
    tl = typ.lower()

    # ── Property types: resolve geometry from SupportingRepresentation ─
    if _is_property_type(tl):
        return await _property_geometry(access_token, ds, typ, uuid)

    # ── 1. Local PG (co-located, fastest) ─────────────────────────────
    try:
        from .pg_backend import get_pool
        pool = await get_pool()
        if pool:
            result = await _pg_geometry3d(pool, ds, typ, uuid)
            if result:
                log.info("fetch_geometry_3d: served from local PG ds=%s uuid=%s", ds, uuid)
                return result
    except Exception as e:
        log.warning("fetch_geometry_3d: local PG failed: %s", e)

    # ── 2. Remote RDDMS PG (direct SQL to cloud DB) ───────────────────
    try:
        from .pg_backend import get_rddms_pool
        rddms_pool = await get_rddms_pool()
        if rddms_pool:
            result = await _pg_geometry3d(rddms_pool, ds, typ, uuid)
            if result:
                log.info("fetch_geometry_3d: served from remote PG ds=%s uuid=%s", ds, uuid)
                return result
    except Exception as e:
        log.warning("fetch_geometry_3d: remote PG failed, falling back to REST: %s", e)

    # ── 3. REST fallback (any RDDMS instance) ─────────────────────────
    return await _rest_geometry3d(access_token, ds, typ, uuid)
