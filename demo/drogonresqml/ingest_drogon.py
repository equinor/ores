#!/usr/bin/env python3
"""
ingest_drogon.py – Ingest the curated Drogon demo EPC into any OSDU instance
and push the comprehensive OSDU manifest.

Supports:  interop, eqndev  (any instance configured in k8s/configmap.yaml)

Steps:
  1. Authenticate (reads auth mode from instance config)
  2. Create dataspace demo/drogon on target RDDMS
  3. Upload EPC (+H5 arrays) via REST or import EPC via Docker ETP CLI
  4. Verify import via REST
  5. Build/load OSDU manifest (comprehensive, from EPC)
  6. Patch manifest with target instance ACLs/partition
  7. Push to OSDU catalog (Workflow or Storage API)

Usage:
  python demo/drogonresqml/ingest_drogon.py interop              # legacy Docker CLI (no arrays)
  python demo/drogonresqml/ingest_drogon.py interop --rest-upload # REST EPC+H5 (with arrays!)
  python demo/drogonresqml/ingest_drogon.py interop --rest-upload --local  # via localhost:8080
  python demo/drogonresqml/ingest_drogon.py interop --rest-upload --validate --auto-ingest records
  python demo/drogonresqml/ingest_drogon.py eqndev --skip-etp    # manifest only
  python demo/drogonresqml/ingest_drogon.py eqndev --dry-run     # no remote changes
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

try:
    import httpx
except ImportError:
    sys.exit("pip install httpx")

# ── Paths ─────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent          # demo/drogonresqml/
DEMO_DIR = SCRIPT_DIR.parent                          # demo/
sys.path.insert(0, str(DEMO_DIR))

from _auth import get_token, load_instance  # noqa: E402

# ── Constants ─────────────────────────────────────────────────────────────
DATASPACE_DEFAULT = "maap/drogon"
DATASPACE_OVERRIDE = {}
EPC_FILE = SCRIPT_DIR / "drogon.epc"
H5_FILE = SCRIPT_DIR / "drogon.h5"
IMAGE_SSL = "osdu-etp-sslclient"

# Drogon project CRS: WGS84 / UTM zone 37N (EPSG:32637) – synthetic model
# Grid: origin (456064, 5926551), 572×645 nodes at 20m
# WGS84 bounding box (computed via pyproj from UTM extent)
DROGON_CRS_ID = "reference-data--CoordinateReferenceSystem:BoundCRS.SLB.32637.15851:"
DROGON_SPATIAL_AREA_WGS84 = {
    "Wgs84Coordinates": {
        "type": "Polygon",
        "coordinates": [[[38.3360, 53.4861], [38.5102, 53.4869],
                         [38.5089, 53.6029], [38.3360, 53.6020],
                         [38.3360, 53.4861]]]
    }
}
DROGON_CRS_META = {
    "kind": "CRS",
    "name": "WGS 84 / UTM zone 37N",
    "persistableReference": (
        '{"authCode":{"auth":"EPSG","code":"32637"},'
        '"type":"LBC","ver":"PE_10_9_1",'
        '"name":"WGS_1984_UTM_Zone_37N",'
        '"wkt":"PROJCS[\\"WGS_1984_UTM_Zone_37N\\",'
        'GEOGCS[\\"GCS_WGS_1984\\",DATUM[\\"D_WGS_1984\\",'
        'SPHEROID[\\"WGS_1984\\",6378137.0,298.257223563]],'
        'PRIMEM[\\"Greenwich\\",0.0],'
        'UNIT[\\"Degree\\",0.0174532925199433]],'
        'PROJECTION[\\"Transverse_Mercator\\"],'
        'PARAMETER[\\"False_Easting\\",500000.0],'
        'PARAMETER[\\"False_Northing\\",0.0],'
        'PARAMETER[\\"Central_Meridian\\",39.0],'
        'PARAMETER[\\"Scale_Factor\\",0.9996],'
        'PARAMETER[\\"Latitude_Of_Origin\\",0.0],'
        'UNIT[\\"Meter\\",1.0]]"}'
    ),
}


# ═══════════════════════════════════════════════════════════════════════════
# Instance config loader
# ═══════════════════════════════════════════════════════════════════════════

class InstanceConfig:
    """Loads all instance-specific settings from configmap/env."""

    def __init__(self, name: str):
        self.name = name
        inst = load_instance(name)
        self.host = inst["host"].replace("https://", "").replace("http://", "").rstrip("/")
        self.partition = inst.get("partition") or "opendes"
        self.legal_tag = inst.get("legal_tag") or f"{self.partition}-default-legal-tag"
        owners = inst.get("owners")
        self.owners = owners if isinstance(owners, list) else [owners] if owners else [f"data.default.owners@{self.partition}.dataservices.energy"]
        viewers = inst.get("viewers")
        self.viewers = viewers if isinstance(viewers, list) else [viewers] if viewers else [f"data.default.viewers@{self.partition}.dataservices.energy"]
        countries = inst.get("countries")
        self.countries = countries if isinstance(countries, list) else [countries] if countries else ["NO"]
        self.dataspace = DATASPACE_OVERRIDE.get(name, DATASPACE_DEFAULT)
        self.base_rddms = f"https://{self.host}/api/reservoir-ddms/v2"
        self.base_osdu = f"https://{self.host}"
        self.etp_url = f"wss://{self.host}/api/reservoir-ddms-etp/v2/"

    def headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "data-partition-id": self.partition,
            "Content-Type": "application/json",
        }

    def __repr__(self):
        return (f"InstanceConfig({self.name}: {self.host}, "
                f"partition={self.partition}, legal={self.legal_tag})")


# ═══════════════════════════════════════════════════════════════════════════
# 1. Auth
# ═══════════════════════════════════════════════════════════════════════════

def authenticate(cfg: InstanceConfig) -> str:
    """Get access token for the target instance."""
    print(f"=== 1. Authenticate ({cfg.name}) ===")
    token = get_token(cfg.name, verbose=True)
    if not token:
        sys.exit(f"Failed to get access token for {cfg.name}")
    return token


# ═══════════════════════════════════════════════════════════════════════════
# 2. Create dataspace
# ═══════════════════════════════════════════════════════════════════════════

def create_dataspace(token: str, cfg: InstanceConfig) -> bool:
    """Create demo/drogon dataspace on remote RDDMS via REST."""
    print(f"\n=== 2. Create dataspace ({cfg.dataspace}) ===")
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
        print(f"  ✓ Dataspace {cfg.dataspace} already exists ({r.status_code})")
        return True
    if r.status_code in (401, 403):
        print(f"  ⚠ REST create failed ({r.status_code}), trying ETP...")
        return create_dataspace_etp(token, cfg)
    print(f"  ✗ Failed: {r.status_code} {r.text[:300]}")
    return False


def create_dataspace_etp(token: str, cfg: InstanceConfig) -> bool:
    """Create dataspace via ETP client (fallback)."""
    xdata = json.dumps({
        "legaltags": [cfg.legal_tag],
        "otherRelevantDataCountries": cfg.countries,
        "owners": cfg.owners,
        "viewers": cfg.viewers,
    })

    tok_file = SCRIPT_DIR / ".etp_token"
    tok_file.write_text(token)

    inner = (
        f"export JWT=$(cat /data/.etp_token) && "
        f"/bin/openETPServer space "
        f"--server-url {cfg.etp_url} "
        f"--data-partition-id {cfg.partition} "
        f"--auth bearer --jwt-token $JWT "
        f"--new -s {cfg.dataspace} "
        f"--xdata '{xdata}'"
    )
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{SCRIPT_DIR}:/data",
        "--entrypoint=sh", IMAGE_SSL, "-c", inner,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    tok_file.unlink(missing_ok=True)

    combined = result.stdout + result.stderr
    if result.returncode == 0:
        print(f"  ✓ Created dataspace {cfg.dataspace} via ETP")
        return True
    if "already exist" in combined.lower():
        print(f"  ✓ Dataspace {cfg.dataspace} already exists")
        return True
    print(f"  ✗ ETP create failed (rc={result.returncode})")
    print(f"    {combined[-300:]}")
    return False


# ═══════════════════════════════════════════════════════════════════════════
# 3. Import EPC via ETP
# ═══════════════════════════════════════════════════════════════════════════

def import_epc(token: str, cfg: InstanceConfig) -> bool:
    """Import drogon.epc into the target RDDMS via ETP (Docker CLI, no H5)."""
    print(f"\n=== 3. Import EPC via ETP (legacy, no arrays) ===")

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
    result = subprocess.run(cmd, text=True, timeout=600)
    tok_file.unlink(missing_ok=True)

    if result.returncode == 0:
        print(f"  ✓ EPC import succeeded")
        return True
    print(f"  ✗ EPC import failed (rc={result.returncode})")
    return False


def upload_epc_rest(
    token: str,
    cfg: InstanceConfig,
    *,
    validate: str = "false",
    auto_ingest: str | None = None,
    local: bool = False,
) -> bool:
    """Upload EPC+H5 via the REST multipart upload route.

    This uploads both drogon.epc and drogon.h5 so that array data
    (statistics, property values) is stored in the ETP server.

    Args:
        validate: "false", "true", or "strict"
        auto_ingest: None, "records", or "workflow"
        local: use localhost:8080 instead of remote RDDMS
    """
    print(f"\n=== 3. Upload EPC+H5 via REST ===")

    if not EPC_FILE.exists():
        print(f"  ✗ EPC file not found: {EPC_FILE}")
        return False

    ds_enc = cfg.dataspace.replace("/", "%2F")
    base = "http://localhost:8080/api/reservoir-ddms/v2" if local else cfg.base_rddms
    url = f"{base}/dataspaces/{ds_enc}/epc/upload"

    params: dict[str, str] = {}
    if validate != "false":
        params["validate"] = validate
    if auto_ingest:
        params["autoIngest"] = auto_ingest

    files: list[tuple[str, tuple[str, ...]]] = [
        ("epc", (EPC_FILE.name, open(EPC_FILE, "rb"),
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
    ]
    if H5_FILE.exists():
        h5_size_mb = H5_FILE.stat().st_size / 1024 / 1024
        print(f"  H5 file: {H5_FILE.name} ({h5_size_mb:.1f} MB)")
        files.append(
            ("h5", (H5_FILE.name, open(H5_FILE, "rb"), "application/x-hdf5"))
        )
    else:
        print(f"  ⚠ No H5 file found at {H5_FILE} — uploading EPC only (no arrays)")

    headers = {
        "Authorization": f"Bearer {token}",
        "data-partition-id": cfg.partition,
    }

    print(f"  Uploading {EPC_FILE.name}" + (f" + {H5_FILE.name}" if H5_FILE.exists() else ""))
    print(f"  → {url}")
    if params:
        print(f"  Params: {params}")

    try:
        r = httpx.post(
            url, headers=headers, files=files, params=params,
            timeout=httpx.Timeout(600.0, connect=30.0),
        )
    finally:
        for _, (_, fobj, _) in files:
            fobj.close()

    if r.is_success:
        body = r.json()
        obj_count = body.get("objectsStored", "?")
        arr_count = body.get("arraysStored", "?")
        print(f"  ✓ Upload succeeded: {obj_count} objects, {arr_count} arrays")
        h5_size = body.get("h5DataSize", 0)
        if isinstance(h5_size, (int, float)) and h5_size:
            print(f"    H5 data transferred: {h5_size / 1024 / 1024:.1f} MB")
        warnings = body.get("warnings", [])
        if warnings:
            print(f"    ⚠ {len(warnings)} warning(s):")
            for w in warnings[:10]:
                print(f"      [{w.get('phase','')}] {w.get('message','')}")
        validation = body.get("validation")
        if validation:
            errs = validation.get("errors", [])
            warns = validation.get("warnings", [])
            print(f"    Validation: {len(errs)} error(s), {len(warns)} warning(s)")
            for e in errs[:5]:
                print(f"      ✗ {e}")
        auto = body.get("autoIngest")
        if auto:
            print(f"    Auto-ingest: {auto}")
        return True
    else:
        print(f"  ✗ Upload failed: {r.status_code}")
        try:
            print(f"    {r.json()}")
        except Exception:
            print(f"    {r.text[:500]}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# 4. Verify import
# ═══════════════════════════════════════════════════════════════════════════

def verify_import(token: str, cfg: InstanceConfig) -> bool:
    """Check resources in the remote dataspace."""
    print(f"\n=== 4. Verify import ===")
    ds_enc = cfg.dataspace.replace("/", "%2F")
    r = httpx.get(f"{cfg.base_rddms}/dataspaces/{ds_enc}/resources",
                  headers=cfg.headers(token), timeout=30)
    if not r.is_success:
        print(f"  ⚠ Could not verify: {r.status_code} {r.text[:200]}")
        return False
    resources = r.json()
    if isinstance(resources, list):
        total = sum(t.get("count", 0) for t in resources)
        print(f"  ✓ {total} objects across {len(resources)} types")
        for t in resources:
            print(f"    {t.get('name', '?')}: {t.get('count', '?')}")
    else:
        print(f"  Response: {json.dumps(resources)[:300]}")
    return True


# ═══════════════════════════════════════════════════════════════════════════
# 5. Build / load manifest
# ═══════════════════════════════════════════════════════════════════════════

def load_manifest(cfg: InstanceConfig) -> dict:
    """Load the pre-built comprehensive manifest and re-partition it."""
    print(f"\n=== 5. Load manifest ===")
    # Try instance-specific first, then generic opendes base
    candidates = [
        SCRIPT_DIR / f"manifest_full_{cfg.partition}.json",
        SCRIPT_DIR / f"manifest_full_{cfg.name}.json",
        SCRIPT_DIR / "manifest_full_opendes.json",
    ]
    src = None
    for c in candidates:
        if c.exists():
            src = c
            break
    if not src:
        print(f"  ⚠ No pre-built manifest found, running build_full_manifest.py...")
        subprocess.run([sys.executable, str(SCRIPT_DIR / "build_full_manifest.py")],
                       check=True)
        src = candidates[0] if candidates[0].exists() else candidates[-1]
    manifest = json.loads(src.read_text())
    data = manifest.get("Data", {})
    total = sum(len(v) for v in data.values() if isinstance(v, list))
    print(f"  Loaded {total} records from {src.name}")

    # Re-partition IDs and ACLs for target instance
    manifest = _repartition(manifest, cfg)
    return manifest


def _repartition(manifest: dict, cfg: InstanceConfig) -> dict:
    """Replace partition prefix and dataspace in all record IDs and cross-references."""
    old_partition = "opendes"  # base manifest uses opendes
    old_dataspace = "maap/drogon"  # base manifest uses maap/drogon

    need_partition = cfg.partition != old_partition
    need_dataspace = cfg.dataspace != old_dataspace

    if not need_partition and not need_dataspace:
        return manifest  # no change needed

    def _replace(obj):
        """Recursively replace partition and dataspace in string values."""
        if isinstance(obj, str):
            s = obj
            if need_partition:
                s = s.replace(f"{old_partition}:", f"{cfg.partition}:")
            if need_dataspace:
                s = s.replace(old_dataspace, cfg.dataspace)
            return s
        if isinstance(obj, list):
            return [_replace(v) for v in obj]
        if isinstance(obj, dict):
            return {k: _replace(v) for k, v in obj.items()}
        return obj

    manifest = _replace(manifest)
    return manifest


def build_manifest_remote(token: str, cfg: InstanceConfig) -> dict:
    """Call POST /manifests/build on the remote RDDMS (after EPC import)."""
    print(f"\n=== 5. Build manifest (remote) ===")
    url = f"{cfg.base_rddms}/manifests/build"
    body = {
        "uris": [f"eml:///dataspace('{cfg.dataspace}')"],
        "createMissingReferences": True,
    }
    print(f"  POST {url}")
    r = httpx.post(url, json=body, headers=cfg.headers(token), timeout=120)
    if r.status_code >= 300:
        print(f"  FAIL {r.status_code}: {r.text[:500]}")
        sys.exit(1)

    manifest = r.json()
    data = manifest.get("Data", {})
    counts = {k: len(v) for k, v in data.items() if isinstance(v, list)}
    print(f"  ✓ {counts}")
    return manifest


# ═══════════════════════════════════════════════════════════════════════════
# 6. Patch manifest for target instance
# ═══════════════════════════════════════════════════════════════════════════

def patch_manifest(manifest: dict, cfg: InstanceConfig) -> dict:
    """Patch all records with target instance ACLs and legal tags."""
    print(f"\n=== 6. Patch manifest ({cfg.name}) ===")
    data = manifest.get("Data", {})

    patched = 0
    for section in data.values():
        if not isinstance(section, list):
            continue
        for rec in section:
            rec["acl"] = {"owners": cfg.owners, "viewers": cfg.viewers}
            rec["legal"] = {
                "legaltags": [cfg.legal_tag],
                "otherRelevantDataCountries": cfg.countries,
                "status": "compliant",
            }
            patched += 1

    print(f"  Patched {patched} records → partition={cfg.partition}, legal={cfg.legal_tag}")
    return manifest


# ═══════════════════════════════════════════════════════════════════════════
# 6b. Enrich manifest with CRS + spatial (for bounding-box search)
# ═══════════════════════════════════════════════════════════════════════════

# WPC kinds that represent spatial objects (grids, surfaces, trajectories)
_SPATIAL_KINDS = frozenset([
    "StructureMap", "GenericRepresentation", "GenericBinGrid",
    "IjkGridRepresentation", "HorizonControlPoints", "HorizonInterpretation",
    "SeismicBinGrid", "SeismicHorizon", "SeismicTraceData",
    "WellboreTrajectory", "WellboreMarkerSet", "WellLog",
    "PointSetRepresentation", "PolylineSetRepresentation",
    "GridConnectionSetRepresentation", "Grid2dRepresentation",
    "LocalBoundaryFeature",
])


def enrich_spatial(manifest: dict, cfg: InstanceConfig) -> dict:
    """Add SpatialArea + CRS metadata to WPC records for bounding-box search.

    The RDDMS manifest builder generates records without spatial metadata.
    This post-processing step adds the Drogon project WGS84 bounding box
    and fills the empty CRS persistableReference so that OSDU ingestion
    can index the records for spatial queries.
    """
    print(f"\n=== 6b. Enrich spatial metadata ===")
    data = manifest.get("Data", {})
    patched = 0

    crs_ref_id = f"{cfg.partition}:{DROGON_CRS_ID}"

    for section in data.values():
        if not isinstance(section, list):
            continue
        for rec in section:
            kind = rec.get("kind", "")
            rec_data = rec.get("data")
            if not rec_data:
                continue

            # Determine if this is a spatial WPC
            is_spatial = any(sk in kind for sk in _SPATIAL_KINDS)
            if not is_spatial:
                continue

            # Add SpatialArea if missing
            if "SpatialArea" not in rec_data:
                rec_data["SpatialArea"] = DROGON_SPATIAL_AREA_WGS84
                patched += 1

            # Add/fix CRS reference if missing or only internal
            if "CoordinateReferenceSystemID" not in rec_data:
                rec_data["CoordinateReferenceSystemID"] = crs_ref_id

            # Fix empty meta CRS persistableReference
            meta = rec.get("meta")
            if isinstance(meta, list):
                for m in meta:
                    if m.get("kind") == "CRS" and not m.get("persistableReference"):
                        m["persistableReference"] = DROGON_CRS_META["persistableReference"]
            elif meta is None:
                rec["meta"] = [DROGON_CRS_META]

    print(f"  ✓ {patched} records enriched with SpatialArea (WGS84 bbox)")
    print(f"    CRS: {DROGON_CRS_ID}")
    return manifest


# ═══════════════════════════════════════════════════════════════════════════
# 7. Save / Push
# ═══════════════════════════════════════════════════════════════════════════

def save_manifest(manifest: dict, cfg: InstanceConfig, output: Path | None = None) -> Path:
    """Save manifest to disk."""
    out = output or SCRIPT_DIR / f"manifest_drogon_{cfg.name}.json"
    out.write_text(json.dumps(manifest, indent=2))
    size_kb = out.stat().st_size / 1024
    print(f"\n  Saved: {out.name} ({size_kb:.0f} KB)")
    return out


def push_via_storage(token: str, cfg: InstanceConfig, manifest: dict) -> bool:
    """Push records via Storage API PUT /records."""
    url = f"{cfg.base_osdu}/api/storage/v2/records"
    hdrs = cfg.headers(token)

    records: list[dict] = []
    for section in manifest.get("Data", {}).values():
        if isinstance(section, list):
            records.extend(section)

    BATCH = 100
    ok = 0
    fail = 0
    for i in range(0, len(records), BATCH):
        batch = records[i:i + BATCH]
        print(f"  PUT batch {i // BATCH + 1} ({len(batch)} records)...")
        r = httpx.put(url, headers=hdrs, json=batch, timeout=120)
        if r.is_success:
            cnt = r.json().get("recordCount", len(batch))
            ok += cnt
            print(f"    ✓ {cnt} stored")
        else:
            fail += len(batch)
            print(f"    ✗ {r.status_code}: {r.text[:200]}")

    print(f"  Results: {ok} stored, {fail} failed")
    return fail == 0


def push_via_workflow(token: str, cfg: InstanceConfig, manifest: dict) -> bool:
    """Push manifest via Workflow API (Osdu_ingest)."""
    url = f"{cfg.base_osdu}/api/workflow/v1/workflow/Osdu_ingest/workflowRun"
    hdrs = cfg.headers(token)
    body = {
        "executionContext": {
            "manifest": manifest,
            "Payload": {
                "data-partition-id": cfg.partition,
                "AppKey": "ores-drogon-ingest",
            },
        },
    }
    print(f"  POST {url}")
    r = httpx.post(url, headers=hdrs, json=body, timeout=60)
    if r.status_code not in (200, 201, 202):
        print(f"  FAIL {r.status_code}: {r.text[:300]}")
        return False

    run_id = r.json().get("runId", "?")
    print(f"  Workflow run: {run_id}")
    status = _poll_workflow(token, cfg, run_id)
    print(f"  Final status: {status}")
    return status in ("completed", "succeeded", "finished")


def _poll_workflow(token: str, cfg: InstanceConfig, run_id: str,
                   timeout: int = 300, interval: int = 5) -> str:
    """Poll workflow run until terminal state or timeout."""
    url = f"{cfg.base_osdu}/api/workflow/v1/workflow/Osdu_ingest/workflowRun/{run_id}"
    hdrs = cfg.headers(token)
    deadline = time.time() + timeout

    while time.time() < deadline:
        time.sleep(interval)
        try:
            r = httpx.get(url, headers=hdrs, timeout=30)
            if not r.is_success:
                continue
            status = r.json().get("status", "unknown").lower()
            if status in ("completed", "succeeded", "failed", "error",
                          "cancelled", "finished"):
                return status
            print(f"    poll: {status}...")
        except Exception:
            continue
    return "timeout"


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="Ingest Drogon demo EPC into an OSDU instance")
    ap.add_argument("instance", choices=["interop", "eqndev", "preship"],
                    help="Target OSDU instance name")
    ap.add_argument("--skip-etp", action="store_true",
                    help="Skip ETP import (manifest only)")
    ap.add_argument("--rest-upload", action="store_true",
                    help="Use REST multipart upload (EPC+H5) instead of Docker ETP CLI")
    ap.add_argument("--local", action="store_true",
                    help="Use localhost:8080 etp-client instead of remote RDDMS")
    ap.add_argument("--validate", nargs="?", const="true", default="false",
                    choices=["false", "true", "strict"],
                    help="Run RESQML validation on upload (true=warn, strict=reject)")
    ap.add_argument("--auto-ingest", choices=["records", "workflow"],
                    help="Auto-ingest manifest after EPC upload (REST upload only)")
    ap.add_argument("--remote-manifest", action="store_true",
                    help="Use remote RDDMS manifest builder instead of local comprehensive manifest")
    ap.add_argument("--save-only", action="store_true",
                    help="Save manifest, don't push to catalog")
    ap.add_argument("--dry-run", action="store_true",
                    help="No remote changes at all")
    ap.add_argument("--storage", action="store_true",
                    help="Use Storage API instead of Workflow API")
    ap.add_argument("-o", "--output", type=Path,
                    help="Output path for manifest JSON")
    ap.add_argument("--dataspace", type=str,
                    help="Override target dataspace (default: maap/drogon)")
    args = ap.parse_args()

    cfg = InstanceConfig(args.instance)
    if args.dataspace:
        cfg.dataspace = args.dataspace

    print(f"{'═' * 60}")
    print(f"  Drogon Demo → {cfg.name} ({cfg.host})")
    print(f"  Dataspace:  {cfg.dataspace}")
    print(f"  Partition:  {cfg.partition}")
    print(f"  Legal:      {cfg.legal_tag}")
    print(f"  EPC:        {EPC_FILE.name} (404 objects)")
    h5_info = f"{H5_FILE.stat().st_size / 1024 / 1024:.0f} MB" if H5_FILE.exists() else "not found"
    print(f"  H5:         {H5_FILE.name} ({h5_info})")
    print(f"  Upload:     {'REST (EPC+H5)' if args.rest_upload else 'Docker ETP CLI (EPC only)'}")
    print(f"{'═' * 60}\n")

    # ── Auth ──
    token = None
    need_remote = not args.save_only and not args.dry_run
    if need_remote or not args.skip_etp:
        token = authenticate(cfg)

    # ── ETP import ──
    if not args.dry_run and not args.skip_etp:
        if not token:
            token = authenticate(cfg)
        create_dataspace(token, cfg)
        if args.rest_upload:
            ok = upload_epc_rest(
                token, cfg,
                validate=args.validate,
                auto_ingest=args.auto_ingest,
                local=args.local,
            )
        else:
            ok = import_epc(token, cfg)
        if not ok:
            print("  ⚠ ETP import failed - continuing with manifest")
        verify_import(token, cfg)

    # ── Build/load manifest ──
    if args.remote_manifest and not args.skip_etp:
        if not token:
            token = authenticate(cfg)
        manifest = build_manifest_remote(token, cfg)
    else:
        manifest = load_manifest(cfg)

    # ── Patch for target ──
    manifest = patch_manifest(manifest, cfg)

    # ── Enrich spatial metadata (CRS + WGS84 bbox) ──
    manifest = enrich_spatial(manifest, cfg)

    # ── Summary ──
    data = manifest.get("Data", {})
    total = sum(len(v) for v in data.values() if isinstance(v, list))
    print(f"\n  Manifest: {total} records")
    for k, v in data.items():
        if isinstance(v, list) and v:
            print(f"    {k}: {len(v)}")

    # ── Save ──
    out_path = save_manifest(manifest, cfg, args.output)

    if args.save_only or args.dry_run:
        print(f"\n{'─' * 60}")
        print(f"  Done (saved to {out_path.name}, not pushed)")
        return

    # ── Push ──
    print(f"\n=== 7. Push manifest to catalog ===")
    if not token:
        token = authenticate(cfg)

    if args.storage:
        ok = push_via_storage(token, cfg, manifest)
    else:
        ok = push_via_workflow(token, cfg, manifest)
        if not ok:
            print("  Workflow failed, trying Storage API fallback...")
            ok = push_via_storage(token, cfg, manifest)

    if ok:
        print(f"\n{'═' * 60}")
        print(f"  ✓ {total} records indexed in {cfg.name} catalog")
    else:
        print(f"\n  ⚠ Some records failed to index")
        sys.exit(1)


if __name__ == "__main__":
    main()
