#!/usr/bin/env python3
"""
ingest_seismic_vds.py – Ingest Drogon seismic as OpenVDS into OSDU.

Uploads SEG-Y + pre-converted OpenVDS files to the OSDU File service as
FileCollection records, then creates a SeismicTraceData WPC record with
proper Datasets + Artefacts references (conformant with the
work-product-component--SeismicTraceData schema).

The manifest uses:
  - Datasets[]   → points at the original SEG-Y FileCollection record
  - Artefacts[]  → points at the converted OpenVDS FileCollection with
                   RoleID = ArtefactRole:ConvertedContent

Pre-requisites
--------------
  1. Convert SEG-Y → VDS locally (done by this script if --convert flag given):
       SEGYImport src/seismic--amplitude_near_time--20180101.sgy \\
                  --url vds/amplitude_near_time_20180101 --sample-unit ms

  2. Both .sgy files in demo/drogonresqml/src/
  3. Matching .vds files in demo/drogonresqml/vds/

Usage
-----
  python demo/drogonresqml/ingest_seismic_vds.py interop
  python demo/drogonresqml/ingest_seismic_vds.py interop --convert     # also run SEGYImport
  python demo/drogonresqml/ingest_seismic_vds.py interop --dry-run     # no remote writes
  python demo/drogonresqml/ingest_seismic_vds.py interop --skip-upload # manifest only
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid as uuid_mod
from pathlib import Path

try:
    import httpx
except ImportError:
    sys.exit("pip install httpx")

# ── Paths ─────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
DEMO_DIR = SCRIPT_DIR.parent
SRC_DIR = SCRIPT_DIR / "src"
VDS_DIR = SCRIPT_DIR / "vds"
sys.path.insert(0, str(DEMO_DIR))

from _auth import get_token, load_instance  # noqa: E402

# ── Seismic volumes ───────────────────────────────────────────────────────
# (sgy filename, vds dirname, dataset_id base, display name, offset class)
SEISMIC_FILES = [
    (
        "seismic--amplitude_far_time--20180101.sgy",
        "amplitude_far_time_20180101",
        "amplitude_far_time_20180101",
        "Drogon Amplitude Far Offset (Time) 2018-01-01",
        "FAR",
    ),
    (
        "seismic--amplitude_near_time--20180101.sgy",
        "amplitude_near_time_20180101",
        "amplitude_near_time_20180101",
        "Drogon Amplitude Near Offset (Time) 2018-01-01",
        "NEAR",
    ),
]

# OSDU schema kinds (M27)
KIND_SEISMIC_TRACE_DATA = "osdu:wks:work-product-component--SeismicTraceData:1.2.0"
KIND_FILE_COLLECTION_SEGY = "osdu:wks:dataset--FileCollection.SEGY:1.0.0"
KIND_FILE_COLLECTION_VDS = "osdu:wks:dataset--FileCollection.Bluware.OpenVDS:1.2.0"


# ═══════════════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════════════

class Config:
    def __init__(self, name: str):
        self.name = name
        inst = load_instance(name)
        self.host = inst["host"].replace("https://", "").replace("http://", "").rstrip("/")
        self.partition = inst.get("partition") or "opendes"
        self.legal_tag = inst.get("legal_tag") or f"{self.partition}-default-legal-tag"

        owners = inst.get("owners")
        self.owners = (
            owners if isinstance(owners, list)
            else [owners] if owners
            else [f"data.default.owners@{self.partition}.dataservices.energy"]
        )
        viewers = inst.get("viewers")
        self.viewers = (
            viewers if isinstance(viewers, list)
            else [viewers] if viewers
            else [f"data.default.viewers@{self.partition}.dataservices.energy"]
        )
        countries = inst.get("countries")
        self.countries = (
            countries if isinstance(countries, list)
            else [countries] if countries
            else ["NO"]
        )
        self.base_url = f"https://{self.host}"

    def headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "data-partition-id": self.partition,
            "Content-Type": "application/json",
        }

    def acl(self) -> dict:
        return {"owners": list(self.owners), "viewers": list(self.viewers)}

    def legal(self) -> dict:
        return {
            "legaltags": [self.legal_tag],
            "otherRelevantDataCountries": list(self.countries),
            "status": "compliant",
        }


# ═══════════════════════════════════════════════════════════════════════════
# SEG-Y → VDS conversion (local)
# ═══════════════════════════════════════════════════════════════════════════

def convert_segy_to_vds(sgy_path: Path, vds_path: Path) -> bool:
    """Run SEGYImport to convert a SEG-Y file to local VDS."""
    if vds_path.exists():
        print(f"  ℹ  VDS already exists: {vds_path.name}")
        return True

    VDS_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        "SEGYImport",
        str(sgy_path),
        "--url", str(vds_path),
        "--sample-unit", "ms",
    ]
    print(f"  Converting {sgy_path.name} → {vds_path.name} …")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ✗ SEGYImport failed: {result.stderr[:300]}")
        return False
    print(f"  ✓ VDS created ({vds_path.stat().st_size / (1024*1024):.0f} MB)")
    return True


# ═══════════════════════════════════════════════════════════════════════════
# File service upload (creates FileCollection records)
# ═══════════════════════════════════════════════════════════════════════════

def _deterministic_uuid(partition: str, dataset_id: str, suffix: str) -> str:
    """Generate a deterministic UUID for a dataset record (idempotent re-runs)."""
    return str(uuid_mod.uuid5(
        uuid_mod.NAMESPACE_URL,
        f"{partition}/seismic/{dataset_id}/{suffix}",
    ))


def _get_upload_url(token: str, cfg: Config) -> tuple[str, str] | None:
    """
    Get a signed upload URL from the OSDU File service.
    Returns (signedUrl, fileSource) or None.
    """
    url = f"{cfg.base_url}/api/file/v2/files/uploadURL"
    r = httpx.get(url, headers=cfg.headers(token), timeout=30)
    if r.status_code != 200:
        print(f"  ✗ getUploadURL failed {r.status_code}: {r.text[:200]}")
        return None
    data = r.json()
    signed_url = data.get("Location", {}).get("SignedURL") or data.get("signedUrl")
    file_source = data.get("FileSource") or data.get("fileSource") or data.get("FileID")
    return signed_url, file_source


def _upload_file(signed_url: str, file_path: Path, content_type: str = "application/octet-stream") -> bool:
    """Upload a file to the signed URL."""
    size = file_path.stat().st_size
    print(f"  Uploading {file_path.name} ({size / (1024*1024):.1f} MB) …")

    headers = {
        "Content-Type": content_type,
        "Content-Length": str(size),
    }
    if "blob.core.windows.net" in signed_url:
        headers["x-ms-blob-type"] = "BlockBlob"

    def chunks():
        with file_path.open("rb") as fh:
            while True:
                chunk = fh.read(8 * 1024 * 1024)
                if not chunk:
                    break
                yield chunk

    r = httpx.put(signed_url, content=chunks(), headers=headers, timeout=600)
    if r.status_code in (200, 201):
        print(f"  ✓ Upload complete")
        return True
    print(f"  ✗ Upload failed {r.status_code}: {r.text[:200]}")
    return False


def _register_file_metadata(
    token: str,
    cfg: Config,
    file_source: str,
    record_id: str,
    kind: str,
    filename: str,
    description: str,
) -> str | None:
    """Register file metadata with the File service, returning the record ID."""
    url = f"{cfg.base_url}/api/file/v2/files/metadata"
    body = {
        "kind": kind,
        "id": record_id,
        "acl": cfg.acl(),
        "legal": cfg.legal(),
        "data": {
            "Name": filename,
            "Description": description,
            "DatasetProperties": {
                "FileSourceInfo": {
                    "FileSource": file_source,
                    "Name": filename,
                }
            },
            "SchemaFormatTypeID": (
                f"{cfg.partition}:reference-data--SchemaFormatType:SEG-Y:"
                if "SEGY" in kind else
                f"{cfg.partition}:reference-data--SchemaFormatType:OpenVDS:"
            ),
        },
    }
    r = httpx.post(url, headers=cfg.headers(token), json=body, timeout=60)
    if r.status_code in (200, 201):
        resp = r.json()
        rid = resp.get("id", record_id)
        print(f"  ✓ File metadata registered: {rid}")
        return rid
    print(f"  ✗ File metadata failed {r.status_code}: {r.text[:300]}")
    return None


def upload_file_collection(
    token: str,
    cfg: Config,
    file_path: Path,
    record_uuid: str,
    kind: str,
    description: str,
) -> str | None:
    """
    Upload a file to OSDU and register it as a FileCollection dataset.
    Returns the full record ID on success.
    """
    # 1. Get signed upload URL
    upload_info = _get_upload_url(token, cfg)
    if not upload_info:
        return None
    signed_url, file_source = upload_info

    # 2. Upload binary
    content_type = "application/x-segy" if file_path.suffix == ".sgy" else "application/octet-stream"
    if not _upload_file(signed_url, file_path, content_type):
        return None

    # 3. Register file metadata
    kind_prefix = kind.split("--")[1].split(":")[0] if "--" in kind else "FileCollection"
    record_id = f"{cfg.partition}:dataset--{kind_prefix}:{record_uuid}:"
    return _register_file_metadata(
        token, cfg, file_source, record_id, kind, file_path.name, description
    )


# ═══════════════════════════════════════════════════════════════════════════
# SeismicTraceData WPC record (with Datasets + Artefacts)
# ═══════════════════════════════════════════════════════════════════════════

def build_seismic_trace_data_record(
    cfg: Config,
    display_name: str,
    offset_class: str,
    dataset_id: str,
    segy_record_id: str,
    vds_record_id: str,
) -> dict:
    """
    Build a SeismicTraceData WPC record using the proper schema-conformant
    Datasets + Artefacts pattern instead of DDMSDatasets.
    """
    record_uuid = _deterministic_uuid(cfg.partition, dataset_id, "wpc")
    return {
        "kind": KIND_SEISMIC_TRACE_DATA,
        "id": f"{cfg.partition}:work-product-component--SeismicTraceData:{record_uuid}:",
        "acl": cfg.acl(),
        "legal": cfg.legal(),
        "data": {
            "Name": display_name,
            "Description": (
                f"Drogon synthetic seismic – {offset_class.lower()} offset amplitude "
                f"in time domain. Vintage 2018-01-01."
            ),
            "ExistenceKind": f"{cfg.partition}:reference-data--ExistenceKind:Prototype:",
            "IsDiscoverable": True,
            "IsExtendedLoad": False,
            # Datasets: points to the SEG-Y FileCollection record
            "Datasets": [segy_record_id],
            # Artefacts: points to the OpenVDS FileCollection (converted content)
            "Artefacts": [
                {
                    "ResourceID": vds_record_id,
                    "ResourceKind": KIND_FILE_COLLECTION_VDS,
                    "RoleID": f"{cfg.partition}:reference-data--ArtefactRole:ConvertedContent:",
                }
            ],
            # Seismic metadata
            "SeismicDomainTypeID": f"{cfg.partition}:reference-data--SeismicDomainType:Time:",
            "SeismicTraceDataDimensionalityTypeID": (
                f"{cfg.partition}:reference-data--SeismicTraceDataDimensionalityType:3D:"
            ),
            "SeismicAttributeTypeID": (
                f"{cfg.partition}:reference-data--SeismicAttributeType:Amplitude:"
            ),
            "SampleInterval": 1.0,
            "SampleCount": 2000,
            "StartTime": 0.0,
            "EndTime": 1999.0,
            "TraceDomainUOM": f"{cfg.partition}:reference-data--UnitOfMeasure:ms:",
            "InlineMin": 0,
            "InlineMax": 435,
            "CrosslineMin": 0,
            "CrosslineMax": 275,
            "InlineIncrement": 1,
            "CrosslineIncrement": 1,
            "TraceCount": 120336,
            "ExtensionProperties": {
                "OriginalFilename": f"{dataset_id}.sgy",
                "DrogonProject": "maap/drogon",
                "OffsetClass": offset_class,
            },
        },
    }


def build_manifest(cfg: Config, records: list[dict]) -> dict:
    """Assemble a full OSDU manifest."""
    return {
        "kind": "osdu:wks:Manifest:1.0.0",
        "ReferenceData": [],
        "MasterData": [],
        "Data": {
            "WorkProductComponents": records,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# Push to OSDU Storage
# ═══════════════════════════════════════════════════════════════════════════

def push_records(token: str, cfg: Config, records: list[dict]) -> bool:
    """Store records via OSDU Storage v2."""
    url = f"{cfg.base_url}/api/storage/v2/records"
    headers = cfg.headers(token)
    r = httpx.put(url, headers=headers, json=records, timeout=120)
    if r.status_code in (200, 201):
        payload = r.json()
        print(f"  ✓ Stored {payload.get('recordCount', len(records))} record(s)")
        return True
    print(f"  ✗ Storage push failed {r.status_code}: {r.text[:400]}")
    return False


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="Ingest Drogon seismic (OpenVDS) into OSDU with proper manifest"
    )
    ap.add_argument("instance", choices=["interop", "eqndev"],
                    help="Target OSDU instance")
    ap.add_argument("--convert", action="store_true",
                    help="Run SEGYImport to convert .sgy → .vds before upload")
    ap.add_argument("--skip-upload", action="store_true",
                    help="Skip file upload, only push manifest (assumes files already uploaded)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print config + manifest — no remote calls")
    args = ap.parse_args()

    cfg = Config(args.instance)

    print("═" * 64)
    print(f"  Drogon Seismic (OpenVDS) → OSDU on {cfg.name}")
    print(f"  Host:        {cfg.host}")
    print(f"  Partition:   {cfg.partition}")
    print(f"  Legal:       {cfg.legal_tag}")
    print(f"  VDS Kind:    {KIND_FILE_COLLECTION_VDS}")
    print(f"  WPC Kind:    {KIND_SEISMIC_TRACE_DATA}")
    print("═" * 64)

    # ── Convert SEG-Y → VDS if requested ─────────────────────────────────
    if args.convert:
        print("\n=== Convert SEG-Y → OpenVDS ===")
        for sgy_name, vds_name, *_ in SEISMIC_FILES:
            sgy_path = SRC_DIR / sgy_name
            vds_path = VDS_DIR / vds_name
            if not sgy_path.exists():
                sys.exit(f"  ✗ SEG-Y not found: {sgy_path}")
            if not convert_segy_to_vds(sgy_path, vds_path):
                sys.exit(f"  ✗ Conversion failed for {sgy_name}")

    # ── Verify files exist ────────────────────────────────────────────────
    for sgy_name, vds_name, *_ in SEISMIC_FILES:
        if not args.skip_upload:
            sgy_path = SRC_DIR / sgy_name
            vds_path = VDS_DIR / vds_name
            if not sgy_path.exists():
                sys.exit(f"  ✗ SEG-Y not found: {sgy_path}")
            if not vds_path.exists():
                sys.exit(f"  ✗ VDS not found: {vds_path} (run with --convert)")

    if args.dry_run:
        # Build and print manifest without uploading
        wpc_records = []
        for sgy_name, vds_name, dataset_id, display_name, offset_class in SEISMIC_FILES:
            segy_id = f"{cfg.partition}:dataset--FileCollection.SEGY:{_deterministic_uuid(cfg.partition, dataset_id, 'segy')}:"
            vds_id = f"{cfg.partition}:dataset--FileCollection.Bluware.OpenVDS:{_deterministic_uuid(cfg.partition, dataset_id, 'vds')}:"
            wpc_records.append(build_seismic_trace_data_record(
                cfg, display_name, offset_class, dataset_id, segy_id, vds_id
            ))
        manifest = build_manifest(cfg, wpc_records)
        print("\n" + json.dumps(manifest, indent=2))
        return

    # ── Authenticate ──────────────────────────────────────────────────────
    print("\n=== 1. Authenticate ===")
    token = get_token(cfg.name, verbose=True)
    if not token:
        sys.exit(f"  ✗ Failed to get token for {cfg.name}")
    print(f"  ✓ Token obtained")

    # ── Upload files + build WPC records ──────────────────────────────────
    wpc_records = []
    for sgy_name, vds_name, dataset_id, display_name, offset_class in SEISMIC_FILES:
        print(f"\n--- {display_name} ---")

        segy_uuid = _deterministic_uuid(cfg.partition, dataset_id, "segy")
        vds_uuid = _deterministic_uuid(cfg.partition, dataset_id, "vds")

        if args.skip_upload:
            # Assume records already exist with deterministic IDs
            segy_record_id = f"{cfg.partition}:dataset--FileCollection.SEGY:{segy_uuid}:"
            vds_record_id = f"{cfg.partition}:dataset--FileCollection.Bluware.OpenVDS:{vds_uuid}:"
        else:
            # Upload SEG-Y
            print("  [SEG-Y upload]")
            segy_record_id = upload_file_collection(
                token, cfg,
                SRC_DIR / sgy_name,
                segy_uuid,
                KIND_FILE_COLLECTION_SEGY,
                f"Original SEG-Y: {display_name}",
            )
            if not segy_record_id:
                print(f"  ✗ SEG-Y upload failed for {sgy_name}")
                continue

            # Upload VDS
            print("  [OpenVDS upload]")
            vds_record_id = upload_file_collection(
                token, cfg,
                VDS_DIR / vds_name,
                vds_uuid,
                KIND_FILE_COLLECTION_VDS,
                f"OpenVDS converted: {display_name}",
            )
            if not vds_record_id:
                print(f"  ✗ VDS upload failed for {vds_name}")
                continue

        # Build WPC record
        wpc_records.append(build_seismic_trace_data_record(
            cfg, display_name, offset_class, dataset_id, segy_record_id, vds_record_id
        ))

    if not wpc_records:
        sys.exit("No records built – aborting")

    # ── Push manifest ─────────────────────────────────────────────────────
    manifest = build_manifest(cfg, wpc_records)

    # Save manifest locally
    out_file = SCRIPT_DIR / f"manifest_seismic_vds_{cfg.name}.json"
    out_file.write_text(json.dumps(manifest, indent=2))
    print(f"\n  Saved manifest → {out_file.name}")

    print(f"\n=== Push {len(wpc_records)} SeismicTraceData WPC(s) to Storage ===")
    push_records(token, cfg, wpc_records)

    print("\n" + "═" * 64)
    print("Done.")


if __name__ == "__main__":
    main()
