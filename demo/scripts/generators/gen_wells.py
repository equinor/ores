"""
gen_wells.py - Generic Well + Wellbore master-data generator.

Spec format:
{
  "generator": "wells",
  "wells": [
    {
      "name": "55/33-A-1",
      "facility": "55/33-A-1",
      "field": "Drogon",
      "description": "Discovery well targeting Valysar Fm.",
      "wellbores": [
        {"name": "55/33-A-1", "facility": "55/33-A-1",
         "description": "Main bore", "target": "Valysar Fm", "seq": 1}
      ]
    }
  ]
}
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from ._common import default_acl, default_legal, det_uuid
from ._registry import register


@register("wells")
def generate(
    spec: Dict[str, Any],
    pfx: str,
    base_dir: Path,
    refs: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Generate Well + Wellbore master-data records."""
    acl = spec.get("acl") or default_acl(pfx)
    legal = spec.get("legal") or default_legal(pfx)
    uid_pfx = spec.get("uuid_prefix", "well")

    records: List[Dict[str, Any]] = []

    for wdef in spec["wells"]:
        wb_records: List[Dict[str, Any]] = []
        wb_ids: List[str] = []

        # Create wellbore records
        for wb in wdef.get("wellbores", []):
            wb_uid = det_uuid(f"{uid_pfx}-wb-{wb['name']}")
            wb_id = f"{pfx}:master-data--Wellbore:{wb_uid}:1"
            wb_ids.append(wb_id)
            wb_records.append({
                "id": wb_id,
                "kind": "osdu:wks:master-data--Wellbore:1.0.0",
                "acl": acl,
                "legal": legal,
                "data": {
                    "Name": wb["name"],
                    "FacilityName": wb.get("facility", wb["name"]),
                    "Description": wb.get("description", ""),
                    "WellID": "",  # patched below
                    "SequenceNumber": wb.get("seq", 1),
                    "TargetFormation": wb.get("target", ""),
                    "DefaultVerticalMeasurementID": "",
                    "DefinitiveTrajectoryID": "",
                    "DrillingReasons": [],
                    "KickOffWellbore": "",
                    "PrimaryMaterialID": "",
                    "TrajectoryTypeID": "",
                    "VerticalMeasurements": [],
                    "ancestry": {"parents": [], "children": []},
                },
            })

        # Create well record
        well_uid = det_uuid(f"{uid_pfx}-{wdef['name']}")
        well_id = f"{pfx}:master-data--Well:{well_uid}:1"

        well_rec = {
            "id": well_id,
            "kind": "osdu:wks:master-data--Well:1.0.0",
            "acl": acl,
            "legal": legal,
            "data": {
                "Name": wdef["name"],
                "FacilityName": wdef.get("facility", wdef["name"]),
                "Description": wdef.get("description", ""),
                "FieldName": wdef.get("field", ""),
                "DefaultVerticalCRSID": "",
                "DefaultVerticalMeasurementID": "",
                "InterestTypeID": "",
                "VerticalMeasurements": [],
                "ancestry": {"parents": [], "children": wb_ids},
            },
        }
        records.append(well_rec)

        # Patch wellbore WellID + ancestry
        for wb_rec in wb_records:
            wb_rec["data"]["WellID"] = well_id
            wb_rec["data"]["ancestry"]["parents"] = [well_id]
        records.extend(wb_records)

    return records
