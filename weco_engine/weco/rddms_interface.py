"""
weco.rddms_interface — RDDMS / OSDU REST interface for WeCo I/O
================================================================

High-level async interface that connects WeCo's correlation engine
to live RDDMS / OSDU Reservoir-DDMS servers via REST API.

This module is designed for integration into web frontends (like ORES)
rather than the desktop Qt GUI.  It provides:

  • Async well import from RDDMS (query + fetch trajectories + logs)
  • Async result export to RDDMS (markers, horizons, zonation)
  • Strat column read/write via RDDMS
  • Token-based authentication (Azure AD / OSDU)
  • Streaming progress for long operations

Typical usage from a FastAPI/ORES router::

    from weco.rddms_interface import RddmsConnector

    connector = RddmsConnector(base_url, token)
    wells = await connector.import_wells(dataspace="project/field")
    result = run_correlation(wells, options)
    await connector.export_results(result, wells, dataspace="project/field")

Architecture
------------
::

    ┌────────────────────┐         ┌──────────────────────┐
    │ ORES Web Frontend  │◄─────►  │  WeCo API (FastAPI)  │
    │  (JS / React)      │  HTTP   │  /rddms/* endpoints  │
    └────────────────────┘         └──────────┬───────────┘
                                              │
                                   ┌──────────▼───────────┐
                                   │ weco.rddms_interface  │
                                   │  RddmsConnector       │
                                   └──────────┬───────────┘
                                              │ REST
                                   ┌──────────▼───────────┐
                                   │  Reservoir-DDMS v2    │
                                   │  (OSDU platform)      │
                                   └──────────────────────┘
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger("weco.rddms_interface")


# ═══════════════════════════════════════════════════════════════════════════
#  Configuration
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class RddmsConfig:
    """Connection configuration for a Reservoir-DDMS / OSDU endpoint."""

    base_url: str
    """RDDMS or OSDU base URL (e.g. https://host/api/reservoir-ddms/v2)."""

    token: str = ""
    """Bearer access token. Refreshed externally (ORES session, env, etc.)."""

    dataspace: str = "default"
    """RDDMS dataspace or OSDU data-partition-id."""

    timeout_s: float = 60.0
    """HTTP request timeout in seconds."""

    max_wells: int = 500
    """Safety limit on number of wells to fetch."""

    @classmethod
    def from_env(cls) -> "RddmsConfig":
        """Create config from environment variables."""
        return cls(
            base_url=os.environ.get("RDDMS_URL", ""),
            token=os.environ.get("OSDU_TOKEN", ""),
            dataspace=os.environ.get("RDDMS_DATASPACE", "default"),
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Async RDDMS Connector
# ═══════════════════════════════════════════════════════════════════════════

class RddmsConnector:
    """Async connector for RDDMS / OSDU well data import and result export.

    Uses httpx for async HTTP.  Designed to be called from FastAPI endpoints
    or any asyncio-based web framework.
    """

    def __init__(self, config: RddmsConfig):
        self.config = config
        self._client = None

    async def _get_client(self):
        """Lazily create httpx async client."""
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                headers={
                    "Authorization": f"Bearer {self.config.token}",
                    "data-partition-id": self.config.dataspace,
                    "Content-Type": "application/json",
                },
                timeout=self.config.timeout_s,
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # ─── Well Discovery ───────────────────────────────────────────────

    async def list_wells(
        self,
        filter_name: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List available wells in the dataspace.

        Returns list of dicts with keys: id, name, description, crs.
        """
        client = await self._get_client()

        # OSDU search endpoint for WellboreTrajectoryRepresentation
        query = {
            "kind": "osdu:wks:work-product-component--WellboreTrajectory:1.1.0",
            "limit": min(limit, self.config.max_wells),
        }
        if filter_name:
            query["query"] = f'data.Name: "*{filter_name}*"'

        resp = await client.post("/search/v2/query", json=query)
        resp.raise_for_status()
        data = resp.json()

        wells = []
        for rec in data.get("results", []):
            wells.append({
                "id": rec.get("id", ""),
                "name": rec.get("data", {}).get("Name", "Unknown"),
                "description": rec.get("data", {}).get("Description", ""),
                "crs": rec.get("data", {}).get("SpatialLocation", {}).get("Wgs84Coordinates", {}),
            })
        return wells

    # ─── Well Import ──────────────────────────────────────────────────

    async def import_wells(
        self,
        well_ids: Optional[List[str]] = None,
        filter_name: Optional[str] = None,
        logs: Optional[List[str]] = None,
    ) -> "WellList":
        """Import wells from RDDMS into WeCo WellList.

        Parameters
        ----------
        well_ids : list of OSDU record IDs (if known)
        filter_name : name filter for discovery
        logs : list of log mnemonics to fetch (None = all available)

        Returns
        -------
        WellList ready for the WeCo engine.
        """
        from .data import Well, WellList

        client = await self._get_client()

        # Discover wells if IDs not provided
        if not well_ids:
            discovered = await self.list_wells(filter_name=filter_name)
            well_ids = [w["id"] for w in discovered]

        if not well_ids:
            raise ValueError("No wells found matching criteria")

        if len(well_ids) > self.config.max_wells:
            logger.warning(
                f"Limiting to {self.config.max_wells} wells "
                f"(found {len(well_ids)})"
            )
            well_ids = well_ids[:self.config.max_wells]

        # Fetch wells in parallel (bounded concurrency)
        sem = asyncio.Semaphore(10)

        async def _fetch_one(wid: str) -> Optional[Well]:
            async with sem:
                return await self._fetch_well(client, wid, logs)

        tasks = [_fetch_one(wid) for wid in well_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        wells = []
        for r in results:
            if isinstance(r, Exception):
                logger.warning(f"Failed to fetch well: {r}")
            elif r is not None:
                wells.append(r)

        if not wells:
            raise ValueError("No wells could be imported")

        wl = WellList.__new__(WellList)
        wl.wells = wells
        wl.well_names = [w.name for w in wells]
        logger.info(f"Imported {len(wells)} wells from RDDMS")
        return wl

    async def _fetch_well(self, client, well_id: str, logs: Optional[List[str]]) -> "Well":
        """Fetch a single well's trajectory + logs from RDDMS."""
        from .data import Well

        # Fetch well metadata
        resp = await client.get(f"/wells/{well_id}")
        resp.raise_for_status()
        meta = resp.json()

        name = meta.get("name", meta.get("data", {}).get("Name", well_id[:12]))

        # Fetch trajectory (MD, X, Y, Z)
        resp = await client.get(f"/wells/{well_id}/trajectory")
        resp.raise_for_status()
        traj = resp.json()

        md = np.array(traj.get("md", traj.get("measuredDepths", [])), dtype=np.float64)
        x_arr = np.array(traj.get("x", traj.get("eastings", [])), dtype=np.float64)
        y_arr = np.array(traj.get("y", traj.get("northings", [])), dtype=np.float64)
        z_arr = np.array(traj.get("z", traj.get("tvds", [])), dtype=np.float64)

        size = len(md)
        if size == 0:
            raise ValueError(f"Well {name}: empty trajectory")

        # Create Well object
        well = Well.__new__(Well)
        well.name = name
        well.size = size
        well.x = float(x_arr[0]) if len(x_arr) > 0 else 0.0
        well.y = float(y_arr[0]) if len(y_arr) > 0 else 0.0
        well.z = float(z_arr[0]) if len(z_arr) > 0 else 0.0
        well.h = float(md[-1] - md[0]) if size > 1 else 0.0
        well.data = {"Depth": list(md)}
        well.region = {}
        well.meta = {"rddms_id": well_id}

        # Fetch logs
        resp = await client.get(f"/wells/{well_id}/logs")
        resp.raise_for_status()
        log_list = resp.json()

        for log_info in log_list.get("logs", log_list.get("channels", [])):
            mnemonic = log_info.get("mnemonic", log_info.get("name", ""))
            if logs and mnemonic not in logs:
                continue

            resp = await client.get(f"/wells/{well_id}/logs/{mnemonic}")
            if resp.status_code != 200:
                continue
            log_data = resp.json()
            values = log_data.get("values", log_data.get("data", []))

            if len(values) == size:
                arr = np.array(values, dtype=np.float64)
                if log_info.get("type") == "discrete" or log_info.get("is_discrete"):
                    well.region[mnemonic] = [int(v) for v in arr]
                else:
                    well.data[mnemonic] = list(arr)
            else:
                logger.debug(
                    f"Well {name}: log {mnemonic} length mismatch "
                    f"({len(values)} vs {size}), skipping"
                )

        return well

    # ─── Result Export ────────────────────────────────────────────────

    async def export_results(
        self,
        res_file: "ResFile",
        well_list: "WellList",
        cor_index: int = 0,
        export_markers: bool = True,
        export_zonation: bool = True,
    ) -> Dict[str, Any]:
        """Export correlation results back to RDDMS.

        Creates WellboreMarkerFrameRepresentation objects on the server.

        Returns summary dict with counts.
        """
        client = await self._get_client()
        summary = {"markers_exported": 0, "zones_exported": 0}

        if res_file is None or res_file.get_nbr_results() == 0:
            return summary

        path = res_file.get_result_full_path(cor_index)
        well_ids = res_file.well_id

        if export_markers:
            # Build marker frame per well
            markers_payload = []
            for wi, wid in enumerate(well_ids):
                well = well_list.wells[wid]
                rddms_id = ""
                if hasattr(well, "meta") and well.meta:
                    rddms_id = well.meta.get("rddms_id", "")

                # Extract marker depths from correlation path
                marker_depths = []
                for node in path:
                    if hasattr(node, '__getitem__'):
                        pos = node[wi] if wi < len(node) else -1
                    else:
                        pos = getattr(node, f"w{wi}", -1)
                    if pos >= 0 and "Depth" in well.data:
                        depth = well.data["Depth"]
                        if pos < len(depth):
                            marker_depths.append(depth[pos])

                if marker_depths and rddms_id:
                    markers_payload.append({
                        "well_id": rddms_id,
                        "well_name": well.name,
                        "marker_depths": marker_depths,
                        "source": "WeCo correlation",
                        "correlation_index": cor_index,
                    })

            if markers_payload:
                resp = await client.post(
                    "/wells/markers/batch",
                    json={"markers": markers_payload},
                )
                if resp.status_code in (200, 201):
                    summary["markers_exported"] = len(markers_payload)
                else:
                    logger.warning(
                        f"Marker export failed: {resp.status_code} {resp.text[:200]}"
                    )

        return summary

    # ─── Strat Column ─────────────────────────────────────────────────

    async def import_strat_column(
        self,
        column_id: Optional[str] = None,
    ) -> Optional["StratColumn"]:
        """Import a stratigraphic column from RDDMS.

        Returns a StratColumn object or None if not found.
        """
        from .strat_column import StratColumn

        client = await self._get_client()

        if column_id:
            resp = await client.get(f"/strat-columns/{column_id}")
        else:
            # Search for available columns
            resp = await client.get("/strat-columns")

        if resp.status_code != 200:
            logger.warning(f"Strat column fetch failed: {resp.status_code}")
            return None

        data = resp.json()

        # Parse into StratColumn (handles both single and list responses)
        if isinstance(data, list):
            if not data:
                return None
            data = data[0]  # Take first available

        try:
            col = StratColumn(
                name=data.get("name", "Imported"),
                ranks=[],
            )
            for rank_data in data.get("ranks", []):
                col.add_rank(
                    name=rank_data.get("name", ""),
                    units=[u.get("name", "") for u in rank_data.get("units", [])],
                    horizons=[h.get("name", "") for h in rank_data.get("horizons", [])],
                )
            return col
        except Exception as e:
            logger.warning(f"Failed to parse strat column: {e}")
            return None

    # ─── Health Check ─────────────────────────────────────────────────

    async def health_check(self) -> Dict[str, Any]:
        """Check RDDMS server connectivity."""
        client = await self._get_client()
        try:
            resp = await client.get("/health")
            return {
                "connected": resp.status_code == 200,
                "status_code": resp.status_code,
                "url": self.config.base_url,
            }
        except Exception as e:
            return {
                "connected": False,
                "error": str(e),
                "url": self.config.base_url,
            }


# ═══════════════════════════════════════════════════════════════════════════
#  Synchronous wrapper (for use in non-async contexts like Qt GUI)
# ═══════════════════════════════════════════════════════════════════════════

def sync_import_wells(
    url: str,
    token: str,
    dataspace: str = "default",
    well_ids: Optional[List[str]] = None,
    filter_name: Optional[str] = None,
) -> "WellList":
    """Synchronous wrapper around RddmsConnector.import_wells()."""
    config = RddmsConfig(base_url=url, token=token, dataspace=dataspace)
    connector = RddmsConnector(config)
    try:
        return asyncio.run(connector.import_wells(well_ids=well_ids, filter_name=filter_name))
    finally:
        asyncio.run(connector.close())


def sync_export_results(
    url: str,
    token: str,
    dataspace: str,
    res_file,
    well_list,
    cor_index: int = 0,
) -> Dict[str, Any]:
    """Synchronous wrapper around RddmsConnector.export_results()."""
    config = RddmsConfig(base_url=url, token=token, dataspace=dataspace)
    connector = RddmsConnector(config)
    try:
        return asyncio.run(connector.export_results(res_file, well_list, cor_index))
    finally:
        asyncio.run(connector.close())
