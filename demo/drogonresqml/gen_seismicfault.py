#!/usr/bin/env python3
"""
gen_seismicfault.py – Generate SeismicFault:2.0.0 WPC records for the Drogon demo.

Creates one SeismicFault record per fault (F1-F6), each linking to the existing
FaultInterpretation and the seismic geometry context (BinGrid, SeismicTraceData).

The SeismicFault record is a REPRESENTATION (inherits AbstractRepresentation),
acting as the seismic-domain view of a fault - analogous to SeismicHorizon for
horizons. The GenericRepresentation records remain as the RESQML-native pointers;
SeismicFault adds the seismic interpretation context.

Relationships (outgoing):
  SeismicFault → FaultInterpretation       via InterpretationID
  SeismicFault → SeismicBinGrid            via BinGridID
  SeismicFault → SeismicTraceData[]        via SeismicTraceDataIDs
  SeismicFault → LocalModelCompoundCrs     via LocalModelCompoundCrsID
  SeismicFault → LocalBoundaryFeature      via ancestry.parents[]

Usage:
  python demo/drogonresqml/gen_seismicfault.py --target eqndev
  python demo/drogonresqml/gen_seismicfault.py --target interop
  python demo/drogonresqml/gen_seismicfault.py --target eqndev --ingest
  python demo/drogonresqml/gen_seismicfault.py --target eqndev --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "seismicfault_config.json"

# ── Instance configurations (loaded from k8s configmap) ───────────────────
DEMO_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(DEMO_DIR))


def _load_instance(name: str) -> dict:
    """Load instance settings from k8s configmap via demo/_auth."""
    from _auth import load_instance  # noqa: E402
    inst = load_instance(name)
    partition = inst.get("partition", "opendes")
    owners = inst.get("owners")
    if isinstance(owners, str):
        owners = [owners]
    elif not owners:
        owners = [f"data.default.owners@{partition}.dataservices.energy"]
    viewers = inst.get("viewers")
    if isinstance(viewers, str):
        viewers = [viewers]
    elif not viewers:
        viewers = [f"data.default.viewers@{partition}.dataservices.energy"]
    countries = inst.get("countries")
    if isinstance(countries, str):
        countries = [countries]
    elif not countries:
        countries = ["NO"]
    return {
        "partition": partition,
        "owners": owners,
        "viewers": viewers,
        "legal_tag": inst.get("legal_tag", f"{partition}-default-legal-tag"),
        "countries": countries,
        "host": inst.get("host", ""),
    }


def generate_seismicfault_id(partition: str, fault_uuid: str) -> str:
    """Generate a deterministic SeismicFault id from the FaultInterpretation UUID.

    We derive it by hashing (uuid5) the FaultInterpretation UUID within a
    well-known namespace so the same fault always maps to the same SeismicFault id.
    """
    ns = uuid.UUID("a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d")  # fixed namespace
    sf_uuid = uuid.uuid5(ns, f"SeismicFault:{fault_uuid}")
    return f"{partition}:work-product-component--SeismicFault:2.0.0:{sf_uuid}"


def build_record(fault: dict, cfg: dict, inst: dict) -> dict:
    """Build a single SeismicFault:2.0.0 record."""
    partition = inst["partition"]
    defaults = cfg["defaults"]
    refs = cfg["references"]

    fi_uuid = fault["fault_interpretation_uuid"]
    sf_id = generate_seismicfault_id(partition, fi_uuid)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    # DDMSDatasets: point to the first PolylineSetRepresentation (primary sticks)
    ddms_datasets = []
    for ps_uuid in fault.get("polyline_set_uuids", []):
        ddms_datasets.append(
            f"eml://reservoir-ddms1/dataspace('{defaults['dataspace']}')"
            f"/resqml20.obj_PolylineSetRepresentation({ps_uuid})"
        )

    # Ancestry: FaultInterpretation + LocalBoundaryFeature
    fi_id = f"{partition}:work-product-component--FaultInterpretation:1.3.0:{fi_uuid}:"
    feat_id = f"{partition}:master-data--LocalBoundaryFeature:1.1.0:{fault['boundary_feature_uuid']}:"

    record = {
        "id": sf_id,
        "kind": cfg["schema"]["kind"],
        "acl": {
            "owners": inst["owners"],
            "viewers": inst["viewers"],
        },
        "legal": {
            "legaltags": [inst["legal_tag"]],
            "otherRelevantDataCountries": inst["countries"],
            "status": "compliant",
        },
        "createTime": now,
        "modifyTime": now,
        "createUser": "Drogon Demo (Equinor)",
        "modifyUser": "Drogon Demo (Equinor)",
        "version": 1,
        "ancestry": {
            "parents": [
                f"{fi_id}1",
                f"{feat_id}1",
            ]
        },
        "data": {
            "Name": fault["name"],
            "Description": fault["description"],
            "ExistenceKind": defaults["existence_kind"],

            # AbstractWPCGroupType
            "DDMSDatasets": ddms_datasets,
            "DatasetIDs": [refs["dataset_id"].format(partition=partition)],

            # AbstractRepresentation
            "InterpretationID": fi_id,
            "InterpretationName": fault["name"],
            "LocalModelCompoundCrsID": refs["local_crs_id"].format(partition=partition),

            # SeismicFault individual properties
            "RepresentationRole": defaults["representation_role"],
            "RepresentationType": defaults["representation_type"],
            "DomainTypeID": defaults["domain_type"],
            "Interpreter": defaults["interpreter"],
            "SeismicPickingTypeID": defaults["picking_type"],
            "BinGridID": refs["seismic_bin_grid_id"].format(partition=partition),
            "SeismicTraceDataIDs": [
                sid.format(partition=partition) for sid in refs["seismic_trace_data_ids"]
            ],

            # Spatial
            "SpatialArea": cfg["spatial_area"],
        },
    }
    return record


def build_manifest(cfg: dict, inst: dict, skip_ancestry: bool = False) -> dict:
    """Build a complete OSDU manifest with all SeismicFault records."""
    records = []
    for fault in cfg["faults"]:
        rec = build_record(fault, cfg, inst)
        if skip_ancestry:
            rec.pop("ancestry", None)
        records.append(rec)

    return {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "Datasets": [],
            "WorkProductComponents": records,
        },
    }


def ingest_records(manifest: dict, target: str) -> None:
    """Push records to OSDU Storage API."""
    sys.path.insert(0, str(SCRIPT_DIR.parent))
    from _auth import get_token, load_instance  # noqa: E402

    inst_cfg = load_instance(target)
    token = get_token(target)
    if not token:
        sys.exit(f"Failed to authenticate to {target}")

    host = inst_cfg["host"].rstrip("/")
    partition = inst_cfg.get("partition", "opendes")

    try:
        import httpx
    except ImportError:
        sys.exit("pip install httpx")

    headers = {
        "Authorization": f"Bearer {token}",
        "data-partition-id": partition,
        "Content-Type": "application/json",
    }

    records = manifest["Data"]["WorkProductComponents"]
    url = f"{host}/api/storage/v2/records"

    print(f"\n=== Ingesting {len(records)} SeismicFault records to {target} ===")
    with httpx.Client(timeout=60) as client:
        resp = client.put(url, headers=headers, json=records)
        if resp.status_code in (200, 201):
            result = resp.json()
            created = result.get("recordCount", len(result.get("recordIds", [])))
            print(f"  OK: {created} records created/updated")
            for rid in result.get("recordIds", []):
                print(f"    {rid}")
        else:
            print(f"  FAILED: {resp.status_code}")
            print(f"  {resp.text[:500]}")
            # Fallback: try one-by-one
            print("  Trying sequential fallback...")
            ok = 0
            for rec in records:
                r2 = client.put(url, headers=headers, json=[rec])
                if r2.status_code in (200, 201):
                    ok += 1
                    print(f"    OK: {rec['data']['Name']}")
                else:
                    print(f"    FAIL: {rec['data']['Name']} - {r2.status_code}: {r2.text[:200]}")
            print(f"  Sequential: {ok}/{len(records)} succeeded")


def main():
    ap = argparse.ArgumentParser(description="Generate SeismicFault:2.0.0 WPC records for Drogon")
    ap.add_argument("--target", default="eqndev",
                    help="Target instance name from k8s config (default: eqndev)")
    ap.add_argument("--config", type=Path, default=CONFIG_FILE,
                    help="Config JSON path")
    ap.add_argument("--output", type=Path, default=None,
                    help="Output manifest path (auto-generated if not specified)")
    ap.add_argument("--ingest", action="store_true",
                    help="Push records to OSDU after generation")
    ap.add_argument("--no-ancestry", action="store_true",
                    help="Omit ancestry.parents (avoid 404 if parents not ingested)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Generate and print, don't save or ingest")
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)

    inst = _load_instance(args.target)
    manifest = build_manifest(cfg, inst, skip_ancestry=args.no_ancestry)
    n = len(manifest["Data"]["WorkProductComponents"])

    if args.dry_run:
        print(json.dumps(manifest, indent=2))
        print(f"\n--- {n} SeismicFault records generated (dry-run) ---")
        return

    # Determine output path
    out_path = args.output or (SCRIPT_DIR / f"manifest_seismicfault_{args.target}.json")
    with open(out_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote {n} SeismicFault records to {out_path}")

    # Relationship summary
    print("\n=== Relationship Summary ===")
    print(f"  SeismicFault:2.0.0 → FaultInterpretation:1.3.0   (InterpretationID)")
    print(f"  SeismicFault:2.0.0 → SeismicBinGrid              (BinGridID)")
    print(f"  SeismicFault:2.0.0 → SeismicTraceData × 2        (SeismicTraceDataIDs)")
    print(f"  SeismicFault:2.0.0 → LocalModelCompoundCrs       (LocalModelCompoundCrsID)")
    print(f"  SeismicFault:2.0.0 → LocalBoundaryFeature        (ancestry.parents)")
    print(f"  GenericRepresentation (existing) ↔ same FaultInterpretation (parallel)")

    if args.ingest:
        ingest_records(manifest, args.target)


if __name__ == "__main__":
    main()
