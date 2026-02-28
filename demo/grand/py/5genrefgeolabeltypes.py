
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rev_geolabeltypes.py — ADME/OSDU-compliant manifest generator
Creates reference-data records for:
  kind = osdu:wks:reference-data--GeoLabelType:1.0.0

Design:
- NO FacetType/FacetRole creation here.
- Numeric labels (volumetric) use UnitQuantity 'volume' and UnitOfMeasure 'sm3'.
- 'Realization' is hardcoded to ValueType='number'.
- 'Zone' is hardcoded to ValueType='string'.
"""
import argparse, json, os
from pathlib import Path
from typing import Any, Dict, List, Tuple

DEFAULT_LEGALTAG = "dev-equinor-osdu-reference-default"
DEFAULT_ACL_OWNER = "data.default.owners@dev.dataservices.energy"
DEFAULT_ACL_VIEWER = "data.office.global.viewers@dev.dataservices.energy"
DEFAULT_COUNTRIES = ["NO"]

KIND_GEOLABELTYPE = "osdu:wks:reference-data--GeoLabelType:1.0.0"
KIND_MANIFEST     = "osdu:wks:Manifest:1.0.0"

GLT_SPECS: List[Tuple[str, str]] = [
    ("Bulk",            "Bulk volume, Gross volume, GRV"),
    ("Net",             "Net volume, NV"),
    ("Pore",            "Pore volume, PV"),
    ("HydrocarbonPore", "Hydrocarbon pore volume, HCPV"),
    ("Oil",             "Stock tank oil initially in place, STOOIP"),
    ("Gas",             "Gas initially in place, GIIP"),
    ("AssociatedGas",   "Associated gas volume"),
    ("Realization",     "Realization"),
    ("Zone",            "Zone, Interval"),
]

def _acl() -> Dict[str, Any]:
    return {"owners": [DEFAULT_ACL_OWNER], "viewers": [DEFAULT_ACL_VIEWER]}

def _legal(legaltag: str, countries: List[str]) -> Dict[str, Any]:
    return {"legaltags": [legaltag], "otherRelevantDataCountries": countries}

def _split(s: str) -> List[str]:
    return [x.strip() for x in s.replace(";", ",").split(",") if x.strip()]

def build_records(partition: str, legaltag: str, countries: List[str],
                  unit_quantity_code: str = "volume", uom_code: str = "sm3") -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    uq_id  = f"{partition}:reference-data--UnitQuantity:{unit_quantity_code}:"
    uom_id = f"{partition}:reference-data--UnitOfMeasure:{uom_code}:"

    for code, desc in GLT_SPECS:
        rec_id = f"{partition}:reference-data--GeoLabelType:{code}"

        # Hardcoded value types per your request
        if code == "Zone":
            value_type = "string"
        elif code == "Realization":
            value_type = "number"   # integer context; still represented as 'number' in schema
        else:
            value_type = "number"   # volumetric labels

        data: Dict[str, Any] = {
            "Name": code,
            "Code": code,
            "Description": desc,
            "ValueType": value_type,  # "number" | "string" | "boolean"
            "ValueCount": 1,
        }

        # Attach units only for numeric labels
        if value_type == "number":
            data["UnitQuantityID"]  = uq_id
            data["UnitOfMeasureID"] = uom_id

        # Facets intentionally omitted; wire later if existing
        items.append({
            "kind": KIND_GEOLABELTYPE,
            "id": rec_id,
            "acl": _acl(),
            "legal": _legal(legaltag, countries),
            "data": data,
        })

    return items

def build_manifest(ref_items: List[Dict[str, Any]], legaltag: str, countries: List[str]) -> Dict[str, Any]:
    return {
        "kind": KIND_MANIFEST,
        "acl": _acl(),
        "legal": _legal(legaltag, countries),
        "ReferenceData": ref_items,
        "MasterData": [],
        "Data": {"Datasets": [], "WorkProductComponents": [], "WorkProduct": {}},
    }

def main():
    ap = argparse.ArgumentParser(description="Generate GeoLabelType manifest (no facets).")
    ap.add_argument("--partition", default=os.getenv("OSDU_PARTITION", "dev"))
    ap.add_argument("--legaltag", default=DEFAULT_LEGALTAG)
    ap.add_argument("--countries", default=",".join(DEFAULT_COUNTRIES))
    ap.add_argument("--unit_quantity", default="volume")  # PWLS3 class
    ap.add_argument("--uom", default="sm3")               # stock-tank cubic meter
    ap.add_argument("--out", default="reftypes_geolabeltypes.json")
    args = ap.parse_args()

    partition = (args.partition or "dev").strip() or "dev"
    countries = [c[:2].upper() for c in _split(args.countries)]

    records = build_records(partition, args.legaltag, countries, args.unit_quantity, args.uom)
    manifest = build_manifest(records, args.legaltag, countries)
    Path(args.out).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote: {args.out} (partition={partition})")
    print("Summary:")
    print(f"  {KIND_GEOLABELTYPE} = {len(records)}")

if __name__ == "__main__":
    main()
