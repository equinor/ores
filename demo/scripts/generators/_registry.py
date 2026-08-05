"""
_registry.py - Generator dispatch registry.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ._common import load_json


# type: generator_name → callable(spec, pfx, base_dir, refs) → list[record]
GENERATORS: Dict[str, Callable] = {}


def register(name: str):
    """Decorator to register a generator function."""
    def decorator(fn):
        GENERATORS[name] = fn
        return fn
    return decorator


def run_generator(
    spec: Dict[str, Any],
    partition_prefix: str = "dev",
    base_dir: Optional[Path] = None,
    refs: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Run a generator from a spec dict.

    Args:
        spec: Generator spec with at least {"generator": "<type>", ...}
        partition_prefix: OSDU partition prefix (e.g. "dev")
        base_dir: Base directory for resolving relative file paths
        refs: Dict of previously-generated manifests/records available
              as cross-references (e.g. {"masterwp": {...}, "activity": {...}})

    Returns:
        List of OSDU records (flat, ready for ingestion)
    """
    gen_type = spec.get("generator")
    if not gen_type:
        raise ValueError("Generator spec must have a 'generator' field")

    # Lazy-import all generator modules to populate registry
    if not GENERATORS:
        _import_all()

    fn = GENERATORS.get(gen_type)
    if not fn:
        available = ", ".join(sorted(GENERATORS.keys()))
        raise ValueError(f"Unknown generator '{gen_type}'. Available: {available}")

    return fn(spec, partition_prefix, base_dir or Path.cwd(), refs or {})


def _import_all():
    """Import all generator modules to trigger @register decorators."""
    from . import (  # noqa: F401
        gen_master,
        gen_wells,
        gen_grid,
        gen_maps,
        gen_polygons,
        gen_simtables,
        gen_volumes_raw,
        gen_volumes_stat,
        gen_params,
        gen_markers,
        gen_geolabelset,
        gen_ontology,
        gen_document,
    )
