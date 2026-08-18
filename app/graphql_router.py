"""
GraphQL deep-search on OSDU Reservoir DDMS (RESQML data model).

Hybrid architecture: uses direct PostgreSQL when co-located with OpenETPServer,
**falls back to the Reservoir DDMS REST API** when PG is unavailable.

Schema wiring, basic resolvers, and GraphQL endpoint setup.
Search implementations (deep_search, federated_search) live in graphql_search.py.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import strawberry
from strawberry.fastapi import GraphQLRouter as _StrawberryRouter
from strawberry.types import Info
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import osdu
from .common import access_token as _access_token
from .pg_backend import (
    get_pool as _get_pool,
    get_rddms_pool as _get_rddms_pool,
    close_pool,
    notify_instance_changed,
    ARY_TYPE_FMT as _ARY_TYPE_FMT,
    pg_schema_for_dataspace as _pg_schema_for_dataspace,
    pg_list_dataspaces as _pg_list_dataspaces,
    pg_list_types as _pg_list_types,
    pg_list_resources as _pg_list_resources,
    pg_list_relations as _pg_list_relations,
    pg_list_arrays as _pg_list_arrays,
    pg_read_array as _pg_read_array,
)
from .graphql_search import (
    # Types (re-exported for backward compatibility)
    ComparisonOperator, ArrayStatistics, CellMatch, ArrayInfo, PropertyInfo,
    RelationInfo, ResqmlObject, DataspaceInfo, TypeSummary,
    DeepSearchResult, FederatedHit, FederatedSearchResult,
    ArrayFilter, PropertyFilter,
    # Native RDDMS GQL types (M27+)
    GraphEdge, GraphNode, NativeGraphResult, NativeObjectContent,
    NativeArrayMeta, NativeResourceWithArrays,
    # Type registry
    RESQML_TYPE_CATEGORIES, ALL_COMMON_RESQML_TYPES, resolve_type_names,
    # REST wrappers (only those still used directly in this file)
    _parse_eml_entry, _rest_list_types, _rest_list_resources,
    _rest_read_array,
    # GQL-first wrappers (try native /graphql → REST fallback)
    _gql_or_rest_list_dataspaces, _gql_or_rest_list_targets,
    _gql_or_rest_list_sources, _gql_or_rest_list_arrays,
    _gql_or_rest_graph_search, _gql_or_rest_list_resources,
    _build_etp_uri,
    # Analysis helpers (used by object_arrays)
    _compute_statistics,
    # Search implementations (called from Query stubs)
    deep_search_impl, federated_search_impl,
    # Native RDDMS GQL implementations (M27+)
    native_graph_search_impl, native_object_content_impl, native_array_metadata_impl,
    # Validation helpers
    validate_object_relations_direction, _VALID_DIRECTIONS,
)

log = logging.getLogger("rddms-admin.graphql")


def _get_token_from_info(info: Info) -> str:
    """Extract access token from Strawberry context."""
    request: Request = info.context["request"]
    return _access_token(request)


# ──────────────────────────────────────────────────────────────────────────────
# Query root - resolvers follow: PG → native GQL → REST fallback
# (except type listing and array values which have no GQL equivalent)
# ──────────────────────────────────────────────────────────────────────────────


@strawberry.type
class Query:

    @strawberry.field(description="Backend connectivity status")
    async def status(self, info: Info) -> str:
        pool = await _get_pool()
        if pool:
            try:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow("SELECT version() as v")
                    return f"PostgreSQL direct: {row['v']}"
            except Exception as e:
                return f"PostgreSQL error: {e}"
        # GQL/REST mode
        try:
            token = _get_token_from_info(info)
            ds = await _gql_or_rest_list_dataspaces(token)
            return f"RDDMS API – {len(ds)} dataspaces available"
        except Exception as e:
            return f"RDDMS API error: {e}"

    @strawberry.field(description="List dataspaces")
    async def dataspaces(self, info: Info) -> List[DataspaceInfo]:
        pool = await _get_pool()
        if pool:
            items = await _pg_list_dataspaces(pool)
            return [DataspaceInfo(path=i["path"], uri=i.get("uri", "")) for i in items]
        token = _get_token_from_info(info)
        items = await _gql_or_rest_list_dataspaces(token)
        return [DataspaceInfo(path=i["path"], uri=i.get("uri", "")) for i in items]

    @strawberry.field(
        description=(
            "List available RESQML type categories for use with deep_search(category:). "
            "Each category groups related RESQML types (e.g. 'grid', 'well', 'structural')."
        )
    )
    async def resqml_categories(self) -> List[TypeSummary]:
        return [
            TypeSummary(name=cat, count=len(types))
            for cat, types in RESQML_TYPE_CATEGORIES.items()
        ]

    @strawberry.field(description="List resource types in a dataspace with counts")
    async def resource_types(self, info: Info, dataspace: str) -> List[TypeSummary]:
        pool = await _get_pool()
        if pool:
            types = await _pg_list_types(pool, dataspace)
            if types:
                return [TypeSummary(name=t["name"], count=t["count"]) for t in types]
            # Dataspace not in PG → fall through to REST
        token = _get_token_from_info(info)
        types = await _rest_list_types(token, dataspace)
        return [TypeSummary(name=t["name"], count=t["count"]) for t in types]

    @strawberry.field(description="Browse RESQML objects by type in a dataspace")
    async def resqml_objects(
        self,
        info: Info,
        dataspace: str,
        type_name: str,
        title_contains: Optional[str] = None,
        limit: int = 50,
    ) -> List[ResqmlObject]:
        pool = await _get_pool()
        resources = []
        if pool:
            resources = await _pg_list_resources(pool, dataspace, type_name, limit)
        if not resources:
            # PG returned nothing (or no pool) → try native GQL (etp-client) → REST
            token = _get_token_from_info(info)
            resources = await _gql_or_rest_list_resources(token, dataspace, type_name, limit)
        results = []
        for r in resources:
            title = r["title"]
            if title_contains and title_contains.lower() not in title.lower():
                continue
            results.append(ResqmlObject(
                uuid=r["uuid"], title=title, type_name=r["type_name"],
            ))
        return results

    @strawberry.field(
        description=(
            "Get object graph: targets and sources (relationships) for an object. "
            "This covers all RESQML relationships: SupportingRepresentation, "
            "RepresentedInterpretation, Geologic features, CRS references, etc."
        )
    )
    async def object_relations(
        self,
        info: Info,
        dataspace: str,
        type_name: str,
        uuid: str,
        direction: str = "both",
    ) -> List[RelationInfo]:
        """
        Traverse the RESQML object graph.

        Every DataObjectReference in RESQML creates an edge:
        - targets: objects this object points to
          (e.g. Grid2D → LocalDepth3dCrs, Property → SupportingRepresentation)
        - sources: objects that point to this object
          (e.g. which Properties reference this Grid2D)

        This is how you find ancestors, topology, interpretation hierarchies.
        """
        # Validate direction
        dir_err = validate_object_relations_direction(direction)
        if dir_err:
            raise ValueError(dir_err)

        pool = await _get_pool()
        if pool:
            rels = await _pg_list_relations(pool, dataspace, type_name, uuid, direction)
            if rels:
                return [
                    RelationInfo(
                        uuid=r["uuid"], name=r["name"], type_name=r["type_name"],
                        direction=r["direction"], content_type=r["content_type"],
                    )
                    for r in rels
                ]
            # PG returned nothing → fall through to REST

        # GQL-first fallback (tries native /graphql, then REST)
        token = _get_token_from_info(info)
        results = []

        if direction in ("both", "targets"):
            try:
                targets = await _gql_or_rest_list_targets(token, dataspace, type_name, uuid)
                for t in targets:
                    parsed = _parse_eml_entry(t)
                    ct = parsed.get("contentType") or parsed.get("dataObjectType") or t.get("dataObjectType", "")
                    uid = parsed.get("uuid") or ""
                    name = parsed.get("name") or t.get("name", "")
                    if not uid:
                        continue
                    results.append(RelationInfo(
                        uuid=str(uid), name=name, type_name=ct,
                        direction="target", content_type=ct,
                    ))
            except Exception as e:
                log.debug("targets fetch failed: %s", e)

        if direction in ("both", "sources"):
            try:
                sources = await _gql_or_rest_list_sources(token, dataspace, type_name, uuid)
                for s in sources:
                    parsed = _parse_eml_entry(s)
                    ct = parsed.get("contentType") or parsed.get("dataObjectType") or s.get("dataObjectType", "")
                    uid = parsed.get("uuid") or ""
                    name = parsed.get("name") or s.get("name", "")
                    if not uid:
                        continue
                    results.append(RelationInfo(
                        uuid=str(uid), name=name, type_name=ct,
                        direction="source", content_type=ct,
                    ))
            except Exception as e:
                log.debug("sources fetch failed: %s", e)

        return results

    @strawberry.field(
        description="List arrays attached to an object"
    )
    async def object_arrays(
        self,
        info: Info,
        dataspace: str,
        type_name: str,
        uuid: str,
        include_statistics: bool = False,
        include_sample_values: bool = False,
        sample_size: int = 50,
    ) -> List[ArrayInfo]:
        pool = await _get_pool()
        if pool:
            arrays = await _pg_list_arrays(pool, dataspace, uuid)
            if arrays:
                results = []
                for a in arrays:
                    ai = ArrayInfo(
                        path=a["path"],
                        data_type=_ARY_TYPE_FMT.get(a["type"], "?"),
                        dimensions=a["dimensions"],
                        total_elements=a["total_elements"],
                    )
                    if (include_statistics or include_sample_values) and a["path"]:
                        try:
                            values = await _pg_read_array(pool, dataspace, uuid, a["path"])
                            if values:
                                ai.total_elements = len(values)
                                if include_statistics:
                                    ai.statistics = _compute_statistics(values)
                                if include_sample_values:
                                    ai.sample_values = values[:sample_size]
                        except Exception as e:
                            log.debug("pg read_array %s failed: %s", a["path"], e)
                    results.append(ai)
                return results
            # PG returned nothing → fall through to REST

        # GQL/REST fallback
        token = _get_token_from_info(info)
        try:
            arrays = await _gql_or_rest_list_arrays(token, dataspace, type_name, uuid)
        except Exception as e:
            log.debug("list_arrays failed: %s", e)
            return []

        results = []
        for a in arrays:
            uid_info = a.get("uid") or {}
            path = uid_info.get("pathInResource", "") if isinstance(uid_info, dict) else ""
            dims = a.get("dimensions") or []
            total = a.get("totalCount") or 0

            ai = ArrayInfo(path=path, total_elements=total)

            if (include_statistics or include_sample_values) and path:
                try:
                    values = await _rest_read_array(token, dataspace, type_name, uuid, path)
                    if values:
                        ai.total_elements = len(values)
                        if include_statistics:
                            ai.statistics = _compute_statistics(values)
                        if include_sample_values:
                            ai.sample_values = values[:sample_size]
                except Exception as e:
                    log.debug("read_array %s failed: %s", path, e)

            results.append(ai)
        return results

    @strawberry.field(
        description=(
            "Deep search: find representations with attached properties matching "
            "kind and cell-value criteria. Queries the RESQML graph + array data. "
            "Supports multiple dataspaces via the 'dataspaces' list parameter. "
            "Use 'category' instead of type_name to search entire RESQML categories: "
            "grid, surface, well, structural, stratigraphic, property, seismic, crs, representation. "
            "type_name also accepts category names or wildcards (e.g. '*Grid*')."
        )
    )
    async def deep_search(
        self,
        info: Info,
        dataspace: Optional[str] = None,
        dataspaces: Optional[List[str]] = None,
        type_name: str = "resqml20.obj_Grid2dRepresentation",
        category: Optional[str] = None,
        title_contains: Optional[str] = None,
        property_filter: Optional[PropertyFilter] = None,
        include_relations: bool = False,
        relation_filter: Optional[List[str]] = None,
        include_statistics: bool = True,
        include_sample_values: bool = False,
        sample_size: int = 50,
        limit: int = 20,
    ) -> DeepSearchResult:
        """
        The flagship query:
          1. List objects of type_name in dataspace(s)
          2. For each, find attached properties via sources (reverse graph)
          3. Filter by property kind
          4. Optionally load array values and apply threshold filter

        Supports querying multiple dataspaces at once via 'dataspaces' param.
        Use 'category' to search all types in a category (e.g. "grid", "well").
        """
        token = _get_token_from_info(info)
        return await deep_search_impl(
            token, dataspace, dataspaces, type_name, title_contains,
            property_filter, include_relations, include_statistics,
            include_sample_values, sample_size, limit, relation_filter,
            category=category,
        )

    @strawberry.field(
        description=(
            "Federated search: query OSDU catalog AND Reservoir DDMS simultaneously. "
            "Merges results by UUID. Covers: (1) indexed OSDU records with ETP links, "
            "(2) un-indexed RDDMS data (local PG), (3) both together with dedup. "
            "Set search_catalog=false to skip OSDU (e.g. local-only demo). "
            "Set search_rddms=false to skip RDDMS (e.g. catalog-only lookup)."
        )
    )
    async def federated_search(
        self,
        info: Info,
        text: str = "*",
        kind: Optional[str] = None,
        type_name: Optional[str] = None,
        dataspaces: Optional[List[str]] = None,
        search_catalog: bool = True,
        search_rddms: bool = True,
        search_remote_rddms: bool = True,
        include_relations: bool = False,
        relation_filter: Optional[List[str]] = None,
        include_properties: bool = False,
        include_statistics: bool = False,
        property_filter: Optional[PropertyFilter] = None,
        limit: int = 30,
    ) -> FederatedSearchResult:
        """
        Three-path federated search.

        Path A (OSDU Catalog):
          Hits OSDU Search API with ``kind`` + ``text`` query.

        Path B (Local RDDMS / PostgreSQL):
          Queries local PG for objects matching ``type_name``.

        Path C (Remote RDDMS / REST):
          Queries the remote OSDU RDDMS REST API.

        Merge: Results are merged by UUID. If same object found in multiple
               sources, metadata is combined.
        """
        token = _get_token_from_info(info)
        return await federated_search_impl(
            token, text, kind, type_name, dataspaces,
            search_catalog, search_rddms, search_remote_rddms,
            include_relations, include_properties, include_statistics,
            property_filter, limit, relation_filter,
        )

    # ──────────────────────────────────────────────────────────────────────
    # Native RDDMS GraphQL (M27+ etp-client with /graphql endpoint)
    # These expose ETP-native capabilities beyond REST:
    #   • True graph traversal with directed edges
    #   • Full object content (parsed XML → JSON)
    #   • Array metadata with dimensions & types
    # Falls back to REST automatically if native GQL is unavailable.
    # ──────────────────────────────────────────────────────────────────────

    @strawberry.field(
        description=(
            "Native ETP graph traversal (M27+). Returns resources and directed edges "
            "forming the RESQML topology graph. Unlike objectRelations (which gives a "
            "flat list), this preserves full graph structure for visualization. "
            "Uses native /graphql endpoint when available; REST fallback otherwise."
        )
    )
    async def native_graph_search(
        self,
        info: Info,
        dataspace: str,
        type_name: str = "resqml20.obj_IjkGridRepresentation",
        depth: int = 2,
        limit: int = 3,
    ) -> NativeGraphResult:
        token = _get_token_from_info(info)
        return await native_graph_search_impl(token, dataspace, type_name, depth, limit)

    @strawberry.field(
        description=(
            "Full object content as JSON (M27+). Fetches the complete parsed "
            "RESQML/EML XML body via ETP Store protocol. Use to inspect Citation, "
            "CRS references, geometry parameters, property kind definitions, etc. "
            "Uses native /graphql endpoint when available; REST $format=json fallback."
        )
    )
    async def native_object_content(
        self,
        info: Info,
        dataspace: str,
        type_name: str = "resqml20.obj_IjkGridRepresentation",
        uuid: Optional[str] = None,
        limit: int = 1,
    ) -> List[NativeObjectContent]:
        token = _get_token_from_info(info)
        return await native_object_content_impl(token, dataspace, type_name, uuid, limit)

    @strawberry.field(
        description=(
            "Array metadata without downloading data (M27+). Shows what arrays exist "
            "inside a resource (grid geometry, property values) with shape, logical type, "
            "and last-write timestamp — without fetching the (potentially GB-sized) payload. "
            "Uses native /graphql endpoint when available; REST fallback otherwise."
        )
    )
    async def native_array_metadata(
        self,
        info: Info,
        dataspace: str,
        type_name: str = "resqml20.obj_IjkGridRepresentation",
        limit: int = 2,
    ) -> List[NativeResourceWithArrays]:
        token = _get_token_from_info(info)
        return await native_array_metadata_impl(token, dataspace, type_name, limit)


# ──────────────────────────────────────────────────────────────────────────────
# Build Strawberry schema and FastAPI router
# ──────────────────────────────────────────────────────────────────────────────

schema = strawberry.Schema(query=Query)


async def get_context(request: Request) -> dict:
    return {"request": request}


graphql_app = _StrawberryRouter(schema, context_getter=get_context)

router = APIRouter()
router.include_router(graphql_app, prefix="/graphql")


@router.post("/api/graphql/query")
async def graphql_query_api(request: Request):
    """Execute a GraphQL query. Body: {"query": "...", "variables": {...}}"""
    body = await request.json()
    query = body.get("query", "")
    variables = body.get("variables") or {}

    if not query:
        return JSONResponse({"errors": [{"message": "No query provided"}]}, status_code=400)

    result = await schema.execute(
        query,
        variable_values=variables,
        context_value={"request": request},
    )

    response: dict[str, Any] = {}
    if result.data is not None:
        response["data"] = result.data
    if result.errors:
        response["errors"] = [
            {"message": str(e), "path": e.path} for e in result.errors
        ]
    return JSONResponse(response)


@router.get("/api/graphql/info")
async def graphql_info():
    """Return GraphQL backend configuration info (no auth required)."""
    from .pg_backend import get_connection_info

    ci = get_connection_info()
    pool = await _get_pool()
    rddms_pool = await _get_rddms_pool()

    pg_connected = pool is not None
    rddms_pg_connected = rddms_pool is not None

    # Determine backend description
    backends = []
    if pg_connected:
        backends.append("Local PostgreSQL")
    if rddms_pg_connected:
        backends.append("Remote RDDMS PostgreSQL")
    if not backends:
        backends.append("REST API")
    backend_str = " + ".join(backends) + (" + REST fallback" if backends != ["REST API"] else "")

    return JSONResponse({
        "pg_configured": ci["pg_configured"],
        "pg_connected": pg_connected,
        "pg_connection": ci["pg_conn_string"],
        "rddms_pg_configured": ci["rddms_pg_configured"],
        "rddms_pg_connected": rddms_pg_connected,
        "rddms_pg_connection": ci["rddms_pg_conn_string"],
        "backend": backend_str,
        "hint": "Set GRAPHQL_PG_CONN_STRING for local PG, RDDMS_PG_CONN_STRING for remote RDDMS PG. "
                "REST API is always available as fallback.",
    })
