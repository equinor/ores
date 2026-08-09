"""
Native GraphQL client for the Reservoir DDMS etp-client.

Provides async helpers that query the new /graphql endpoint on the
etp-client directly, falling back to REST when the GraphQL endpoint
is unavailable (e.g. older etp-client versions, or ADME deployments
without the graphql module).

Usage:
    from .rddms_gql import gql_query, gql_available

    if await gql_available(token):
        result = await gql_query(token, QUERY, variables)
    else:
        # fall back to REST
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from . import osdu

log = logging.getLogger("rddms-admin.rddms_gql")

# Cache availability probe result per base_url to avoid repeated probes.
_gql_available_cache: Dict[str, bool] = {}


def _gql_url() -> str:
    """Build the native GraphQL endpoint URL from the active RDDMS base.

    Local dev:  http://localhost:8080/graphql
    ADME/OSDU:  https://<hostname>/api/reservoir-ddms/v2/graphql
    Override:   RDDMS_GRAPHQL_URL env var (takes precedence)
    """
    override = os.getenv("RDDMS_GRAPHQL_URL", "").strip()
    if override:
        return override

    base = osdu.OSDU_BASE_URL
    if not base:
        return ""

    # Local: if the base looks like localhost:PORT, use http
    if "localhost" in base or "127.0.0.1" in base:
        scheme = "http"
        # Strip port if needed - the rddms_url function adds the path
        return f"{scheme}://{base}/graphql"

    # ADME/OSDU: same host, under the reservoir-ddms path
    return f"https://{base}/api/reservoir-ddms/v2/graphql"


async def gql_available(token: str = "") -> bool:
    """Probe whether the native GraphQL endpoint responds.

    Results are cached for the lifetime of the process (reset on instance switch).
    """
    url = _gql_url()
    if not url:
        return False

    if url in _gql_available_cache:
        return _gql_available_cache[url]

    # Lightweight introspection probe
    try:
        async with osdu.http_client(timeout=5) as client:
            r = await client.post(
                url,
                headers=osdu.headers(token) if token else {"Content-Type": "application/json"},
                json={"query": "{ __typename }"},
            )
            available = r.status_code == 200
    except Exception:
        available = False

    _gql_available_cache[url] = available
    if available:
        log.info("Native GraphQL endpoint available at %s", url)
    else:
        log.debug("Native GraphQL endpoint not available at %s (will use REST)", url)
    return available


def reset_availability_cache():
    """Called on instance switch to re-probe the new endpoint."""
    _gql_available_cache.clear()


async def gql_query(
    token: str,
    query: str,
    variables: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute a GraphQL query against the native RDDMS endpoint.

    Returns the full response dict: {"data": {...}, "errors": [...]}
    Raises on HTTP-level errors (timeouts, 5xx).
    """
    url = _gql_url()
    if not url:
        raise RuntimeError("No RDDMS GraphQL URL configured")

    body: Dict[str, Any] = {"query": query}
    if variables:
        body["variables"] = variables

    async with osdu.http_client(timeout=30) as client:
        r = await client.post(url, headers=osdu.headers(token), json=body)
        r.raise_for_status()
        return r.json()


# ──────────────────────────────────────────────────────────────────────────────
# Pre-built queries for common operations (avoid string-building in resolvers)
# ──────────────────────────────────────────────────────────────────────────────

Q_DATASPACES = """{
  dataspaces { uri name storeLastWrite storeCreated }
}"""

Q_RESOURCES = """query($uri: String!, $types: [String!]) {
  resources(dataspaceUri: $uri, dataObjectTypes: $types) {
    uri name dataObjectType sourceCount targetCount
    lastChanged storeLastWrite activeStatus
  }
}"""

Q_RESOURCE = """query($uri: String!) {
  resource(uri: $uri) {
    uri name dataObjectType sourceCount targetCount
    lastChanged storeLastWrite activeStatus
  }
}"""

Q_GRAPH_SEARCH = """query($uris: [String!]!, $depth: Int) {
  graphSearch(uris: $uris, depth: $depth) {
    resources { uri name dataObjectType sourceCount targetCount lastChanged activeStatus }
    edges { sourceUri targetUri path }
  }
}"""

Q_TARGETS = """query($uri: String!) {
  resource(uri: $uri) {
    uri name
    targets { uri name dataObjectType sourceCount targetCount activeStatus }
  }
}"""

Q_SOURCES = """query($uri: String!) {
  resource(uri: $uri) {
    uri name
    sources { uri name dataObjectType sourceCount targetCount activeStatus }
  }
}"""

Q_CONTENT = """query($uri: String!) {
  resource(uri: $uri) {
    uri name
    content { uri dataObjectType data }
  }
}"""

Q_ARRAYS = """query($uri: String!) {
  resource(uri: $uri) {
    uri name
    arrays { uri pathInResource dimensions logicalArrayType transportArrayType storeLastWrite }
  }
}"""
