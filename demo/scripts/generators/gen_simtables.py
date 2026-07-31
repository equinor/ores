"""
gen_simtables.py - Generic ColumnBasedTable WPC catalog generator.

Spec format:
{
  "generator": "simtables",
  "project": "Drogon DG2",
  "rddms_dataspace": "maap/drogon_dg",
  "uuid_prefix": "dg2-simtable",
  "tables": [
    {
      "name": "relperm",
      "title": "Relative Permeability",
      "description": "...",
      "fmu_content": "relperm",
      "file_ref": "share/results/tables/relperm.csv",
      "key_columns": [
        {"ColumnName": "SATNUM", "ColumnRole": "Key", "ValueType": "integer"}
      ],
      "value_columns": [
        {"ColumnName": "SW", "ColumnRole": "Value", "ValueType": "number", "UOM": "Euc"}
      ]
    }
  ],
  "masterwp_manifest": "..."
}
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from ._common import (
    load_ref,
    det_uuid, load_json,
    resolve_acl_legal, resolve_reservoir_id,
)
from ._registry import register


@register("simtables")
def generate(
    spec: Dict[str, Any],
    pfx: str,
    base_dir: Path,
    refs: Dict[str, Any],
) -> List[Dict[str, Any]]:
    project = spec.get("project", "")
    rddms_ds = spec.get("rddms_dataspace", "")
    rddms_base = f"eml:///dataspace('{rddms_ds}')" if rddms_ds else ""
    uuid_pfx = spec.get("uuid_prefix", "simtable")
    kind_version = spec.get("kind_version", "1.4.0")

    masterwp = load_ref(spec, refs, "masterwp_manifest", "masterwp", base_dir)
    acl, legal = resolve_acl_legal(spec, pfx, masterwp)
    reservoir_id = resolve_reservoir_id(masterwp)
    ds_slug = rddms_ds.replace("/", "-") if rddms_ds else ""
    dataspace_id = f"{pfx}:dataset--ETPDataspace:{ds_slug}:1" if rddms_ds else ""

    records: List[Dict[str, Any]] = []

    for tbl in spec.get("tables", []):
        tab_uuid = det_uuid(f"{uuid_pfx}-{tbl['name']}")
        tab_id = f"{pfx}:work-product-component--ColumnBasedTable:{tab_uuid}:1"

        # Build column list: key columns as-is, value columns with UOM expansion
        all_columns = list(tbl.get("key_columns", []))
        for col in tbl.get("value_columns", []):
            expanded = {k: v for k, v in col.items() if k != "UOM"}
            if "UOM" in col:
                expanded["UnitOfMeasureID"] = f"{pfx}:reference-data--UnitOfMeasure:{col['UOM']}:"
            all_columns.append(expanded)

        data: Dict[str, Any] = {
            "Name": tbl.get("title", f"{project} - {tbl['name']}" if project else tbl["name"]),
            "Description": tbl.get("description", ""),
            "ColumnBasedTableTypeID": f"{pfx}:reference-data--ColumnBasedTableType:AdHoc:",
            "Columns": all_columns,
        }
        if reservoir_id:
            data["ReservoirID"] = reservoir_id
        if rddms_base and tbl.get("file_ref"):
            data["DDMSDatasets"] = [f"{rddms_base}/{tbl['file_ref']}"]
        fmu: Dict[str, Any] = {}
        if tbl.get("fmu_content"):
            fmu["Content"] = tbl["fmu_content"]
        if tbl.get("file_ref"):
            fmu["FileReference"] = tbl["file_ref"]
        if fmu:
            data["FMU"] = fmu
        if dataspace_id:
            data["data.ancestry.inputs"] = [dataspace_id]

        records.append({
            "id": tab_id,
            "kind": f"osdu:wks:work-product-component--ColumnBasedTable:{kind_version}",
            "acl": acl, "legal": legal, "data": data,
        })

    return records


