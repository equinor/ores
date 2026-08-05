"""
gen_document.py - Generate Document WPC records.

Produces work-product-component--Document records with optional
inline Markdown content read from a source file.

Spec format:
{
  "generator": "document",
  "id": "dev:work-product-component--Document:MyDoc:1",
  "project": "OmegaSor",
  "name": "Document title",
  "description": "...",
  "document_type": "DatasetDocumentation",
  "document_date": "2026-08-05",
  "is_discoverable": true,
  "source_file": "md/OsduWellWpcOntology.md",   // relative to repo root
  "sharepoint_url": "https://...",
  "parent_ids": ["dev:master-data--BusinessDecision:OmegaSor-WPC:1"],
  "extension_properties": {}   // optional extra fields in ExtensionProperties
}
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from ._common import default_acl, default_legal, wpc_id, det_uuid
from ._registry import register


@register("document")
def generate(
    spec: Dict[str, Any],
    pfx: str,
    base_dir: Path,
    refs: Dict[str, Any],
) -> List[Dict[str, Any]]:
    acl = spec.get("acl") or default_acl(pfx)
    legal = spec.get("legal") or default_legal(pfx)

    project = spec.get("project", "")
    name = spec["name"]
    record_id = spec.get("id") or wpc_id(pfx, "Document", det_uuid(f"{project}-{name}"))

    data: Dict[str, Any] = {
        "Name": name,
        "Description": spec.get("description", ""),
        "DocumentType": spec.get("document_type", "General"),
        "DocumentDate": spec.get("document_date", ""),
        "IsDiscoverable": spec.get("is_discoverable", True),
        "ExistenceKind": f"{pfx}:reference-data--ExistenceKind:Active:",
    }

    # ── ExtensionProperties (with optional Markdown from file) ──
    ext: Dict[str, Any] = dict(spec.get("extension_properties") or {})

    source_file = spec.get("source_file", "")
    if source_file:
        ext["SourceFile"] = source_file
        # Resolve the markdown file relative to repo root (base_dir/../..)
        repo_root = base_dir
        # Walk up until we find the md/ folder or use base_dir as-is
        for _ in range(5):
            if (repo_root / "md").is_dir():
                break
            repo_root = repo_root.parent
        md_path = repo_root / source_file
        if md_path.exists():
            ext["Markdown"] = md_path.read_text(encoding="utf-8")

    if spec.get("sharepoint_url"):
        ext["SharePointProjectArea"] = spec["sharepoint_url"]

    if ext:
        data["ExtensionProperties"] = ext

    # ── ancestry (parent records) ──
    parent_ids = spec.get("parent_ids") or []
    if parent_ids:
        data["ancestry"] = {"parents": parent_ids}

    return [{
        "id": record_id,
        "kind": "osdu:wks:work-product-component--Document:1.2.0",
        "acl": acl,
        "legal": legal,
        "data": data,
    }]
