"""
generators - Generic OSDU record generators driven by JSON data specs.

Each generator reads a JSON data file and produces OSDU records.
The data file captures all project-specific information (dimensions,
properties, horizons, well definitions, etc.) while the generator
implements the OSDU record-building pattern.

Supported generator types:
  master       - Reservoir + ReservoirSegment + WorkProduct
  wells        - Well + Wellbore master-data
  grid         - IjkGridRepresentation WPCs
  maps         - StructureMap + GenericRepresentation WPCs
  polygons     - GenericRepresentation (polygon/line) WPCs
  simtables    - ColumnBasedTable (simulator tables) WPCs
  volumes_raw  - ReservoirEstimatedVolumes from CSV
  volumes_stat - ReservoirEstimatedVolumes statistics from RAW
  params       - ColumnBasedTable (design matrix / parameters) from CSV/XLSX
  markers      - WellboreMarkerSet + StratColumn + strat hierarchy
  geolabelset  - GeoLabelSet from stat volumes
"""
from __future__ import annotations

from ._common import (
    NS,
    build_manifest,
    find_id,
    find_all_ids,
    load_json,
    load_ref,
    resolve_file,
    write_manifest,
)
from ._registry import GENERATORS, run_generator
