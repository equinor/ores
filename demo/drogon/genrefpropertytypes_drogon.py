#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
genrefpropertytypes_drogon.py — Generate ReservoirEstimatedVolumePropertyType
reference-data manifest for the Drogon pipeline.

Duplicated from demo/grand/py/5genrefpropertytypes.py so the Drogon tree is
self-contained and independent of grand/.

Output:
  demo/drogon/reftypes_revpropertytypes.json

Usage:
  py demo/drogon/genrefpropertytypes_drogon.py
"""
import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent  # demo/drogon

DEFAULT_LEGALTAG = "dev-equinor-osdu-reference-default"
DEFAULT_ACL_OWNER = "data.default.owners@dev.dataservices.energy"
DEFAULT_ACL_VIEWER = "data.office.global.viewers@dev.dataservices.energy"
DEFAULT_COUNTRIES = ["NO"]

KIND_RESVOL_PROP = "osdu:wks:reference-data--ReservoirEstimatedVolumePropertyType:1.0.0"
KIND_MANIFEST    = "osdu:wks:Manifest:1.0.0"


PROPERTY_SPECS = [
    # ── OSDU OPEN VALUES (fluid volumes) ─────────────────────────────
    ("TotalGas", "Total gas initially in place (GIIP). Free + dissolved gas."),
    ("TotalHydrocarbonGas", "Total hydrocarbon gas volume (HC gas)."),
    ("Non-AssociatedGas", "Non-associated (free) gas. Free gas above oil column."),
    ("Non-AssociatedHydrocarbonGas", "Non-associated hydrocarbon gas."),
    ("AssociatedGas", "Associated gas in oil column (solution gas, SGIIP, Rs)."),
    ("AssociatedHydrocarbon", "Associated liquid hydrocarbons in gas column (condensate/oil)."),
    ("GasCapGas", "Gas cap free gas above oil-water contact."),
    ("GasCapHydrocarbonGas", "Hydrocarbon gas in the gas-cap zone."),
    ("DissolvedGas", "Dissolved/solution gas in oil (SGIIP)."),
    ("DissolvedHydrocarbonGas", "Dissolved hydrocarbon gases in oil."),
    ("Condensate", "Condensate volume in gas column."),
    ("CondensateGas", "Gas components yielding condensate at surface."),
    ("CondensateOil", "Liquid hydrocarbons in gas condensate systems."),
    ("Oil", "Oil in-place: STOIIP (stock-tank oil initially in place)."),
    ("CarbonDioxide", "CO\u2082 volume in reservoir fluids."),
    ("HydrogenSulfide", "H\u2082S volume in reservoir fluids."),
    ("Nitrogen", "N\u2082 in reservoir fluids."),
    ("Hydrocarbon", "Total hydrocarbons (oil + gas)."),
    ("Petroleum", "Total petroleum hydrocarbons."),
    ("Water", "Water volume in reservoir fluids (connate or movable)."),

    # ── LOCAL EXTENSIONS (Equinor) ───────────────────────────────────
    ("BulkOil", "Bulk volume of oil-bearing interval (BULK_OIL). Formula: GRV_OIL."),
    ("BulkGas", "Bulk volume of gas-bearing interval (BULK_GAS). Formula: GRV_GAS."),
    ("BulkTotal", "Bulk volume of full reservoir interval (BULK_TOTAL). Formula: GRV_TOTAL."),
    ("NetOil", "Net rock volume of oil-bearing interval (NET_OIL, NRV_OIL). Formula: NRV = GRV \u00d7 NTG."),
    ("NetGas", "Net rock volume of gas-bearing interval (NET_GAS, NRV_GAS). Formula: NRV = GRV \u00d7 NTG."),
    ("NetTotal", "Net rock volume of full interval (NET_TOTAL, NRV_TOTAL). Formula: NRV = GRV \u00d7 NTG."),
    ("PorvOil", "Pore volume in oil-bearing interval (PORV_OIL). Formula: PORV_OIL = NetOil \u00d7 \u03c6."),
    ("PorvGas", "Pore volume in gas-bearing interval (PORV_GAS). Formula: PORV_GAS = NetGas \u00d7 \u03c6."),
    ("PorvTotal", "Total pore volume in reservoir (PORV_TOTAL). Formula: PORV = NetTotal \u00d7 \u03c6."),
    ("HcpvOil", "Hydrocarbon pore volume in oil-bearing interval (HCPV_OIL). Formula: PORV_OIL \u00d7 Shc_OIL."),
    ("HcpvGas", "Hydrocarbon pore volume in gas-bearing interval (HCPV_GAS). Formula: PORV_GAS \u00d7 Shc_GAS."),
]


def _acl() -> Dict[str, Any]:
    return {"owners": [DEFAULT_ACL_OWNER], "viewers": [DEFAULT_ACL_VIEWER]}

def _legal(legaltag: str, countries: List[str]) -> Dict[str, Any]:
    return {"legaltags": [legaltag], "otherRelevantDataCountries": countries}

def _split(s: str) -> List[str]:
    return [x.strip() for x in s.replace(";", ",").split(",") if x.strip()]

def build_records(partition: str, legaltag: str, countries: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for code, desc in PROPERTY_SPECS:
        rec_id = f"{partition}:reference-data--ReservoirEstimatedVolumePropertyType:{code}:"
        out.append({
            "kind": KIND_RESVOL_PROP,
            "id": rec_id,
            "acl": _acl(),
            "legal": _legal(legaltag, countries),
            "data": {"Name": code, "Code": code, "Description": desc},
        })
    return out

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
    ap = argparse.ArgumentParser(description="Generate ReservoirEstimatedVolumePropertyType manifest.")
    ap.add_argument("--partition", default=os.getenv("OSDU_PARTITION", "dev"))
    ap.add_argument("--legaltag", default=DEFAULT_LEGALTAG)
    ap.add_argument("--countries", default=",".join(DEFAULT_COUNTRIES))
    ap.add_argument("--out", default=str(SCRIPT_DIR / "reftypes_revpropertytypes.json"))
    args = ap.parse_args()

    partition = (args.partition or "dev").strip() or "dev"
    countries = [c[:2].upper() for c in _split(args.countries)]

    records = build_records(partition, args.legaltag, countries)
    manifest = build_manifest(records, args.legaltag, countries)
    Path(args.out).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote: {args.out} (partition={partition})")
    print("Summary:")
    print(f"  {KIND_RESVOL_PROP} = {len(records)}")

if __name__ == "__main__":
    main()
