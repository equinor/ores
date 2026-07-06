#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest_omegas.py – Ingest the Omega Sør dataset to eqndev:
  1. Create dataspace on RDDMS
  2. Push os.epc to RDDMS (maap/omegas dataspace) via ETP
  3. Call RDDMS manifests/build API to index EPC objects in OSDU catalog
     (same API as ores admin.html "Manifest" button)
  4. Generate custom manifests (BD, risks, volumes, wells, collection)
  5. Push custom manifest records to OSDU catalog via Storage API

The EPC-derived records MUST be indexed FIRST so that the BD and
PersistedCollection can reference them (dataspace, grids, surfaces etc.).

Analogous to demo/drogonresqml/ingest_drogon.py but for the omegas dataset.

Usage:
  python demo/omegas/ingest_omegas.py                    # full pipeline
  python demo/omegas/ingest_omegas.py --skip-etp         # manifests + catalog only
  python demo/omegas/ingest_omegas.py --skip-manifest-build  # skip RDDMS manifest builder
  python demo/omegas/ingest_omegas.py --generate-only    # generate manifests, no push
  python demo/omegas/ingest_omegas.py --dry-run          # no remote changes
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent          # demo/omegas/
DEMO_DIR = SCRIPT_DIR.parent                          # demo/
REPO_ROOT = DEMO_DIR.parent                           # ores/

sys.path.insert(0, str(DEMO_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

from _auth import get_token, load_instance  # noqa: E402
from demo.eqn.omegas._shared import (  # noqa: E402
    DATASPACE, EPC_FILE, DEFAULT_ACL, DEFAULT_LEGAL,
    SPATIAL_AREA_WGS84, PROJECT_CRS_ID,
)
import re  # noqa: E402

try:
    import httpx
except ImportError:
    sys.exit("pip install httpx")

# ETP client Docker image
IMAGE_SSL = "osdu-etp-sslclient"


# ═══════════════════════════════════════════════════════════════════════════
# Instance config
# ═══════════════════════════════════════════════════════════════════════════

class InstanceConfig:
    def __init__(self, name: str = "eqndev"):
        inst = load_instance(name)
        self.name = name
        self.host = inst["host"].replace("https://", "").replace("http://", "").rstrip("/")
        self.partition = inst.get("partition") or "opendes"
        self.legal_tag = inst.get("legal_tag") or f"{self.partition}-default-legal-tag"
        owners = inst.get("owners")
        self.owners = owners if isinstance(owners, list) else [owners] if owners else DEFAULT_ACL["owners"]
        viewers = inst.get("viewers")
        self.viewers = viewers if isinstance(viewers, list) else [viewers] if viewers else DEFAULT_ACL["viewers"]
        self.countries = inst.get("countries", ["NO"])
        self.dataspace = DATASPACE
        self.base_rddms = f"https://{self.host}/api/reservoir-ddms/v2"
        self.base_storage = f"https://{self.host}/api/storage/v2"
        self.etp_url = f"wss://{self.host}/api/reservoir-ddms-etp/v2/"

    def headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "data-partition-id": self.partition,
            "Content-Type": "application/json",
        }


# ═══════════════════════════════════════════════════════════════════════════
# RDDMS record name enrichment
# ═══════════════════════════════════════════════════════════════════════════

# Map of RESQML Citation/Title → canonical OSDU name for Omega Sør objects.
# RDDMS manifest builder sets data.Name from the RESQML Citation title,
# which in RMS exports is often a generic workflow string.
# We patch them here to be searchable by "Omega Sør" and proper geo names.

_TITLE_RENAMES: Dict[str, str] = {
    # === Geo Model (IjkGrid) ===
    "GeoGrid": "Omega Sør – Geo Model (IjkGrid)",
    "Grid connection for GeoGrid": "Omega Sør – Grid Connection Set",
    # === Stratigraphy ===
    "Strati column for GeoGrid": "Omega Sør – Stratigraphic Column",
    # === Horizons (Grid2d / HorizonInterpretation) ===
    "BCU": "Omega Sør – BCU (Base Cretaceous Unconformity)",
    "Tarbert_Fm_Top": "Omega Sør – Tarbert Fm Top",
    "Tarbert_Top_Sand": "Omega Sør – Tarbert Top Sand",
    "Rannoch_Fm_Top": "Omega Sør – Rannoch Fm Top",
    "Rannoch_Fm_Base": "Omega Sør – Rannoch Fm Base",
    "Etive_Fm_Top": "Omega Sør – Etive Fm Top",
    "Ness_Fm_Top": "Omega Sør – Ness Fm Top",
    # === Fault Interpretations ===
    "ISF": "Omega Sør – ISF (Inter-Segment Fault)",
    "OmegaS_1": "Omega Sør – Fault 1",
    "OmegaS_2": "Omega Sør – Fault 2",
    "OmegaS_3": "Omega Sør – Fault 3",
    "OmegaS_4": "Omega Sør – Fault 4",
    "OmegaS_5": "Omega Sør – Fault 5",
    "OmegaS_N": "Omega Sør – Fault N (North)",
    "OmegaS_E": "Omega Sør – Fault E (East)",
    "OmegaS_S": "Omega Sør – Fault S (South)",
    "OmegaS_S_2": "Omega Sør – Fault S2 (South 2)",
    # === Wells ===
    "34_4-19_S": "Omega Sør – Well 34/4-19 S",
    "OS_Producer_R02": "Omega Sør – Producer 1 (R02)",
    "OS_injector_r05": "Omega Sør – Injector 1 (R05)",
    # === Trajectories ===
    "Imported trajectory": "Omega Sør – Well Trajectory",
    "Drilled trajectory": "Omega Sør – Drilled Trajectory",
}

# Pattern-based renames for objects matching RMS workflow names
_PATTERN_RENAMES: List[tuple] = [
    (r"ExtractedHorizon_model_for_grid", "Omega Sør – Horizon Grid2d"),
    (r"depthsurfaces_from_f2f", "Omega Sør – Depth Surface (face-to-face)"),
    (r"ExtractedFaultLines_model_for_grid", "Omega Sør – Fault Lines (grid extract)"),
    (r"FaultPoints_f2f", "Omega Sør – Fault Points (face-to-face)"),
    (r"DepthPoints_f2f", "Omega Sør – Depth Points (face-to-face)"),
    (r"filtered_horizons", "Omega Sør – Filtered Horizons (pointset)"),
    (r"faultPoints_v\d+", "Omega Sør – Fault Points"),
]

# RESQML type → description prefix (used when no specific title is known)
_KIND_DESCRIPTIONS: Dict[str, str] = {
    "IjkGridRepresentation": "Omega Sør geological model – 3D corner-point grid (Brent Group, block 34/4).",
    "Grid2dRepresentation": "Omega Sør depth surface / horizon representation.",
    "FaultInterpretation": "Omega Sør structural fault interpretation (Snorre area).",
    "HorizonInterpretation": "Omega Sør horizon interpretation (Brent Group stratigraphy).",
    "WellboreTrajectoryRepresentation": "Omega Sør wellbore trajectory (block 34/4).",
    "DeviationSurveyRepresentation": "Omega Sør deviation survey (block 34/4).",
    "PointSetRepresentation": "Omega Sør point set – structural/stratigraphic data.",
    "PolylineSetRepresentation": "Omega Sør polyline set – fault lines or boundaries.",
    "StratigraphicColumn": "Omega Sør stratigraphic column – Brent Group (Tarbert, Rannoch).",
    "ContinuousProperty": "Omega Sør reservoir property (geo model).",
    "DiscreteProperty": "Omega Sør discrete property (geo model, zone/facies).",
    "GridConnectionSetRepresentation": "Omega Sør grid connection set (fault throw connections).",
    "LocalModelCompoundCrs": "Omega Sør local model CRS (ED50/UTM31N + TVD MSL).",
    "GenericRepresentation": "Omega Sør generic representation.",
}


def _enrich_rddms_record_names(records: List[Dict[str, Any]]) -> int:
    """Patch Name, Description, SpatialArea, CRS on RDDMS-generated records.

    Returns the number of records modified.
    """
    # WPC kinds that represent spatial objects
    _SPATIAL_KINDS = {
        "StructureMap", "GenericRepresentation", "GenericBinGrid",
        "IjkGridRepresentation", "HorizonControlPoints", "HorizonInterpretation",
        "WellboreTrajectory", "WellboreMarkerSet", "WellLog",
        "PointSetRepresentation", "PolylineSetRepresentation",
        "GridConnectionSetRepresentation", "Grid2dRepresentation",
        "LocalBoundaryFeature", "SeismicBinGrid",
    }

    patched = 0
    for rec in records:
        data = rec.get("data") or {}
        current_name = data.get("Name", "")
        kind = rec.get("kind", "")

        # --- Exact title match ---
        if current_name in _TITLE_RENAMES:
            data["Name"] = _TITLE_RENAMES[current_name]
            patched += 1
        else:
            # --- Pattern match ---
            for pattern, replacement in _PATTERN_RENAMES:
                if re.search(pattern, current_name):
                    # Append original name for disambiguation if multiple matches
                    data["Name"] = f"{replacement} [{current_name}]"
                    patched += 1
                    break
            else:
                # No match — prepend "Omega Sør – " if not already present
                if current_name and "Omega" not in current_name and "OmegaS" not in current_name:
                    data["Name"] = f"Omega Sør – {current_name}"
                    patched += 1

        # --- Enrich Description if empty or generic ---
        if not data.get("Description"):
            # Extract RESQML type from kind string
            resqml_type = ""
            for rt in _KIND_DESCRIPTIONS:
                if rt.lower() in kind.lower():
                    resqml_type = rt
                    break
            if resqml_type:
                data["Description"] = _KIND_DESCRIPTIONS[resqml_type]
            else:
                data["Description"] = (
                    f"Omega Sør field development – RESQML object from geo model. "
                    f"Block 34/4, PL057, Snorre area."
                )

        # --- Enrich SpatialArea + CRS for spatial WPC records ---
        is_spatial = any(sk in kind for sk in _SPATIAL_KINDS)
        if is_spatial:
            if "SpatialArea" not in data:
                data["SpatialArea"] = SPATIAL_AREA_WGS84
            if "CoordinateReferenceSystemID" not in data:
                data["CoordinateReferenceSystemID"] = PROJECT_CRS_ID
            # Fix empty meta CRS persistableReference
            meta = rec.get("meta")
            if isinstance(meta, list):
                for m in meta:
                    if m.get("kind") == "CRS" and not m.get("persistableReference"):
                        m["persistableReference"] = (
                            '{"authCode":{"auth":"EPSG","code":"23031"},'
                            '"type":"LBC","ver":"PE_10_9_1",'
                            '"name":"ED50_UTM_Zone_31N"}'
                        )

    return patched


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline steps
# ═══════════════════════════════════════════════════════════════════════════

GENERATOR_SCRIPTS = [
    ("1. Master data (Reservoir, Wells)", "gen_master_omegas.py"),
    ("2. Volumes (REV + InPlace)", "gen_volumes_omegas.py"),
    ("3. Risks (5 categories)", "gen_risk_omegas.py"),
    ("4. Drilling (trajectories, activities, docs)", "gen_drilling_omegas.py"),
    ("5. PersistedCollection (evidence)", "gen_collection_omegas.py"),
    ("6. BusinessDecision (WPC)", "gen_businessdecision_omegas.py"),
]


def run_generators(dry_run: bool = False) -> bool:
    """Run all manifest generator scripts in order."""
    print("\n═══ Generate OSDU Manifests ═══")
    for label, script in GENERATOR_SCRIPTS:
        script_path = SCRIPT_DIR / script
        if not script_path.exists():
            print(f"  ⚠ Missing: {script}")
            continue
        print(f"\n  ── {label} ──")
        if dry_run:
            print(f"    [dry-run] Would run: {script}")
            continue
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(SCRIPT_DIR),
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"    ✗ FAILED: {result.stderr[-300:]}")
            return False
        for line in result.stdout.strip().split("\n"):
            print(f"    {line}")
    return True


def create_dataspace(token: str, cfg: InstanceConfig, dry_run: bool) -> bool:
    """Create maap/omegas dataspace on RDDMS."""
    print(f"\n═══ Create Dataspace ({cfg.dataspace}) ═══")
    if dry_run:
        print("  [dry-run] Would create dataspace")
        return True

    payload = [{
        "DataspaceId": cfg.dataspace,
        "Path": cfg.dataspace,
        "CustomData": {
            "legaltags": [cfg.legal_tag],
            "otherRelevantDataCountries": cfg.countries,
            "owners": cfg.owners,
            "viewers": cfg.viewers,
        },
    }]
    r = httpx.post(f"{cfg.base_rddms}/dataspaces", headers=cfg.headers(token),
                   json=payload, timeout=30)
    if r.status_code in (200, 201):
        print(f"  ✓ Created dataspace {cfg.dataspace}")
        return True
    if r.status_code in (400, 409):
        print(f"  ✓ Dataspace {cfg.dataspace} already exists")
        return True
    print(f"  ✗ Failed: {r.status_code} {r.text[:300]}")
    return False


def import_epc(token: str, cfg: InstanceConfig, dry_run: bool) -> bool:
    """Import os.epc via ETP into the maap/omegas dataspace."""
    print(f"\n═══ Import EPC via ETP ({EPC_FILE.name}) ═══")
    if not EPC_FILE.exists():
        print(f"  ✗ EPC file not found: {EPC_FILE}")
        return False
    if dry_run:
        print(f"  [dry-run] Would import {EPC_FILE.name} → {cfg.dataspace}")
        return True

    tok_file = SCRIPT_DIR / ".etp_token"
    tok_file.write_text(token)

    inner = (
        f"export JWT=$(cat /data/.etp_token) && "
        f"/bin/openETPServer space "
        f"--server-url {cfg.etp_url} "
        f"--data-partition-id {cfg.partition} "
        f"--auth bearer --jwt-token $JWT "
        f"-s {cfg.dataspace} "
        f"--import-epc /data/{EPC_FILE.name} -j"
    )
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{SCRIPT_DIR}:/data",
        "--entrypoint=sh", IMAGE_SSL, "-c", inner,
    ]
    print(f"  Importing {EPC_FILE.name} → {cfg.dataspace}")
    print(f"  ETP URL: {cfg.etp_url}")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    tok_file.unlink(missing_ok=True)

    combined = result.stdout + result.stderr
    if result.returncode == 0:
        print(f"  ✓ EPC imported successfully")
        return True
    if "already exist" in combined.lower():
        print(f"  ✓ Objects already exist in dataspace (re-import skipped)")
        return True
    print(f"  ✗ ETP import failed (rc={result.returncode})")
    print(f"    {combined[-400:]}")
    return False


def build_rddms_manifest(token: str, cfg: InstanceConfig, dry_run: bool) -> bool:
    """Call RDDMS manifests/build API to index EPC objects in OSDU catalog.

    This is the same API that the ores admin.html "Manifest" button calls:
      POST /api/reservoir-ddms/v2/manifests/build
      Body: {"uris": ["eml:///dataspace('maap/omegas')"], "createMissingReferences": true}

    The RDDMS service introspects the EPC content in the dataspace and generates
    OSDU WPC records (IjkGrid, Grid2d, WellboreTrajectory, FaultInterpretation,
    etc.) which are then pushed to the OSDU Storage/Search catalog.

    These records MUST be indexed before the BD/collection can reference them.
    """
    print(f"\n═══ RDDMS Manifest Builder ({cfg.dataspace}) ═══")
    print(f"  API: POST {cfg.base_rddms}/manifests/build")
    print(f"  URI: eml:///dataspace('{cfg.dataspace}')")

    if dry_run:
        print("  [dry-run] Would call manifests/build and ingest results")
        return True

    # Step A: Call manifests/build to generate OSDU records from EPC
    dataspace_uri = f"eml:///dataspace('{cfg.dataspace}')"
    body = {
        "uris": [dataspace_uri],
        "createMissingReferences": True,
    }

    print("  Building manifest from dataspace content...")
    try:
        r = httpx.post(
            f"{cfg.base_rddms}/manifests/build",
            headers=cfg.headers(token),
            json=body,
            timeout=120,
        )
    except httpx.TimeoutException:
        print("  ✗ Timeout (120s) – dataspace may have too many objects")
        print("    Try building for specific URIs instead of whole dataspace")
        return False

    if r.status_code >= 400:
        print(f"  ✗ manifests/build failed: {r.status_code}")
        print(f"    {r.text[:500]}")
        # Known issue: some RESQML types crash the builder (see keys_router.py)
        if r.status_code == 500:
            print("    Note: RDDMS manifest builder may fail on certain RESQML types.")
            print("    This is a known deficiency. Custom manifests will still be pushed.")
        return False

    manifest = r.json()
    if not manifest:
        print("  ✗ Empty response from manifests/build")
        return False

    # Count what was generated
    records = []
    for section in ("WorkProductComponents", "Datasets", "ReferenceData", "MasterData"):
        items = manifest.get(section) or manifest.get("Data", {}).get(section) or []
        if isinstance(items, list):
            records.extend(items)
            if items:
                print(f"    {section}: {len(items)} records")

    if not records:
        print("  ⚠ No records generated (dataspace may be empty or types unsupported)")
        return True

    print(f"  Total: {len(records)} EPC-derived records to index")

    # Step B: Enrich record names for searchability ("Omega Sør" + descriptive)
    n_patched = _enrich_rddms_record_names(records)
    print(f"  Enriched: {n_patched}/{len(records)} records patched with canonical names")

    # Step C: Enrich records with ACL/legal and push to Storage API
    for rec in records:
        if "acl" not in rec:
            rec["acl"] = {}
        rec["acl"]["owners"] = cfg.owners
        rec["acl"]["viewers"] = cfg.viewers
        if "legal" not in rec:
            rec["legal"] = {}
        rec["legal"]["legaltags"] = [cfg.legal_tag]
        rec["legal"]["otherRelevantDataCountries"] = cfg.countries

    # Push in batches
    batch_size = 20
    total_ok = 0
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        resp = httpx.put(
            f"{cfg.base_storage}/records",
            headers=cfg.headers(token),
            json=batch,
            timeout=60,
        )
        if resp.status_code in (200, 201):
            result_data = resp.json()
            count = result_data.get("recordCount", len(batch))
            total_ok += count
        else:
            print(f"    ✗ Batch {i // batch_size + 1} failed: {resp.status_code}")
            print(f"      {resp.text[:200]}")

    print(f"  ✓ {total_ok}/{len(records)} EPC-derived records indexed in catalog")

    # Save the RDDMS-generated manifest for reference
    out_path = SCRIPT_DIR / "manifest_rddms_omegas.json"
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"  Saved: {out_path.name}")

    return True


def push_to_catalog(token: str, cfg: InstanceConfig, dry_run: bool) -> bool:
    """Push all generated manifest records to OSDU Storage API."""
    print(f"\n═══ Push Custom Records to Catalog ═══")

    manifest_files = sorted(SCRIPT_DIR.glob("manifest_*_omegas.json"))
    if not manifest_files:
        print("  ✗ No manifest files found")
        return False

    all_records: List[Dict[str, Any]] = []
    for mf in manifest_files:
        manifest = json.loads(mf.read_text(encoding="utf-8"))
        # Collect master-data records
        for md in manifest.get("MasterData", []):
            all_records.append(md)
        # Collect WPCs
        data = manifest.get("Data", {})
        for wpc in data.get("WorkProductComponents", []):
            all_records.append(wpc)
        for wp in data.get("WorkProducts", []):
            all_records.append(wp)

    print(f"  Found {len(all_records)} records from {len(manifest_files)} manifests")

    if dry_run:
        print("  [dry-run] Would push records to Storage API")
        for r in all_records:
            print(f"    {r.get('kind', '?')}: {r.get('id', '?')}")
        return True

    # Push in batches of 20
    batch_size = 20
    total_ok = 0
    for i in range(0, len(all_records), batch_size):
        batch = all_records[i:i + batch_size]
        r = httpx.put(
            f"{cfg.base_storage}/records",
            headers=cfg.headers(token),
            json=batch,
            timeout=60,
        )
        if r.status_code in (200, 201):
            result = r.json()
            count = result.get("recordCount", len(batch))
            total_ok += count
            print(f"  ✓ Batch {i // batch_size + 1}: {count} records ingested")
        else:
            print(f"  ✗ Batch {i // batch_size + 1} failed: {r.status_code}")
            print(f"    {r.text[:300]}")
            # Continue with other batches

    print(f"\n  Total: {total_ok}/{len(all_records)} records ingested to catalog")
    return total_ok > 0


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="Ingest Omega Sør to eqndev (RDDMS + catalog)")
    ap.add_argument("instance", nargs="?", default="eqndev", help="Target instance")
    ap.add_argument("--skip-etp", action="store_true", help="Skip EPC import to RDDMS")
    ap.add_argument("--skip-manifest-build", action="store_true", help="Skip RDDMS manifest builder")
    ap.add_argument("--generate-only", action="store_true", help="Only generate manifests")
    ap.add_argument("--dry-run", action="store_true", help="No remote changes")
    args = ap.parse_args()

    print(f"╔═══════════════════════════════════════════════╗")
    print(f"║  Omega Sør → {args.instance} ingestion pipeline  ║")
    print(f"╚═══════════════════════════════════════════════╝")

    # Step 1: Authenticate
    print(f"\n═══ Authenticate ({args.instance}) ═══")
    if args.dry_run or args.generate_only:
        token = "DRY_RUN_TOKEN"
        if args.dry_run:
            print("  [dry-run] Skipping auth")
    else:
        token = get_token(args.instance, verbose=True)
        if not token:
            sys.exit(f"Failed to authenticate to {args.instance}")

    cfg = InstanceConfig(args.instance)

    # Step 2: RDDMS – create dataspace + import EPC via ETP
    if not args.skip_etp and not args.generate_only:
        create_dataspace(token, cfg, args.dry_run)
        import_epc(token, cfg, args.dry_run)
    else:
        print("\n  [skip-etp] Skipping RDDMS import")

    # Step 3: RDDMS manifest builder – index EPC objects in catalog FIRST
    # This must happen BEFORE custom manifests so that BD/collection can
    # reference the EPC-derived records (dataspace, grids, surfaces, etc.)
    # Uses same API as ores admin.html "Manifest" button:
    #   POST /api/reservoir-ddms/v2/manifests/build
    if not args.skip_manifest_build and not args.generate_only:
        build_rddms_manifest(token, cfg, args.dry_run)
    else:
        print("\n  [skip] Skipping RDDMS manifest builder")

    # Step 4: Generate custom manifests (BD, risks, volumes, wells, collection)
    if not run_generators(dry_run=args.dry_run):
        sys.exit("Manifest generation failed")

    if args.generate_only:
        print("\n✓ Manifests generated. Use --skip-etp to push catalog only.")
        return

    # Step 5: Push custom records to catalog
    push_to_catalog(token, cfg, args.dry_run)

    print("\n═══ Done ═══")


if __name__ == "__main__":
    main()
