"""
record_factory.py - Generic OSDU record template engine.

Creates OSDU records from templates + input data. Supports:
  - Generating blank templates (to fill in manually)
  - Generating filled records from JSON input
  - Interactive prompting for missing fields
  - Deterministic UUID generation for stable record IDs

Independent of ORES — works with any OSDU-compatible system.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import OsduInstance


TEMPLATES_DIR = Path(__file__).parent / "templates"

# Deterministic UUID namespace (stable across regenerations)
OSDU_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


# ── Record type registry ─────────────────────────────────────────────────

RECORD_TYPES = {
    "business_decision": {
        "category": "master-data",
        "entity": "BusinessDecision",
        "kind_version": "1.0.0",
        "template": "business_decision.json",
    },
    "risk": {
        "category": "master-data",
        "entity": "Risk",
        "kind_version": "1.2.0",
        "template": "risk.json",
    },
    "activity": {
        "category": "work-product-component",
        "entity": "Activity",
        "kind_version": "1.0.0",
        "template": "activity.json",
    },
    "activity_template": {
        "category": "work-product-component",
        "entity": "ActivityTemplate",
        "kind_version": "1.0.0",
        "template": "activity_template.json",
    },
    "document": {
        "category": "work-product-component",
        "entity": "Document",
        "kind_version": "1.2.0",
        "template": "document.json",
    },
    "persisted_collection": {
        "category": "work-product-component",
        "entity": "PersistedCollection",
        "kind_version": "1.0.0",
        "template": "persisted_collection.json",
    },
    "collaboration_project": {
        "category": "work-product-component",
        "entity": "CollaborationProject",
        "kind_version": "1.0.0",
        "template": "collaboration_project.json",
    },
    "reservoir_volumes": {
        "category": "work-product-component",
        "entity": "ReservoirEstimatedVolumes",
        "kind_version": "1.0.0",
        "template": "reservoir_volumes.json",
    },
    "geolabelset": {
        "category": "work-product-component",
        "entity": "GeoLabelSet",
        "kind_version": "1.0.0",
        "template": "geolabelset.json",
    },
    "development_concept": {
        "category": "work-product-component",
        "entity": "DevelopmentConcept",
        "kind_version": "1.0.0",
        "template": "development_concept.json",
    },
    "column_based_table": {
        "category": "work-product-component",
        "entity": "ColumnBasedTable",
        "kind_version": "1.0.0",
        "template": "column_based_table.json",
    },
    "reservoir": {
        "category": "master-data",
        "entity": "Reservoir",
        "kind_version": "1.0.0",
        "template": "reservoir.json",
    },
    "activity_state_template": {
        "category": "work-product-component",
        "entity": "ActivityStateTemplate",
        "kind_version": "1.0.0",
        "template": "activity_state_template.json",
    },
}


def get_record_types() -> List[str]:
    """Return list of supported record type names."""
    return sorted(RECORD_TYPES.keys())


def make_record_id(
    partition: str, record_type: str, slug: str, version: int = 1
) -> str:
    """Generate a deterministic OSDU record ID.

    Format: {partition}:{category}--{Entity}:{uuid5(slug)}:{version}
    """
    info = RECORD_TYPES[record_type]
    uid = uuid.uuid5(OSDU_NS, slug)
    return f"{partition}:{info['category']}--{info['entity']}:{uid}:{version}"


def make_kind(record_type: str) -> str:
    """Generate the 'kind' field for a record type."""
    info = RECORD_TYPES[record_type]
    return f"osdu:wks:{info['category']}--{info['entity']}:{info['kind_version']}"


def load_template(record_type: str) -> Dict[str, Any]:
    """Load the JSON template for a record type."""
    if record_type not in RECORD_TYPES:
        raise ValueError(
            f"Unknown record type: {record_type}\n"
            f"Available: {', '.join(get_record_types())}"
        )
    info = RECORD_TYPES[record_type]
    template_path = TEMPLATES_DIR / info["template"]
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")
    return json.loads(template_path.read_text(encoding="utf-8"))


def generate_blank_template(
    record_type: str,
    instance: OsduInstance,
    slug: str = "REPLACE_ME",
) -> Dict[str, Any]:
    """Generate a blank record with envelope filled, data as template placeholders."""
    template = load_template(record_type)
    return _wrap_envelope(record_type, instance, slug, template["data"])


def generate_record(
    record_type: str,
    instance: OsduInstance,
    data: Dict[str, Any],
    *,
    slug: Optional[str] = None,
    version: int = 1,
) -> Dict[str, Any]:
    """Generate a complete OSDU record from input data.

    Merges provided data with the template defaults, wraps in the standard envelope.
    """
    template = load_template(record_type)
    # Merge: input data overrides template defaults
    merged_data = {**template["data"], **data}

    # Auto-generate slug from Name if not provided
    if not slug:
        name = merged_data.get("Name", record_type)
        slug = _slugify(name)

    return _wrap_envelope(record_type, instance, slug, merged_data, version=version)


def generate_records_from_input(
    input_config: Dict[str, Any],
    instance: OsduInstance,
) -> List[Dict[str, Any]]:
    """Generate multiple records from a pipeline input config.

    Input config format:
    {
        "project": "My Project",
        "gate": "DG2",
        "records": [
            {"type": "business_decision", "slug": "my-bd", "data": {...}},
            {"type": "risk", "slug": "risk-1", "data": {...}},
            ...
        ]
    }
    """
    records: List[Dict[str, Any]] = []
    project = input_config.get("project", "unnamed")
    gate = input_config.get("gate", "")

    for rec_spec in input_config.get("records", []):
        rec_type = rec_spec["type"]
        data = rec_spec.get("data", {})
        slug = rec_spec.get("slug") or f"{project}-{gate}-{rec_type}".lower()
        version = rec_spec.get("version", 1)

        record = generate_record(
            rec_type, instance, data, slug=slug, version=version
        )
        records.append(record)

    return records


def _wrap_envelope(
    record_type: str,
    instance: OsduInstance,
    slug: str,
    data: Dict[str, Any],
    version: int = 1,
) -> Dict[str, Any]:
    """Wrap data in the standard OSDU record envelope."""
    record_id = make_record_id(instance.partition, record_type, slug, version)
    return {
        "id": record_id,
        "kind": make_kind(record_type),
        "acl": instance.acl,
        "legal": instance.legal,
        "data": data,
    }


def _slugify(name: str) -> str:
    """Convert a Name field to a safe slug for ID generation."""
    import re
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")[:80]


# ── Manifest operations ──────────────────────────────────────────────────

def records_to_manifest(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Wrap records in an OSDU manifest envelope (for workflow ingestion)."""
    master = [r for r in records if "master-data" in r.get("kind", "")]
    wpc = [r for r in records if "work-product-component" in r.get("kind", "")]
    refdata = [r for r in records if "reference-data" in r.get("kind", "")]
    datasets = [r for r in records if "dataset" in r.get("kind", "")]

    manifest: Dict[str, Any] = {}
    if refdata:
        manifest["ReferenceData"] = refdata
    if master:
        manifest["MasterData"] = master
    if wpc or datasets:
        manifest["Data"] = {}
        if wpc:
            manifest["Data"]["WorkProductComponents"] = wpc
        if datasets:
            manifest["Data"]["Datasets"] = datasets
    return manifest


def manifest_to_records(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten an OSDU manifest envelope into a list of records."""
    records: List[Dict[str, Any]] = []
    records.extend(manifest.get("ReferenceData", []))
    records.extend(manifest.get("MasterData", []))
    data_section = manifest.get("Data", {})
    records.extend(data_section.get("WorkProductComponents", []))
    records.extend(data_section.get("Datasets", []))
    records.extend(data_section.get("WorkProducts", []))
    return records
