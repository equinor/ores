#!/usr/bin/env python3
"""
ingest_seismic.py – Ingest Drogon demo SEG-Y volumes into OSDU Seismic DDMS.

Targets the Seismic DMS (seistore-svc) REST API v3 on interop / eqndev.
All ACL, legal-tag, and partition values are read from k8s/configmap.yaml +
k8s/secret.yaml (the canonical single source of truth for the ores stack).

Files ingested
--------------
  seismic--amplitude_far_time--20180101.sgy   → amplitude_far_time_20180101
  seismic--amplitude_near_time--20180101.sgy  → amplitude_near_time_20180101

Seismic DDMS pipeline per file
-------------------------------
  1. Auth           – bearer token via existing _auth.py helper
  2. Tenant         – POST /tenant/{tenantid}  (idempotent – 409 = already exists)
  3. SubProject     – POST /subproject/tenant/{tenantid}/subproject/drogon
                      (idempotent – 409 = already exists)
  4. Register       – POST /dataset/tenant/{tenantid}/subproject/drogon/dataset/{dsid}
                      body: type=SEGY, acls, legal  → response contains gcsurl
  5. Upload         – PUT {gcsurl}  (binary, Content-Type: application/octet-stream)
  6. Unlock         – PUT /dataset/.../unlock  (marks upload complete / readonly=false)
  7. Catalog record – build work-product-component--SeismicTraceData records and
                      push to OSDU via Workflow ingestion

Usage
-----
  python demo/drogonresqml/ingest_seismic.py interop
  python demo/drogonresqml/ingest_seismic.py eqndev
  python demo/drogonresqml/ingest_seismic.py interop --skip-upload   # catalog only
  python demo/drogonresqml/ingest_seismic.py interop --dry-run       # no remote writes
  python demo/drogonresqml/ingest_seismic.py interop --skip-catalog  # seistore only
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid as uuid_mod
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

try:
    import httpx
except ImportError:
    sys.exit("pip install httpx")

# ── Paths ─────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent          # demo/drogonresqml/
DEMO_DIR   = SCRIPT_DIR.parent                        # demo/
SRC_DIR    = SCRIPT_DIR / "src"
sys.path.insert(0, str(DEMO_DIR))

from _auth import get_token, load_instance            # noqa: E402

# ── Seismic volumes to ingest ──────────────────────────────────────────────
# Each entry: (local filename, seistore dataset id, human-readable name, offset class)
SEISMIC_FILES = [
    (
        "seismic--amplitude_far_time--20180101.sgy",
        "amplitude_far_time_20180101",
        "Drogon Amplitude Far Offset (Time) 2018-01-01",
        "FAR",
    ),
    (
        "seismic--amplitude_near_time--20180101.sgy",
        "amplitude_near_time_20180101",
        "Drogon Amplitude Near Offset (Time) 2018-01-01",
        "NEAR",
    ),
]

# Seismic DDMS subproject name – aligns with Drogon demo project
SUBPROJECT = "drogon"


# ═══════════════════════════════════════════════════════════════════════════
# Config (reads from k8s/configmap.yaml + k8s/secret.yaml via _auth.py)
# ═══════════════════════════════════════════════════════════════════════════

class SeismicConfig:
    """Mirrors InstanceConfig from ingest_drogon.py but for the seismic DDMS."""

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

        # Seismic DDMS base URL – seistore-svc v3
        self.base_seis = f"https://{self.host}/seistore-svc/api/v3"

        # OSDU core base URL (for catalog / workflow)
        self.base_osdu = f"https://{self.host}"

    # Storage location follows region convention from countries list
    @property
    def storage_location(self) -> str:
        return "EUROPE" if "NO" in self.countries else "US"

    @property
    def esd(self) -> str:
        """Seismic DDMS tenant subdomain, derived from the k8s ACL domain."""
        first_owner = self.owners[0]
        if "@" in first_owner:
            return first_owner.split("@", 1)[1]
        return f"{self.partition}.dataservices.energy"

    def headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "data-partition-id": self.partition,
            "Content-Type": "application/json",
        }

    def acls(self) -> dict:
        """ACL dict in Seismic DDMS format (admins + viewers lists)."""
        return {"admins": list(self.owners), "viewers": list(self.viewers)}

    def legal(self) -> dict:
        """Legal dict in Seismic DDMS / OSDU catalog format."""
        return {
            "legaltags": [self.legal_tag],
            "otherRelevantDataCountries": list(self.countries),
        }

    def __repr__(self) -> str:
        return (
            f"SeismicConfig({self.name}: {self.host}, "
            f"partition={self.partition}, legal={self.legal_tag})"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Step 1 – Auth
# ═══════════════════════════════════════════════════════════════════════════

def authenticate(cfg: SeismicConfig) -> str:
    print(f"=== 1. Authenticate ({cfg.name}) ===")
    token = get_token(cfg.name, verbose=True)
    if not token:
        sys.exit(f"  ✗ Failed to get access token for {cfg.name}")
    print(f"  ✓ Token obtained")
    return token


# ═══════════════════════════════════════════════════════════════════════════
# Step 2 – Ensure tenant is registered
# ═══════════════════════════════════════════════════════════════════════════

def ensure_tenant(token: str, cfg: SeismicConfig) -> bool:
    """
    POST /tenant/{tenantid}
    409 Conflict = already registered, treat as success.
    Body: { acls, legal, storage_class, storage_location, esd }
    """
    print(f"\n=== 2. Ensure Seismic DDMS tenant ({cfg.partition}) ===")
    url = f"{cfg.base_seis}/tenant/{cfg.partition}"

    # GET first to avoid unnecessary POST
    r = httpx.get(url, headers=cfg.headers(token), timeout=30)
    if r.status_code == 200:
        print(f"  ✓ Tenant '{cfg.partition}' already registered")
        return True
    if r.status_code == 403:
        print(f"  ✓ Tenant '{cfg.partition}' exists but metadata is tenant-admin protected (403)")
        return True

    body = {
        "gcpid": cfg.partition,
        "esd": cfg.esd,
        "default_acls": f"users.datalake.admins@{cfg.esd},users.datalake.ops@{cfg.esd}",
        "acls": cfg.acls(),
        "legal": cfg.legal(),
        "storage_class": "STANDARD",
        "storage_location": cfg.storage_location,
    }
    r = httpx.post(url, headers=cfg.headers(token), json=body, timeout=30)
    if r.status_code in (200, 201, 409):
        if r.status_code == 409:
            print(f"  ✓ Tenant '{cfg.partition}' already exists (409)")
        else:
            print(f"  ✓ Tenant '{cfg.partition}' registered ({r.status_code})")
        return True

    print(f"  ✗ Tenant registration failed {r.status_code}: {r.text[:300]}")
    return False


# ═══════════════════════════════════════════════════════════════════════════
# Step 3 – Ensure subproject exists
# ═══════════════════════════════════════════════════════════════════════════

def ensure_subproject(token: str, cfg: SeismicConfig, subproject: str) -> bool:
    """
    POST /subproject/tenant/{tenantid}/subproject/{subprojectid}
    409 Conflict = already exists, treat as success.
    """
    print(f"\n=== 3. Ensure subproject '{subproject}' ===")
    url = f"{cfg.base_seis}/subproject/tenant/{cfg.partition}/subproject/{subproject}"

    # GET first
    r = httpx.get(url, headers=cfg.headers(token), timeout=30)
    if r.status_code == 200:
        print(f"  ✓ Subproject '{subproject}' already exists")
        return True

    body = {
        "admin": cfg.owners[0],
        "acls": cfg.acls(),
        "access_policy": "uniform",
        "storage_class": "STANDARD",
        "storage_location": cfg.storage_location,
    }
    headers = cfg.headers(token)
    headers["ltag"] = cfg.legal_tag
    r = httpx.post(url, headers=headers, json=body, timeout=30)
    if r.status_code in (200, 201, 409):
        if r.status_code == 409:
            print(f"  ✓ Subproject '{subproject}' already exists (409)")
        else:
            print(f"  ✓ Subproject '{subproject}' created ({r.status_code})")
        return True

    print(f"  ✗ Subproject creation failed {r.status_code}: {r.text[:300]}")
    return False


# ═══════════════════════════════════════════════════════════════════════════
# Steps 4–6 – Register dataset + upload + unlock
# ═══════════════════════════════════════════════════════════════════════════

def _dataset_url(cfg: SeismicConfig, subproject: str, dataset_id: str) -> str:
    """Seismic DDMS dataset endpoint URL."""
    return (
        f"{cfg.base_seis}/dataset"
        f"/tenant/{cfg.partition}"
        f"/subproject/{subproject}"
        f"/dataset/{dataset_id}"
    )


def register_dataset(
    token: str,
    cfg: SeismicConfig,
    subproject: str,
    dataset_id: str,
    display_name: str,
    filename: str,
) -> dict | None:
    """
    POST /dataset/tenant/{tid}/subproject/{spid}/dataset/{dsid}
    Returns the registered dataset object (which contains gcsurl for upload).
    """
    url = _dataset_url(cfg, subproject, dataset_id)

    # Check if already registered
    r = httpx.get(url, headers=cfg.headers(token), timeout=30)
    if r.status_code == 200:
        existing = r.json()
        if existing.get("gcsurl") and existing.get("readonly") is False:
            print(f"  ℹ  Dataset '{dataset_id}' already registered and writable – using existing storage object")
            return existing
        print(f"  ℹ  Dataset '{dataset_id}' already registered – re-registering for fresh upload URL")

    body = {
        "acls": cfg.acls(),
        "gtags": ["drogon", "public", "segy", "time", dataset_id],
        "seismicmeta": {
            "kind": "osdu:sdms:seismic3d:1.0.0",
            "legal": cfg.legal(),
            "data": {
                "Name": display_name,
                "OriginalFilename": filename,
                "Project": "maap/drogon",
                "Domain": "Time",
                "Format": "SEGY",
            },
        },
    }
    headers = cfg.headers(token)
    headers["ltag"] = cfg.legal_tag

    def post_register() -> httpx.Response:
        response = httpx.post(url, headers=headers, json=body, timeout=30)
        if response.status_code == 400 and "uniform" in response.text.lower() and "acl" in response.text.lower():
            body_without_acls = dict(body)
            body_without_acls.pop("acls", None)
            response = httpx.post(url, headers=headers, json=body_without_acls, timeout=30)
        return response

    r = post_register()
    if r.status_code == 423 and "write locked" in r.text.lower():
        print("  ℹ  Dataset is write locked – unlocking and retrying")
        unlock_dataset(token, cfg, subproject, dataset_id)
        r = post_register()
    if r.status_code in (200, 201):
        data = r.json()
        print(f"  ✓ Dataset registered: sd://{cfg.partition}/{subproject}/{dataset_id}")
        return data
    print(f"  ✗ Dataset register failed {r.status_code}: {r.text[:400]}")
    return None


def get_upload_sas_url(token: str, cfg: SeismicConfig, subproject: str) -> str | None:
    """Return an Azure SAS container URL for the uniform subproject upload scope."""
    url = f"{cfg.base_seis}/utility/upload-connection-string"
    r = httpx.get(
        url,
        headers=cfg.headers(token),
        params={"sdpath": f"sd://{cfg.partition}/{subproject}"},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"  ✗ Upload credential request failed {r.status_code}: {r.text[:300]}")
        return None
    data = r.json()
    if data.get("token_type") != "SasUrl" or not data.get("access_token"):
        print(f"  ✗ Unsupported upload credential type: {data.get('token_type')}")
        return None
    return data["access_token"]


def resolve_upload_url(token: str, cfg: SeismicConfig, subproject: str, gcsurl: str) -> str | None:
    """Resolve a Seismic DDMS storage object path into a signed upload URL."""
    if gcsurl.startswith(("http://", "https://")):
        return gcsurl

    sas_url = get_upload_sas_url(token, cfg, subproject)
    if not sas_url:
        return None

    parts = urlsplit(sas_url)
    container = parts.path.rstrip("/").split("/")[-1]
    object_path = gcsurl.replace("gs://", "").replace("az://", "")
    if object_path.startswith(container + "/"):
        object_path = object_path[len(container) + 1:]
    object_path = "/".join(quote(part, safe="") for part in object_path.split("/"))
    signed_path = f"{parts.path.rstrip('/')}/{object_path}"
    return urlunsplit((parts.scheme, parts.netloc, signed_path, parts.query, ""))


def upload_sgy(gcsurl: str, sgy_path: Path) -> bool:
    """
    PUT the raw SEG-Y bytes to the GCS/Azure signed URL returned by register.
    No auth header on signed URLs – the signature is embedded in the URL.
    """
    size_bytes = sgy_path.stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    print(f"  Uploading {sgy_path.name} ({size_mb:.1f} MB) …")

    headers = {
        "Content-Type": "application/octet-stream",
        "Content-Length": str(size_bytes),
    }
    if "blob.core.windows.net" in gcsurl:
        headers["x-ms-blob-type"] = "BlockBlob"

    def chunks():
        with sgy_path.open("rb") as fh:
            while True:
                chunk = fh.read(8 * 1024 * 1024)
                if not chunk:
                    break
                yield chunk

    r = httpx.put(
        gcsurl,
        content=chunks(),
        headers=headers,
        timeout=600,       # large file – generous timeout
    )
    if r.status_code in (200, 201):
        print(f"  ✓ Upload complete ({r.status_code})")
        return True
    print(f"  ✗ Upload failed {r.status_code}: {r.text[:300]}")
    return False


def unlock_dataset(token: str, cfg: SeismicConfig, subproject: str, dataset_id: str) -> bool:
    """
    PUT /dataset/.../unlock
    Marks the dataset as fully written and removes the write lock.
    """
    url = _dataset_url(cfg, subproject, dataset_id) + "/unlock"
    r = httpx.put(url, headers=cfg.headers(token), timeout=30)
    if r.status_code in (200, 201, 204):
        print(f"  ✓ Dataset unlocked / finalised")
        return True
    # 404 on unlock just means there was no lock (upload path may differ)
    if r.status_code == 404:
        print(f"  ✓ No lock to release (404 – upload may use alternative path)")
        return True
    print(f"  ✗ Unlock failed {r.status_code}: {r.text[:200]}")
    return False


def ingest_file(
    token: str,
    cfg: SeismicConfig,
    subproject: str,
    filename: str,
    dataset_id: str,
    display_name: str,
    skip_upload: bool,
) -> str | None:
    """Full pipeline for a single SEG-Y file.  Returns the seistore path on success."""
    print(f"\n--- {display_name} ---")
    sgy_path = SRC_DIR / filename

    if not skip_upload and not sgy_path.exists():
        print(f"  ✗ File not found: {sgy_path}")
        return None

    # 4. Register
    dataset_obj = register_dataset(token, cfg, subproject, dataset_id, display_name, filename)
    if dataset_obj is None:
        return None

    if not skip_upload:
        # 5. Upload via signed URL / connection string
        gcsurl = dataset_obj.get("gcsurl") or dataset_obj.get("upload_url")
        if not gcsurl:
            print(f"  ✗ No upload URL in register response: {list(dataset_obj.keys())}")
            return None
        upload_url = resolve_upload_url(token, cfg, subproject, gcsurl)
        if not upload_url:
            return None
        if not upload_sgy(upload_url, sgy_path):
            return None

        # 6. Unlock / finalise
        unlock_dataset(token, cfg, subproject, dataset_id)
    else:
        print(f"  ⏭  Upload skipped (--skip-upload)")

    return f"sd://{cfg.partition}/{subproject}/{dataset_id}"


# ═══════════════════════════════════════════════════════════════════════════
# Step 7 – OSDU catalog manifest (SeismicTraceData WPC records)
# ═══════════════════════════════════════════════════════════════════════════

def _seismic_wpc_record(
    cfg: SeismicConfig,
    seistore_path: str,
    dataset_id: str,
    display_name: str,
    offset_class: str,
    record_uuid: str,
) -> dict:
    """
    Build a work-product-component--SeismicTraceData:1.0.0 catalog record
    linking back to the seistore dataset via DDMSDatasets.
    """
    return {
        "kind": "osdu:wks:work-product-component--SeismicTraceData:1.0.0",
        "acl": {
            "owners": list(cfg.owners),
            "viewers": list(cfg.viewers),
        },
        "legal": {
            "legaltags": [cfg.legal_tag],
            "otherRelevantDataCountries": list(cfg.countries),
            "status": "compliant",
        },
        "id": f"{cfg.partition}:work-product-component--SeismicTraceData:{record_uuid}",
        "data": {
            "Name": display_name,
            "Description": (
                f"Drogon synthetic seismic – {offset_class.lower()} offset amplitude "
                f"in time domain. Vintage 2018-01-01."
            ),
            "ExistenceKind": f"{cfg.partition}:reference-data--ExistenceKind:Prototype:",
            "IsDiscoverable": True,
            "IsExtendedLoad": False,
            # SeismicDDMS dataset path – consumed by seismic-aware apps
            "DDMSDatasets": [seistore_path],
            # Attribute classification
            "SeismicDomainTypeID": (
                f"{cfg.partition}:reference-data--SeismicDomainType:Time:"
            ),
            "BinGridID": "",          # No bin grid in catalog yet – filled post-ingest
            "OffsetClass": offset_class,
            "ExtensionProperties": {
                "OriginalFilename": f"{dataset_id}.sgy",
                "DrogonProject": "maap/drogon",
            },
        },
    }


def build_seismic_manifest(
    cfg: SeismicConfig,
    seistore_paths: list[tuple[str, str, str, str]],   # (path, dataset_id, name, offset)
) -> dict:
    """
    Assemble M27-style manifest with one SeismicTraceData WPC per file.
    seistore_paths: list of (seistore_path, dataset_id, display_name, offset_class)
    """
    wpcs = []
    for seistore_path, dataset_id, display_name, offset_class in seistore_paths:
        record_uuid = str(uuid_mod.uuid5(
            uuid_mod.NAMESPACE_URL,
            f"{cfg.partition}/seismic/{dataset_id}",
        ))
        wpcs.append(
            _seismic_wpc_record(
                cfg, seistore_path, dataset_id, display_name, offset_class, record_uuid
            )
        )
    return {
        "kind": "osdu:wks:Manifest:1.0.0",
        "Data": {
            "WorkProductComponents": wpcs,
        },
    }


def push_manifest(token: str, cfg: SeismicConfig, manifest: dict) -> bool:
    """
    Store the SeismicTraceData WPC records directly via OSDU Storage.

    The Osdu_ingest workflow can return `finished` for this small manifest while
    storing no records, so use the same reliable Storage path as the Drogon
    ingest fallback.
    """
    print(f"\n=== 7. Push catalog records via Storage ===")
    url = f"{cfg.base_osdu}/api/storage/v2/records"
    headers = {
        "Authorization": f"Bearer {token}",
        "data-partition-id": cfg.partition,
        "Content-Type": "application/json",
    }
    records = manifest.get("Data", {}).get("WorkProductComponents", [])
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
        description="Ingest Drogon SEG-Y volumes to OSDU Seismic DDMS"
    )
    ap.add_argument("instance", choices=["interop", "eqndev"],
                    help="Target OSDU instance (reads ACL/legal/partition from k8s/)")
    ap.add_argument("--skip-upload", action="store_true",
                    help="Register datasets in seistore but do not upload binary data")
    ap.add_argument("--skip-catalog", action="store_true",
                    help="Upload to seistore but skip OSDU catalog manifest push")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print config and planned actions – no remote calls")
    ap.add_argument("--subproject", default=SUBPROJECT,
                    help=f"Seistore subproject name (default: {SUBPROJECT})")
    args = ap.parse_args()

    cfg = SeismicConfig(args.instance)

    print("═" * 64)
    print(f"  Drogon Seismic → Seismic DDMS on {cfg.name}")
    print(f"  Host:        {cfg.host}")
    print(f"  Partition:   {cfg.partition}")
    print(f"  Legal:       {cfg.legal_tag}")
    print(f"  ACL owners:  {cfg.owners}")
    print(f"  ACL viewers: {cfg.viewers}")
    print(f"  Countries:   {cfg.countries}")
    print(f"  Subproject:  {args.subproject}")
    print(f"  Base URL:    {cfg.base_seis}")
    print(f"  Files:")
    for fname, dsid, name, offset in SEISMIC_FILES:
        path = SRC_DIR / fname
        size = f"{path.stat().st_size / (1024*1024):.1f} MB" if path.exists() else "MISSING"
        print(f"    {fname}  [{size}]  → sd://{cfg.partition}/{args.subproject}/{dsid}")
    print("═" * 64)

    if args.dry_run:
        print("\n[dry-run] No remote calls made.")
        return

    # ── Step 1: auth ──────────────────────────────────────────────────────
    token = authenticate(cfg)

    # ── Steps 2–3: tenant + subproject ───────────────────────────────────
    if not ensure_tenant(token, cfg):
        sys.exit("Aborting: tenant setup failed")
    if not ensure_subproject(token, cfg, args.subproject):
        sys.exit("Aborting: subproject setup failed")

    # ── Steps 4–6: upload each file ───────────────────────────────────────
    ingested: list[tuple[str, str, str, str]] = []   # (seistore_path, dsid, name, offset)
    for filename, dataset_id, display_name, offset_class in SEISMIC_FILES:
        seistore_path = ingest_file(
            token, cfg, args.subproject,
            filename, dataset_id, display_name,
            skip_upload=args.skip_upload,
        )
        if seistore_path:
            ingested.append((seistore_path, dataset_id, display_name, offset_class))

    if not ingested:
        sys.exit("No files ingested successfully – aborting catalog push")

    print(f"\n  ✓ Ingested {len(ingested)}/{len(SEISMIC_FILES)} file(s) to seistore")

    # ── Step 7: OSDU catalog ──────────────────────────────────────────────
    if args.skip_catalog:
        print("\n[--skip-catalog] Skipping manifest push.")
        return

    manifest = build_seismic_manifest(cfg, ingested)

    # Save patched manifest alongside instance manifests
    out_file = SCRIPT_DIR / f"manifest_seismic_{cfg.name}.json"
    out_file.write_text(json.dumps(manifest, indent=2))
    print(f"\n  Saved manifest → {out_file.name}")
    print(f"  Records: {len(manifest['Data']['WorkProductComponents'])} SeismicTraceData WPC(s)")

    push_manifest(token, cfg, manifest)

    print("\n═" * 64)
    print("Done.")


if __name__ == "__main__":
    main()
