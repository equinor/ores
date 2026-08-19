"""
app/pg_backend.py - PostgreSQL backend for RDDMS data access.

Pool management and direct-PG resolvers for the OpenETPServer/RDDMS
PostgreSQL database.  Extracted from graphql_router.py so that
keys_router, resqml_viz, and other modules can import cleanly without
reaching into graphql_router's private namespace.

Public API:
  Pool management:
    get_pool()                → asyncpg.Pool | None  (local PG)
    get_rddms_pool()          → asyncpg.Pool | None  (remote RDDMS PG)
    close_pool()              → close both pools
    notify_instance_changed() → tear down & rebuild for new instance

  Resolvers (all async, pool as first arg):
    pg_schema_for_dataspace(pool, ds)         → schema name | None
    pg_list_dataspaces(pool)                  → [{path, uri}]
    pg_list_types(pool, ds)                   → [{name, count}]
    pg_list_resources(pool, ds, type, limit)  → [{uuid, title, type_name, obj_id}]
    pg_list_relations(pool, ds, type, uuid, dir) → [{uuid, name, type_name, direction, content_type}]
    pg_list_arrays(pool, ds, uuid)            → [{ary_id, path, type, ...}]
    pg_read_array(pool, ds, uuid, path)       → [float]

  Constants:
    ARY_TYPE_FMT              → {int: struct_fmt_char}
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import struct
from typing import Any, Dict, List, Optional

log = logging.getLogger("rddms-admin.graphql")


# ──────────────────────────────────────────────────────────────────────────────
# Pool management
# ──────────────────────────────────────────────────────────────────────────────

# PG conn string is per-instance: set via INSTANCE_<NAME>_GRAPHQL_PG_CONN_STRING
# in k8s/secret.yaml, or globally via GRAPHQL_PG_CONN_STRING (legacy fallback).
# When the active instance changes, notify_instance_changed() tears down and
# rebuilds the pool with the new connection string (or None → REST fallback).
_PG_CONN_STRING = os.getenv("GRAPHQL_PG_CONN_STRING") or os.getenv("POSTGRESQL_CONN_STRING", "")
_PG_CONN_STRING_GLOBAL = _PG_CONN_STRING  # remember the global fallback
_pool = None  # asyncpg.Pool or None

# Remote RDDMS PostgreSQL (direct access to the cloud-hosted RDDMS database).
# Not yet available on ADME, but prepared for when it becomes accessible.
_RDDMS_PG_CONN_STRING = os.getenv("RDDMS_PG_CONN_STRING", "")
_rddms_pool = None  # asyncpg.Pool or None – remote RDDMS PG

# Async lock to prevent double pool creation under concurrent requests.
_pool_lock = asyncio.Lock()


def _parse_dsn(conn_str: str) -> str:
    """Normalise a connection string to a DSN URI if needed."""
    if "=" in conn_str and "://" not in conn_str:
        parts = dict(p.split("=", 1) for p in conn_str.split() if "=" in p)
        return "postgresql://{user}:{password}@{host}:{port}/{dbname}".format(
            user=parts.get("user", "postgres"),
            password=parts.get("password", ""),
            host=parts.get("host", "localhost"),
            port=parts.get("port", "5432"),
            dbname=parts.get("dbname", "postkv"),
        )
    return conn_str


async def get_pool():
    """Return asyncpg pool for the *local* PG (or None if not configured)."""
    global _pool
    if _pool is not None:
        return _pool
    if not _PG_CONN_STRING:
        return None
    async with _pool_lock:
        # Double-check after acquiring lock
        if _pool is not None:
            return _pool
        try:
            import asyncpg
            dsn = _parse_dsn(_PG_CONN_STRING)
            _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10, command_timeout=60)
            log.info("GraphQL PG pool created (local)")
        except Exception as e:
            log.warning("PG pool failed (will use REST fallback): %s", e)
            _pool = None
    return _pool


async def get_rddms_pool():
    """Return asyncpg pool for the *remote* RDDMS PG (or None).

    This connects directly to the PostgreSQL database backing a
    cloud-hosted RDDMS instance, bypassing the REST API.  Set the
    ``RDDMS_PG_CONN_STRING`` env var to enable.
    """
    global _rddms_pool
    if _rddms_pool is not None:
        return _rddms_pool
    if not _RDDMS_PG_CONN_STRING:
        return None
    async with _pool_lock:
        # Double-check after acquiring lock
        if _rddms_pool is not None:
            return _rddms_pool
        try:
            import asyncpg
            dsn = _parse_dsn(_RDDMS_PG_CONN_STRING)
            _rddms_pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5, command_timeout=120)
            log.info("Remote RDDMS PG pool created")
        except Exception as e:
            log.warning("Remote RDDMS PG pool failed (will use REST fallback): %s", e)
            _rddms_pool = None
    return _rddms_pool


async def close_pool():
    """Close both PG pools (called on app shutdown)."""
    global _pool, _rddms_pool
    if _pool:
        await _pool.close()
        _pool = None
    if _rddms_pool:
        await _rddms_pool.close()
        _rddms_pool = None


def notify_instance_changed(pg_conn_string: str = "") -> None:
    """Called by instances._apply_instance() when the active OSDU instance changes.

    Tears down the existing PG pool so it will be lazily re-created with the
    new connection string on the next query.

    Precedence: the global ``GRAPHQL_PG_CONN_STRING`` env var (local Docker PG)
    always wins when set - per-instance ``pg_conn_string`` is only used when the
    global is absent (i.e. on Radix where there is no local Docker PG).
    If neither is set, the pool stays None and resolvers use REST.
    """
    global _PG_CONN_STRING, _pool
    old = _PG_CONN_STRING
    _clear_schema_cache()
    # Local dev: GRAPHQL_PG_CONN_STRING is set → always use Docker PG.
    # Radix:     GRAPHQL_PG_CONN_STRING absent → use per-instance PG.
    _PG_CONN_STRING = _PG_CONN_STRING_GLOBAL or pg_conn_string

    if _pool is not None:
        old_pool = _pool
        _pool = None
        # Schedule async close so outstanding queries can finish gracefully.
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_async_close_pool(old_pool))
        except RuntimeError:
            pass  # no running loop (startup) – pool will just be GC'd

    if old != pg_conn_string:
        label = "PG" if pg_conn_string else "REST-only"
        log.info("GraphQL backend switched → %s", label)


def get_connection_info() -> dict:
    """Return sanitised PG connection info for the /api/graphql/info endpoint."""
    import re as _re_local
    def _mask(s: str) -> str:
        s = _re_local.sub(r"password=\S+", "password=***", s)
        return _re_local.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", s)
    return {
        "pg_conn_string": _mask(_PG_CONN_STRING) if _PG_CONN_STRING else None,
        "rddms_pg_conn_string": _mask(_RDDMS_PG_CONN_STRING) if _RDDMS_PG_CONN_STRING else None,
        "pg_configured": bool(_PG_CONN_STRING),
        "rddms_pg_configured": bool(_RDDMS_PG_CONN_STRING),
    }


async def _async_close_pool(pool_to_close) -> None:
    """Close an old PG pool asynchronously (fire-and-forget)."""
    try:
        await pool_to_close.close()
        log.debug("Old PG pool closed")
    except Exception as e:
        log.debug("Old PG pool close error (ignored): %s", e)


# ──────────────────────────────────────────────────────────────────────────────
# PostgreSQL-native resolvers (direct path - when PG is available)
# ──────────────────────────────────────────────────────────────────────────────

# Array element type → struct format
ARY_TYPE_FMT = {0: "i", 1: "d", 2: "f", 3: "q", 4: "i", 5: "h"}  # int32, float64, float32, int64, int32, int16

# Valid PG schema name pattern (defence-in-depth against SQL injection via
# f-string schema interpolation - the value comes from admin.spaces, not user
# input, but we validate anyway).
_SAFE_SCHEMA_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# In-memory schema cache: dataspace path → schema name (or None).
# Cleared on instance change.  Avoids repeated admin.spaces lookups.
_schema_cache: Dict[str, Optional[str]] = {}


def _clear_schema_cache() -> None:
    """Clear the schema cache (called on instance change)."""
    _schema_cache.clear()


async def pg_schema_for_dataspace(pool, dataspace: str) -> Optional[str]:
    """Resolve a dataspace path to the PostgreSQL schema name (cached)."""
    if dataspace in _schema_cache:
        return _schema_cache[dataspace]
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT dbfile FROM admin.spaces WHERE path=$1 OR uid=$1", dataspace
        )
        if not row:
            _schema_cache[dataspace] = None
            return None
        schema = row["dbfile"]
        if not _SAFE_SCHEMA_RE.match(schema):
            log.error("Unsafe PG schema name %r for dataspace %r - refusing to query", schema, dataspace)
            _schema_cache[dataspace] = None
            return None
        _schema_cache[dataspace] = schema
        return schema


async def pg_list_dataspaces(pool) -> List[Dict[str, Any]]:
    """List all dataspaces from admin.spaces."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT uid, path FROM admin.spaces ORDER BY path")
        return [{"path": r["path"], "uri": f"eml:///dataspace('{r['path']}')"} for r in rows]


async def pg_list_types(pool, dataspace: str) -> List[Dict[str, Any]]:
    """List resource types with counts in a dataspace."""
    schema = await pg_schema_for_dataspace(pool, dataspace)
    if not schema:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT t.xml as name, u.ml || '.' || t.xml as full_name, count(r.obj_id) as cnt
            FROM {schema}.typ t
            JOIN {schema}.uri u ON t.uri_id = u.id
            LEFT JOIN {schema}.res r ON r.typ_id = t.id
            GROUP BY t.xml, u.ml
            ORDER BY cnt DESC
        """)
        return [{"name": f"{r['full_name']}", "count": int(r["cnt"])} for r in rows]


async def pg_list_resources(pool, dataspace: str, type_name: str, limit: int = 100) -> List[Dict[str, Any]]:
    """List resources of a given type in a dataspace."""
    schema = await pg_schema_for_dataspace(pool, dataspace)
    if not schema:
        return []
    # type_name is like "resqml20.obj_Grid2dRepresentation" → split into ml and xml
    parts = type_name.split(".", 1)
    async with pool.acquire() as conn:
        if len(parts) == 2:
            rows = await conn.fetch(f"""
                SELECT r.obj_id, r.guid, r.name, t.xml as typ_xml, u.ml
                FROM {schema}.res r
                JOIN {schema}.typ t ON r.typ_id = t.id
                JOIN {schema}.uri u ON t.uri_id = u.id
                WHERE u.ml = $1 AND t.xml = $2
                ORDER BY r.obj_id
                LIMIT $3
            """, parts[0], parts[1], limit)
        else:
            rows = await conn.fetch(f"""
                SELECT r.obj_id, r.guid, r.name, t.xml as typ_xml, u.ml
                FROM {schema}.res r
                JOIN {schema}.typ t ON r.typ_id = t.id
                JOIN {schema}.uri u ON t.uri_id = u.id
                WHERE t.xml ILIKE '%' || $1 || '%'
                ORDER BY r.obj_id
                LIMIT $2
            """, type_name, limit)
        return [
            {"uuid": str(r["guid"]), "title": r["name"],
             "type_name": f"{r['ml']}.{r['typ_xml']}", "obj_id": r["obj_id"]}
            for r in rows
        ]


async def pg_list_relations(pool, dataspace: str, type_name: str, uuid: str, direction: str = "both") -> List[Dict[str, Any]]:
    """Get relationships from the rel table. direction: targets|sources|both."""
    schema = await pg_schema_for_dataspace(pool, dataspace)
    if not schema:
        return []
    async with pool.acquire() as conn:
        # Find obj_id for the given uuid
        src = await conn.fetchrow(f"SELECT obj_id FROM {schema}.res WHERE guid=$1", uuid)
        if not src:
            return []
        obj_id = src["obj_id"]
        results = []

        if direction in ("both", "targets"):
            rows = await conn.fetch(f"""
                SELECT r2.guid, r2.name, t.xml as typ_xml, u.ml, xpa.th as rel_path
                FROM {schema}.rel rel
                JOIN {schema}.res r2 ON rel.dst_id = r2.obj_id
                JOIN {schema}.typ t ON r2.typ_id = t.id
                JOIN {schema}.uri u ON t.uri_id = u.id
                LEFT JOIN {schema}.xpa xpa ON rel.xpa_id = xpa.id
                WHERE rel.obj_id = $1
            """, obj_id)
            for r in rows:
                results.append({
                    "uuid": str(r["guid"]), "name": r["name"],
                    "type_name": f"{r['ml']}.{r['typ_xml']}",
                    "direction": "target",
                    "content_type": r["rel_path"] or "",
                })

        if direction in ("both", "sources"):
            rows = await conn.fetch(f"""
                SELECT r2.guid, r2.name, t.xml as typ_xml, u.ml, xpa.th as rel_path
                FROM {schema}.rel rel
                JOIN {schema}.res r2 ON rel.obj_id = r2.obj_id
                JOIN {schema}.typ t ON r2.typ_id = t.id
                JOIN {schema}.uri u ON t.uri_id = u.id
                LEFT JOIN {schema}.xpa xpa ON rel.xpa_id = xpa.id
                WHERE rel.dst_id = $1
            """, obj_id)
            for r in rows:
                results.append({
                    "uuid": str(r["guid"]), "name": r["name"],
                    "type_name": f"{r['ml']}.{r['typ_xml']}",
                    "direction": "source",
                    "content_type": r["rel_path"] or "",
                })

        return results


async def pg_list_arrays(pool, dataspace: str, uuid: str) -> List[Dict[str, Any]]:
    """List arrays for an object from the ary table."""
    schema = await pg_schema_for_dataspace(pool, dataspace)
    if not schema:
        return []
    async with pool.acquire() as conn:
        src = await conn.fetchrow(f"SELECT obj_id FROM {schema}.res WHERE guid=$1", uuid)
        if not src:
            return []
        rows = await conn.fetch(f"""
            SELECT id, path, type, rank1, dim1, dim2, dim3, dim4, usize
            FROM {schema}.ary WHERE obj_id=$1
        """, src["obj_id"])
        results = []
        for r in rows:
            dims = [int(r[f"dim{i}"]) for i in range(1, 5) if r[f"dim{i}"] is not None and r[f"dim{i}"] > 0]
            total = 1
            for d in dims:
                total *= d
            results.append({
                "ary_id": int(r["id"]),
                "path": r["path"] or "",
                "type": int(r["type"]) if r["type"] is not None else 1,
                "rank": int(r["rank1"]) if r["rank1"] is not None else 0,
                "dimensions": dims,
                "total_elements": total,
                "usize": int(r["usize"]) if r["usize"] is not None else 8,
            })
        return results


async def pg_read_array(pool, dataspace: str, uuid: str, path: str) -> List[float]:
    """Read array binary data from bin table and decode to floats."""
    schema = await pg_schema_for_dataspace(pool, dataspace)
    if not schema:
        return []
    async with pool.acquire() as conn:
        src = await conn.fetchrow(f"SELECT obj_id FROM {schema}.res WHERE guid=$1", uuid)
        if not src:
            return []
        ary = await conn.fetchrow(f"""
            SELECT id, type, dim1, dim2, dim3, dim4, usize, value
            FROM {schema}.ary WHERE obj_id=$1 AND path=$2
        """, src["obj_id"], path)
        if not ary:
            return []
        # Read binary: inline ary.value first, then chunked bin table
        if ary["value"]:
            raw = bytes(ary["value"])
        else:
            bins = await conn.fetch(f"""
                SELECT value FROM {schema}.bin WHERE ary_id=$1 ORDER BY idx
            """, ary["id"])
            raw = b"".join(b["value"] for b in bins)

        # Determine element format
        fmt_char = ARY_TYPE_FMT.get(ary["type"] if ary["type"] is not None else 1, "d")
        elem_size = struct.calcsize(fmt_char)
        n_elements = len(raw) // elem_size if elem_size else 0
        if n_elements == 0:
            return []
        values = list(struct.unpack_from(f"<{n_elements}{fmt_char}", raw))
        return [float(v) for v in values]


# ──────────────────────────────────────────────────────────────────────────────
# Batch queries (optimised for deep_search - eliminate N+1)
# ──────────────────────────────────────────────────────────────────────────────


async def pg_batch_property_sources(pool, dataspace: str, obj_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
    """For a batch of obj_ids, find all property sources that reference them.

    Returns: {target_obj_id: [{p_obj_id, p_guid, p_name, p_typ_xml, p_ml}, ...]}
    """
    schema = await pg_schema_for_dataspace(pool, dataspace)
    if not schema or not obj_ids:
        return {}
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT rel.dst_id as target_id,
                   r2.obj_id as p_obj_id, r2.guid as p_guid, r2.name as p_name,
                   t2.xml as p_typ_xml, u2.ml as p_ml
            FROM {schema}.rel rel
            JOIN {schema}.res r2 ON rel.obj_id = r2.obj_id
            JOIN {schema}.typ t2 ON r2.typ_id = t2.id
            JOIN {schema}.uri u2 ON t2.uri_id = u2.id
            WHERE rel.dst_id = ANY($1::int[])
            AND t2.xml IN ('obj_ContinuousProperty', 'obj_DiscreteProperty',
                           'obj_CategoricalProperty', 'obj_PointsProperty')
        """, obj_ids)
        result: Dict[int, List[Dict[str, Any]]] = {}
        for r in rows:
            tid = r["target_id"]
            result.setdefault(tid, []).append({
                "p_obj_id": r["p_obj_id"],
                "p_guid": str(r["p_guid"]),
                "p_name": r["p_name"],
                "p_typ_xml": r["p_typ_xml"],
                "p_ml": r["p_ml"],
            })
        return result


async def pg_batch_relations(pool, dataspace: str, obj_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
    """Batch fetch relations (targets+sources) for multiple obj_ids.

    Returns: {obj_id: [{uuid, name, type_name, direction, content_type}, ...]}
    """
    schema = await pg_schema_for_dataspace(pool, dataspace)
    if not schema or not obj_ids:
        return {}
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT rel.obj_id as src_id, r2.guid, r2.name, t2.xml as typ_xml, u2.ml,
                   'target' as direction
            FROM {schema}.rel rel
            JOIN {schema}.res r2 ON rel.dst_id = r2.obj_id
            JOIN {schema}.typ t2 ON r2.typ_id = t2.id
            JOIN {schema}.uri u2 ON t2.uri_id = u2.id
            WHERE rel.obj_id = ANY($1::int[])
            UNION ALL
            SELECT rel.dst_id as src_id, r2.guid, r2.name, t2.xml as typ_xml, u2.ml,
                   'source' as direction
            FROM {schema}.rel rel
            JOIN {schema}.res r2 ON rel.obj_id = r2.obj_id
            JOIN {schema}.typ t2 ON r2.typ_id = t2.id
            JOIN {schema}.uri u2 ON t2.uri_id = u2.id
            WHERE rel.dst_id = ANY($1::int[])
        """, obj_ids)
        result: Dict[int, List[Dict[str, Any]]] = {}
        for r in rows:
            sid = r["src_id"]
            result.setdefault(sid, []).append({
                "uuid": str(r["guid"]),
                "name": r["name"],
                "type_name": f"{r['ml']}.{r['typ_xml']}",
                "direction": r["direction"],
                "content_type": f"{r['ml']}.{r['typ_xml']}",
            })
        return result


async def pg_batch_arrays_for_objects(pool, dataspace: str, obj_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
    """Batch fetch array metadata for multiple obj_ids.

    Returns: {obj_id: [{ary_id, path, type, dimensions, total_elements}, ...]}
    """
    schema = await pg_schema_for_dataspace(pool, dataspace)
    if not schema or not obj_ids:
        return {}
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT obj_id, id, path, type, rank1, dim1, dim2, dim3, dim4, usize
            FROM {schema}.ary WHERE obj_id = ANY($1::int[])
        """, obj_ids)
        result: Dict[int, List[Dict[str, Any]]] = {}
        for r in rows:
            dims = [int(r[f"dim{i}"]) for i in range(1, 5) if r[f"dim{i}"] is not None and r[f"dim{i}"] > 0]
            total = 1
            for d in dims:
                total *= d
            result.setdefault(r["obj_id"], []).append({
                "ary_id": int(r["id"]),
                "path": r["path"] or "",
                "type": int(r["type"]) if r["type"] is not None else 1,
                "dimensions": dims,
                "total_elements": total,
            })
        return result


async def pg_read_array_by_id(pool, dataspace: str, ary_id: int, ary_type: int = 1) -> List[float]:
    """Read array binary data by ary_id directly (avoids extra obj_id lookup)."""
    schema = await pg_schema_for_dataspace(pool, dataspace)
    if not schema:
        return []
    async with pool.acquire() as conn:
        # Check inline value first
        row = await conn.fetchrow(f"""
            SELECT value FROM {schema}.ary WHERE id=$1
        """, ary_id)
        if row and row["value"]:
            raw = bytes(row["value"])
        else:
            bins = await conn.fetch(f"""
                SELECT value FROM {schema}.bin WHERE ary_id=$1 ORDER BY idx
            """, ary_id)
            if not bins:
                return []
            raw = b"".join(b["value"] for b in bins)
        fmt_char = ARY_TYPE_FMT.get(ary_type, "d")
        elem_size = struct.calcsize(fmt_char)
        n_elements = len(raw) // elem_size if elem_size else 0
        if n_elements == 0:
            return []
        values = list(struct.unpack_from(f"<{n_elements}{fmt_char}", raw))
        return [float(v) for v in values]


# ──────────────────────────────────────────────────────────────────────────────
# FIRP relationship queries (Feature ↔ Interpretation ↔ Representation ↔ Property)
# ──────────────────────────────────────────────────────────────────────────────

async def pg_firp_relationships(
    pool, dataspace: str, guid: str
) -> Dict[str, List[Dict[str, Any]]]:
    """Query forward and reverse RESQML relationships for a given object UUID.

    Returns {"forward": [...], "reverse": [...]} where each item is:
        {"guid": str, "name": str, "type": str}
    ``type`` is the EML short type like 'obj_HorizonInterpretation'.
    """
    schema = await pg_schema_for_dataspace(pool, dataspace)
    if not schema:
        return {"forward": [], "reverse": []}

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT obj_id FROM {schema}.res WHERE guid=$1", guid
        )
        if not row:
            return {"forward": [], "reverse": []}
        obj_id = row["obj_id"]

        fwd_rows = await conn.fetch(f"""
            SELECT r2.guid, r2.name, t2.xml AS typ
            FROM {schema}.rel rl
            JOIN {schema}.res r2 ON r2.obj_id = rl.dst_id
            JOIN {schema}.typ t2 ON r2.typ_id = t2.id
            WHERE rl.obj_id = $1
        """, obj_id)

        rev_rows = await conn.fetch(f"""
            SELECT r2.guid, r2.name, t2.xml AS typ
            FROM {schema}.rel rl
            JOIN {schema}.res r2 ON r2.obj_id = rl.obj_id
            JOIN {schema}.typ t2 ON r2.typ_id = t2.id
            WHERE rl.dst_id = $1
        """, obj_id)

    forward = [
        {"guid": str(r["guid"]), "name": r["name"] or "", "type": r["typ"] or ""}
        for r in fwd_rows
    ]
    reverse = [
        {"guid": str(r["guid"]), "name": r["name"] or "", "type": r["typ"] or ""}
        for r in rev_rows
    ]
    return {"forward": forward, "reverse": reverse}
