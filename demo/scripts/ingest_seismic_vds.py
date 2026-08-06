#!/usr/bin/env python3
"""
ingest_seismic_vds.py – Generic seismic OpenVDS ingestion into OSDU.

Uploads SEG-Y and/or pre-converted OpenVDS files to the OSDU File service
as FileCollection records, then creates SeismicTraceData WPC records with
proper Datasets + Artefacts references.

Supports two modes:
  1. Auto-scan:   point at a .sgy or VDS file — metadata extracted automatically.
  2. JSON config: provide a config file with full control over all parameters.

Usage (CLI)
-----------
  # Auto-scan (zero-config):
  python -m demo.scripts.ingest_seismic_vds --scan cube.sgy eqndev --dry-run
  python -m demo.scripts.ingest_seismic_vds --scan cube.sgy --scan-vds vds/ eqndev
  python -m demo.scripts.ingest_seismic_vds --scan cube.sgy eqndev --save-config out.json

  # JSON config (full control):
  python -m demo.scripts.ingest_seismic_vds config.json interop
  python -m demo.scripts.ingest_seismic_vds config.json interop --dry-run

Usage (library)
---------------
  from demo.scripts.ingest_seismic_vds import SeismicVdsIngestor, survey_from_scan

  survey = survey_from_scan(segy_path="cube.sgy", vds_path="vds/cube")
  ingestor = SeismicVdsIngestor.from_instance_name("eqndev", survey)
  ingestor.run(dry_run=False)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid as uuid_mod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import httpx
except ImportError:
    sys.exit("pip install httpx")


# ═══════════════════════════════════════════════════════════════════════════
# Data structures for survey configuration
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class SeismicVolume:
    """One seismic volume (e.g. near/far offset)."""
    segy_file: str                     # e.g. "seismic--amplitude_far_time--20180101.sgy"
    vds_file: str                      # e.g. "amplitude_far_time_20180101" (dir name under vds/)
    wpc_id: str                        # e.g. "drogon-amp-far-time-20180101"
    segy_dataset_id: str               # e.g. "drogon-amplitude-far-time-20180101"
    vds_dataset_id: str                # e.g. "drogon-amplitude-far-time-20180101"
    display_name: str                  # e.g. "Drogon Amplitude Far Offset (Time) 2018-01-01"
    offset_class: str = ""             # e.g. "FAR", "NEAR"
    description: str = ""              # if empty, auto-generated


@dataclass
class BinGridConfig:
    """SeismicBinGrid geometry parameters."""
    id: str = ""                       # record ID base (e.g. "drogon-seismic-bingrid")
    name: str = ""
    description: str = ""
    inline_min: int = 0
    inline_max: int = 0
    crossline_min: int = 0
    crossline_max: int = 0
    inline_bin_count: int = 0
    crossline_bin_count: int = 0
    inline_bin_width: float = 25.0
    crossline_bin_width: float = 25.0
    origin_easting: float = 0.0
    origin_northing: float = 0.0
    origin_i: int = 0
    origin_j: int = 0
    node_increment_i: Dict[str, float] = field(default_factory=lambda: {"X": 25.0, "Y": 0.0})
    node_increment_j: Dict[str, float] = field(default_factory=lambda: {"X": 0.0, "Y": 25.0})
    transformation_method: str = "9666"


@dataclass
class SeismicConfig:
    """Seismic trace metadata."""
    domain: str = "Time"               # Time or Depth
    dimensionality: str = "3D"
    attribute: str = "Amplitude"
    sample_interval: float = 1.0
    sample_count: int = 2000
    start_value: float = 0.0           # StartTime or StartDepth
    end_value: float = 1999.0          # EndTime or EndDepth
    trace_uom: str = "ms"              # ms, m, ft
    inline_min: int = 0
    inline_max: int = 0
    crossline_min: int = 0
    crossline_max: int = 0
    inline_increment: int = 1
    crossline_increment: int = 1
    trace_count: int = 0


@dataclass
class SurveyConfig:
    """Complete survey configuration loaded from JSON."""
    volumes: List[SeismicVolume]
    seismic: SeismicConfig
    bingrid: BinGridConfig
    spatial_area: Dict[str, Any] = field(default_factory=dict)
    crs_uuid: str = ""
    existence_kind: str = "Prototype"
    extension_properties: Dict[str, Any] = field(default_factory=dict)
    src_dir: str = ""                  # directory containing .sgy files
    vds_dir: str = ""                  # directory containing VDS dirs
    # Optional instance overrides (take precedence over resolved instance config)
    legal_tag: str = ""                # e.g. "opendes-default-legal-tag"
    owners: List[str] = field(default_factory=list)   # ACL owners
    viewers: List[str] = field(default_factory=list)  # ACL viewers
    countries: List[str] = field(default_factory=list) # legal countries


def load_survey_config(path: str | Path) -> SurveyConfig:
    """Load a SurveyConfig from a JSON file."""
    data = json.loads(Path(path).read_text())

    volumes = [SeismicVolume(**v) for v in data["volumes"]]

    seismic_data = data.get("seismic", {})
    seismic = SeismicConfig(**seismic_data)

    bingrid_data = data.get("bingrid", {})
    bingrid = BinGridConfig(**bingrid_data)

    # Instance overrides (optional section in JSON)
    inst = data.get("instance", {})

    return SurveyConfig(
        volumes=volumes,
        seismic=seismic,
        bingrid=bingrid,
        spatial_area=data.get("spatial_area", {}),
        crs_uuid=data.get("crs_uuid", ""),
        existence_kind=data.get("existence_kind", "Prototype"),
        extension_properties=data.get("extension_properties", {}),
        src_dir=data.get("src_dir", ""),
        vds_dir=data.get("vds_dir", ""),
        legal_tag=inst.get("legal_tag", ""),
        owners=inst.get("owners", []),
        viewers=inst.get("viewers", []),
        countries=inst.get("countries", []),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Auto-scan metadata from SEG-Y or VDS
# ═══════════════════════════════════════════════════════════════════════════

def _slugify(name: str) -> str:
    """Convert a filename to a URL-safe slug for record IDs."""
    import re
    slug = Path(name).stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    # Limit length
    if len(slug) > 80:
        slug = slug[:80].rstrip("-")
    return slug


def _approximate_wgs84_from_utm(easting: float, northing: float, zone: int = 31) -> tuple[float, float]:
    """Very rough UTM→WGS84 approximation (good enough for bounding box)."""
    # Simplified inverse UTM for zones 30-32, Norwegian Sea
    import math
    lon0 = (zone - 1) * 6 - 180 + 3
    lat = northing / 111320.0
    lon = lon0 + (easting - 500000) / (111320 * math.cos(math.radians(lat)))
    return round(lon, 4), round(lat, 4)


def scan_segy(segy_path: str | Path) -> dict:
    """
    Scan a SEG-Y file and return extracted metadata as a dict.

    Returns dict with keys: inline_min, inline_max, crossline_min, crossline_max,
    sample_count, sample_interval, start_value, end_value, trace_count,
    trace_uom, origin_easting, origin_northing, coord_scalar, corners.
    """
    try:
        import segyio
    except ImportError:
        sys.exit("pip install segyio  (required for --scan)")

    segy_path = Path(segy_path)
    print(f"  Scanning {segy_path.name} …")

    with segyio.open(str(segy_path), ignore_geometry=True) as f:
        trace_count = f.tracecount
        sample_count = len(f.samples)
        sample_interval = float(f.samples[1] - f.samples[0]) if sample_count > 1 else 0.0
        start_value = float(f.samples[0])
        end_value = float(f.samples[-1])

        # Determine time/depth from sample unit heuristic
        # interval < 1 or > 10ms usually means depth (metres)
        if sample_interval >= 0.5 and sample_interval <= 16.0:
            trace_uom = "ms"
            domain = "Time"
        else:
            trace_uom = "m"
            domain = "Depth"

        # Scan IL/XL from all trace headers
        ils = []
        xls = []
        for i in range(trace_count):
            ils.append(f.header[i][segyio.TraceField.INLINE_3D])
            xls.append(f.header[i][segyio.TraceField.CROSSLINE_3D])

        inline_min = min(ils)
        inline_max = max(ils)
        crossline_min = min(xls)
        crossline_max = max(xls)

        # Coordinates from corner traces
        scalar = f.header[0][segyio.TraceField.SourceGroupScalar]
        scale = abs(1.0 / scalar) if scalar < 0 else float(scalar) if scalar > 0 else 1.0

        def _get_coord(idx: int) -> tuple[float, float]:
            x = f.header[idx][segyio.TraceField.CDP_X] * scale
            y = f.header[idx][segyio.TraceField.CDP_Y] * scale
            return x, y

        origin = _get_coord(0)
        last = _get_coord(trace_count - 1)

        # Infer increment from unique counts
        unique_ils = sorted(set(ils))
        unique_xls = sorted(set(xls))
        il_increment = unique_ils[1] - unique_ils[0] if len(unique_ils) > 1 else 1
        xl_increment = unique_xls[1] - unique_xls[0] if len(unique_xls) > 1 else 1

    print(f"    IL: {inline_min}–{inline_max} ({len(unique_ils)} lines)")
    print(f"    XL: {crossline_min}–{crossline_max} ({len(unique_xls)} lines)")
    print(f"    Samples: {sample_count} @ {sample_interval}{trace_uom}")
    print(f"    Traces: {trace_count}")
    print(f"    Origin: E={origin[0]:.2f}, N={origin[1]:.2f}")

    return {
        "domain": domain,
        "inline_min": inline_min,
        "inline_max": inline_max,
        "crossline_min": crossline_min,
        "crossline_max": crossline_max,
        "inline_increment": il_increment,
        "crossline_increment": xl_increment,
        "inline_count": len(unique_ils),
        "crossline_count": len(unique_xls),
        "sample_count": sample_count,
        "sample_interval": sample_interval,
        "start_value": start_value,
        "end_value": end_value,
        "trace_count": trace_count,
        "trace_uom": trace_uom,
        "origin_easting": origin[0],
        "origin_northing": origin[1],
        "corner_last": last,
        "coord_scalar": scalar,
    }


def scan_vds(vds_path: str | Path) -> dict:
    """
    Scan a local VDS directory and return extracted metadata.

    Returns same keys as scan_segy (subset — no coordinate info).
    """
    try:
        import openvds
    except ImportError:
        sys.exit("pip install openvds  (required for --scan with VDS)")

    vds_path = Path(vds_path)
    print(f"  Scanning VDS {vds_path.name} …")

    handle = openvds.open(str(vds_path))
    layout = openvds.getLayout(handle)

    meta: dict = {"domain": "Time"}
    for i in range(layout.dimensionality):
        axis = layout.getAxisDescriptor(i)
        if axis.name == "Sample":
            meta["sample_count"] = axis.numSamples
            meta["start_value"] = float(axis.coordinateMin)
            meta["end_value"] = float(axis.coordinateMax)
            meta["trace_uom"] = axis.unit or "ms"
            if axis.numSamples > 1:
                meta["sample_interval"] = (axis.coordinateMax - axis.coordinateMin) / (axis.numSamples - 1)
            if axis.unit in ("m", "ft"):
                meta["domain"] = "Depth"
        elif axis.name == "Inline":
            meta["inline_min"] = int(axis.coordinateMin)
            meta["inline_max"] = int(axis.coordinateMax)
            meta["inline_count"] = axis.numSamples
            if axis.numSamples > 1:
                meta["inline_increment"] = int((axis.coordinateMax - axis.coordinateMin) / (axis.numSamples - 1))
        elif axis.name == "Crossline":
            meta["crossline_min"] = int(axis.coordinateMin)
            meta["crossline_max"] = int(axis.coordinateMax)
            meta["crossline_count"] = axis.numSamples
            if axis.numSamples > 1:
                meta["crossline_increment"] = int((axis.coordinateMax - axis.coordinateMin) / (axis.numSamples - 1))

    openvds.close(handle)

    meta["trace_count"] = meta.get("inline_count", 1) * meta.get("crossline_count", 1)
    print(f"    IL: {meta.get('inline_min')}–{meta.get('inline_max')} ({meta.get('inline_count')} lines)")
    print(f"    XL: {meta.get('crossline_min')}–{meta.get('crossline_max')} ({meta.get('crossline_count')} lines)")
    print(f"    Samples: {meta.get('sample_count')} @ {meta.get('sample_interval', '?')}{meta.get('trace_uom', '')}")

    return meta


def survey_from_scan(
    segy_path: str | Path | None = None,
    vds_path: str | Path | None = None,
    *,
    name: str = "",
    description: str = "",
) -> SurveyConfig:
    """
    Build a SurveyConfig entirely from scanning a SEG-Y and/or VDS file.

    IDs are generated from the filename. At least one of segy_path or vds_path
    must be provided.
    """
    if not segy_path and not vds_path:
        raise ValueError("Provide at least one of segy_path or vds_path")

    # Prefer VDS metadata (more reliable), fall back to SEG-Y
    segy_meta = scan_segy(segy_path) if segy_path else {}
    vds_meta = scan_vds(vds_path) if vds_path else {}
    meta = {**segy_meta, **vds_meta}  # VDS wins on overlap

    # Generate slug IDs from filename
    base_file = Path(vds_path or segy_path)
    slug = _slugify(base_file.name)
    display_name = name or base_file.stem.replace("_", " ").replace("--", " – ")

    # Build volume
    vol = SeismicVolume(
        segy_file=Path(segy_path).name if segy_path else "",
        vds_file=Path(vds_path).name if vds_path else slug,
        wpc_id=slug,
        segy_dataset_id=f"{slug}-segy" if segy_path else "",
        vds_dataset_id=f"{slug}-vds",
        display_name=display_name,
        description=description,
    )

    # Build seismic config
    seismic = SeismicConfig(
        domain=meta.get("domain", "Time"),
        dimensionality="3D",
        attribute="Amplitude",
        sample_interval=meta.get("sample_interval", 4.0),
        sample_count=meta.get("sample_count", 0),
        start_value=meta.get("start_value", 0.0),
        end_value=meta.get("end_value", 0.0),
        trace_uom=meta.get("trace_uom", "ms"),
        inline_min=meta.get("inline_min", 0),
        inline_max=meta.get("inline_max", 0),
        crossline_min=meta.get("crossline_min", 0),
        crossline_max=meta.get("crossline_max", 0),
        inline_increment=meta.get("inline_increment", 1),
        crossline_increment=meta.get("crossline_increment", 1),
        trace_count=meta.get("trace_count", 0),
    )

    # Build bingrid (use same geometry as seismic; refine manually if needed)
    il_count = meta.get("inline_count", seismic.inline_max - seismic.inline_min + 1)
    xl_count = meta.get("crossline_count", seismic.crossline_max - seismic.crossline_min + 1)

    bingrid = BinGridConfig(
        id=f"{slug}-bingrid",
        name=f"{display_name} Bin Grid",
        inline_min=seismic.inline_min,
        inline_max=seismic.inline_max,
        crossline_min=seismic.crossline_min,
        crossline_max=seismic.crossline_max,
        inline_bin_count=il_count,
        crossline_bin_count=xl_count,
        origin_easting=meta.get("origin_easting", 0.0),
        origin_northing=meta.get("origin_northing", 0.0),
    )

    # Build approximate spatial area from corner coordinates
    spatial_area: Dict[str, Any] = {}
    if "origin_easting" in segy_meta:
        e0, n0 = segy_meta["origin_easting"], segy_meta["origin_northing"]
        e1, n1 = segy_meta.get("corner_last", (e0, n0))
        lon0, lat0 = _approximate_wgs84_from_utm(e0, n0)
        lon1, lat1 = _approximate_wgs84_from_utm(e1, n1)
        sw_lon, ne_lon = min(lon0, lon1), max(lon0, lon1)
        sw_lat, ne_lat = min(lat0, lat1), max(lat0, lat1)
        spatial_area = {
            "Wgs84Coordinates": {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[sw_lon, sw_lat], [ne_lon, sw_lat],
                                         [ne_lon, ne_lat], [sw_lon, ne_lat],
                                         [sw_lon, sw_lat]]]
                    }
                }]
            }
        }

    # Extension properties
    ext: Dict[str, Any] = {}
    if segy_path:
        ext["OriginalFilename"] = Path(segy_path).name

    return SurveyConfig(
        volumes=[vol],
        seismic=seismic,
        bingrid=bingrid,
        spatial_area=spatial_area,
        extension_properties=ext,
        src_dir=str(Path(segy_path).parent) if segy_path else "",
        vds_dir=str(Path(vds_path).parent) if vds_path else "",
    )


# ═══════════════════════════════════════════════════════════════════════════
# OSDU schema kinds
# ═══════════════════════════════════════════════════════════════════════════

KIND_SEISMIC_TRACE_DATA = "osdu:wks:work-product-component--SeismicTraceData:1.2.0"
KIND_FILE_COLLECTION_SEGY = "osdu:wks:dataset--FileCollection.SEGY:1.0.0"
KIND_FILE_COLLECTION_VDS = "osdu:wks:dataset--FileCollection.Bluware.OpenVDS:1.2.0"
KIND_SEISMIC_BINGRID = "osdu:wks:work-product-component--SeismicBinGrid:1.0.0"


# ═══════════════════════════════════════════════════════════════════════════
# Ingestor
# ═══════════════════════════════════════════════════════════════════════════

class SeismicVdsIngestor:
    """
    Generic seismic VDS ingestor.

    Handles:
      1. Optional SEG-Y → VDS conversion (SEGYImport)
      2. File upload via OSDU File service
      3. FileCollection metadata registration
      4. SeismicTraceData WPC record creation
      5. SeismicBinGrid record creation
    """

    def __init__(self, client, survey: SurveyConfig):
        """
        Parameters
        ----------
        client : OsduClient
            An authenticated OsduClient instance from demo.scripts.osdu_client.
        survey : SurveyConfig
            Survey configuration (volumes, geometry, spatial area, etc.).
        """
        self.client = client
        self.survey = survey
        self.partition = client.instance.partition

    @classmethod
    def from_instance_name(
        cls,
        name: str,
        survey: SurveyConfig,
        *,
        legal_tag: str = "",
        owners: List[str] | None = None,
        viewers: List[str] | None = None,
    ) -> "SeismicVdsIngestor":
        """Create ingestor by resolving instance name.

        Instance config overrides (priority): CLI args > survey JSON > resolved instance.
        """
        from .osdu_client import OsduClient
        client = OsduClient.from_instance_name(name)

        # Apply overrides: CLI > survey config > resolved instance defaults
        if legal_tag or survey.legal_tag:
            client.instance.legal_tag = legal_tag or survey.legal_tag
        if owners or survey.owners:
            client.instance.owners = owners or survey.owners
        if viewers or survey.viewers:
            client.instance.viewers = viewers or survey.viewers
        if survey.countries:
            client.instance.countries = survey.countries

        return cls(client, survey)

    # ── Record ID helpers ────────────────────────────────────────────────

    def _record_id(self, entity: str, name: str) -> str:
        return f"{self.partition}:{entity}:{name}:"

    def _dataset_record_id(self, kind_suffix: str, name: str) -> str:
        return self._record_id(f"dataset--{kind_suffix}", name)

    def _wpc_record_id(self, name: str) -> str:
        return self._record_id("work-product-component--SeismicTraceData", name)

    def _bingrid_record_id(self) -> str:
        return self._record_id(
            "work-product-component--SeismicBinGrid", self.survey.bingrid.id
        )

    def _crs_id(self) -> str:
        uuid = self.survey.crs_uuid
        if not uuid:
            return ""
        if self.partition == "opendes":
            return f"opendes:work-product-component--LocalModelCompoundCrs:{uuid}"
        return f"{self.partition}:work-product-component--LocalModelCompoundCrs:1.2.0:{uuid}"

    # ── File service operations ──────────────────────────────────────────

    def _get_upload_url(self) -> Optional[tuple[str, str]]:
        """Get a signed upload URL. Returns (signedUrl, fileSource) or None."""
        url = f"{self.client.instance.host}/api/file/v2/files/uploadURL"
        r = httpx.get(url, headers=self.client.headers, timeout=30)
        if r.status_code != 200:
            print(f"  ✗ getUploadURL failed {r.status_code}: {r.text[:200]}")
            return None
        data = r.json()
        signed_url = data.get("Location", {}).get("SignedURL") or data.get("signedUrl")
        file_source = data.get("FileSource") or data.get("fileSource") or data.get("FileID")
        return signed_url, file_source

    def _upload_file(self, signed_url: str, file_path: Path, content_type: str = "application/octet-stream") -> bool:
        """Upload bytes to the signed URL."""
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
        self,
        file_source: str,
        record_id: str,
        kind: str,
        file_path: Path,
        name: str,
        description: str,
        collection_path: str | None = None,
    ) -> str | None:
        """Register file metadata with the File service (with Storage fallback)."""
        url = f"{self.client.instance.host}/api/file/v2/files/metadata"
        filename = file_path.name
        file_size = file_path.stat().st_size
        dataset_props: dict = {
            "FileSourceInfo": {
                "FileSource": file_source,
                "Name": filename,
                "FileSize": str(file_size),
            },
            "FileSourceInfos": [
                {
                    "FileSource": file_source,
                    "Name": filename,
                    "FileSize": str(file_size),
                }
            ],
        }
        if collection_path:
            dataset_props["FileCollectionPath"] = collection_path

        body = {
            "kind": kind,
            "id": record_id,
            "acl": self.client.instance.acl,
            "legal": self.client.instance.legal,
            "data": {
                "Name": name,
                "Description": description,
                "TotalSize": str(file_size),
                "ResourceSecurityClassification": (
                    f"{self.partition}:reference-data--ResourceSecurityClassification:RESTRICTED:"
                ),
                "DatasetProperties": dataset_props,
                "SchemaFormatTypeID": (
                    f"{self.partition}:reference-data--SchemaFormatType:SEG-Y:"
                    if "SEGY" in kind else
                    f"{self.partition}:reference-data--SchemaFormatType:OpenVDS:"
                ),
            },
        }
        r = httpx.post(url, headers=self.client.headers, json=body, timeout=60)
        if r.status_code in (200, 201):
            resp = r.json()
            rid = resp.get("id", record_id)
            print(f"  ✓ File metadata registered: {rid}")
            return rid

        # Fallback to Storage upsert
        print(f"  ! File metadata failed {r.status_code}: {r.text[:300]}")
        print("  Falling back to Storage record upsert for FileCollection metadata")
        storage_url = f"{self.client.instance.host}/api/storage/v2/records"
        storage_resp = httpx.put(storage_url, headers=self.client.headers, json=[body], timeout=60)
        if storage_resp.status_code in (200, 201):
            print(f"  ✓ FileCollection stored: {record_id}")
            return record_id
        print(f"  ✗ Storage fallback failed {storage_resp.status_code}: {storage_resp.text[:300]}")
        return None

    def upload_file_collection(
        self,
        file_path: Path,
        record_id: str,
        kind: str,
        name: str,
        description: str,
        collection_path: str | None = None,
    ) -> str | None:
        """Upload a file and register it as a FileCollection dataset. Returns record ID."""
        upload_info = self._get_upload_url()
        if not upload_info:
            return None
        signed_url, file_source = upload_info

        content_type = "application/x-segy" if file_path.suffix == ".sgy" else "application/octet-stream"
        if not self._upload_file(signed_url, file_path, content_type):
            return None

        return self._register_file_metadata(
            file_source, record_id, kind, file_path, name, description,
            collection_path=collection_path,
        )

    # ── SEG-Y → VDS conversion ──────────────────────────────────────────

    def convert_segy_to_vds(self, sgy_path: Path, vds_path: Path, sample_unit: str = "ms") -> bool:
        """Run SEGYImport to convert a SEG-Y file to local VDS."""
        if vds_path.exists():
            print(f"  ℹ  VDS already exists: {vds_path.name}")
            return True

        vds_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["SEGYImport", str(sgy_path), "--url", str(vds_path), "--sample-unit", sample_unit]
        print(f"  Converting {sgy_path.name} → {vds_path.name} …")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ✗ SEGYImport failed: {result.stderr[:300]}")
            return False
        print(f"  ✓ VDS created ({vds_path.stat().st_size / (1024*1024):.0f} MB)")
        return True

    # ── Record builders ──────────────────────────────────────────────────

    def build_seismic_trace_data_record(self, vol: SeismicVolume, segy_record_id: str, vds_record_id: str) -> dict:
        """Build a SeismicTraceData WPC record."""
        s = self.survey.seismic
        # Extract the ID base from record ID (e.g. "dev:dataset--X:my-id:" → "my-id")
        parts = [p for p in vds_record_id.split(":") if p]
        vds_id_base = parts[-1] if parts else vol.vds_dataset_id
        sd_path = f"sd://{self.partition}/{vds_id_base}"

        description = vol.description or (
            f"{vol.display_name} – {vol.offset_class.lower()} offset {s.attribute.lower()} "
            f"in {s.domain.lower()} domain."
        )

        # Domain-specific start/end keys
        if s.domain.lower() == "time":
            domain_keys = {"StartTime": s.start_value, "EndTime": s.end_value}
        else:
            domain_keys = {"StartDepth": s.start_value, "EndDepth": s.end_value}

        data: Dict[str, Any] = {
            "Name": vol.display_name,
            "Description": description,
            "ExistenceKind": f"{self.partition}:reference-data--ExistenceKind:{self.survey.existence_kind}:",
            "IsDiscoverable": True,
            "IsExtendedLoad": False,
            "Datasets": [vds_record_id],
            "Artefacts": [
                {
                    "ResourceID": vds_record_id,
                    "ResourceKind": KIND_FILE_COLLECTION_VDS,
                    "RoleID": f"{self.partition}:reference-data--ArtefactRole:ConvertedContent:",
                }
            ],
            "DDMSDatasets": [sd_path],
            "BinGridID": self._bingrid_record_id(),
            "SeismicDomainTypeID": f"{self.partition}:reference-data--SeismicDomainType:{s.domain}:",
            "SeismicTraceDataDimensionalityTypeID": (
                f"{self.partition}:reference-data--SeismicTraceDataDimensionalityType:{s.dimensionality}:"
            ),
            "SeismicAttributeTypeID": f"{self.partition}:reference-data--SeismicAttributeType:{s.attribute}:",
            "SampleInterval": s.sample_interval,
            "SampleCount": s.sample_count,
            "TraceDomainUOM": f"{self.partition}:reference-data--UnitOfMeasure:{s.trace_uom}:",
            "InlineMin": s.inline_min,
            "InlineMax": s.inline_max,
            "CrosslineMin": s.crossline_min,
            "CrosslineMax": s.crossline_max,
            "InlineIncrement": s.inline_increment,
            "CrosslineIncrement": s.crossline_increment,
            "TraceCount": s.trace_count,
            **domain_keys,
        }

        crs_id = self._crs_id()
        if crs_id:
            data["CoordinateReferenceSystemID"] = crs_id
        if self.survey.spatial_area:
            data["SpatialArea"] = self.survey.spatial_area

        # Merge extension properties (global + per-volume offset class)
        ext = dict(self.survey.extension_properties)
        if vol.offset_class:
            ext["OffsetClass"] = vol.offset_class
        if ext:
            data["ExtensionProperties"] = ext

        return {
            "kind": KIND_SEISMIC_TRACE_DATA,
            "id": self._wpc_record_id(vol.wpc_id),
            "acl": self.client.instance.acl,
            "legal": self.client.instance.legal,
            "data": data,
        }

    def build_bingrid_record(self) -> dict:
        """Build a SeismicBinGrid WPC record."""
        bg = self.survey.bingrid
        s = self.survey.seismic
        data: Dict[str, Any] = {
            "Name": bg.name,
            "Description": bg.description or f"Seismic bin grid: {bg.name}",
            "ExistenceKind": f"{self.partition}:reference-data--ExistenceKind:{self.survey.existence_kind}:",
            "InlineMin": bg.inline_min if bg.inline_min is not None else s.inline_min,
            "InlineMax": bg.inline_max if bg.inline_max else s.inline_max,
            "CrosslineMin": bg.crossline_min if bg.crossline_min is not None else s.crossline_min,
            "CrosslineMax": bg.crossline_max if bg.crossline_max else s.crossline_max,
            "InlineBinCount": bg.inline_bin_count,
            "CrosslineBinCount": bg.crossline_bin_count,
            "InlineBinIncrement": 1,
            "CrosslineBinIncrement": 1,
            "InlineBinWidth": bg.inline_bin_width,
            "CrosslineBinWidth": bg.crossline_bin_width,
            "P6BinGridOriginEasting": bg.origin_easting,
            "P6BinGridOriginNorthing": bg.origin_northing,
            "P6BinGridOriginI": bg.origin_i,
            "P6BinGridOriginJ": bg.origin_j,
            "P6BinNodeIncrementOnIaxis": bg.node_increment_i,
            "P6BinNodeIncrementOnJaxis": bg.node_increment_j,
            "P6TransformationMethod": bg.transformation_method,
        }

        crs_id = self._crs_id()
        if crs_id:
            data["CoordinateReferenceSystemID"] = crs_id
        if self.survey.spatial_area:
            data["SpatialArea"] = self.survey.spatial_area

        return {
            "kind": KIND_SEISMIC_BINGRID,
            "id": self._bingrid_record_id(),
            "acl": self.client.instance.acl,
            "legal": self.client.instance.legal,
            "data": data,
        }

    # ── Main execution ───────────────────────────────────────────────────

    def run(
        self,
        *,
        dry_run: bool = False,
        skip_upload: bool = False,
        upload_segy: bool = False,
        convert: bool = False,
        src_dir: Path | None = None,
        vds_dir: Path | None = None,
    ) -> list[dict]:
        """
        Execute the full ingest pipeline.

        Returns the list of records that were built (and pushed unless dry_run).
        """
        _src_dir = src_dir or (Path(self.survey.src_dir) if self.survey.src_dir else None)
        _vds_dir = vds_dir or (Path(self.survey.vds_dir) if self.survey.vds_dir else None)

        print("═" * 64)
        print(f"  Seismic VDS → OSDU")
        print(f"  Host:      {self.client.instance.host}")
        print(f"  Partition: {self.partition}")
        print(f"  Volumes:   {len(self.survey.volumes)}")
        print(f"  BinGrid:   {self.survey.bingrid.id}")
        print("═" * 64)

        # Convert if requested
        if convert and _src_dir and _vds_dir:
            print("\n=== Convert SEG-Y → OpenVDS ===")
            uom = self.survey.seismic.trace_uom
            for vol in self.survey.volumes:
                sgy_path = _src_dir / vol.segy_file
                vds_path = _vds_dir / vol.vds_file
                if not sgy_path.exists():
                    sys.exit(f"  ✗ SEG-Y not found: {sgy_path}")
                if not self.convert_segy_to_vds(sgy_path, vds_path, uom):
                    sys.exit(f"  ✗ Conversion failed for {vol.segy_file}")

        # Build records
        wpc_records = []
        for vol in self.survey.volumes:
            print(f"\n--- {vol.display_name} ---")

            segy_record_id = self._dataset_record_id("FileCollection.SEGY", vol.segy_dataset_id)
            vds_record_id = self._dataset_record_id("FileCollection.Bluware.OpenVDS", vol.vds_dataset_id)

            if dry_run or skip_upload:
                print("  (skipping upload)")
            else:
                if not _src_dir or not _vds_dir:
                    sys.exit("  ✗ src_dir and vds_dir required for upload (set in config or CLI)")

                if upload_segy:
                    print("  [SEG-Y upload]")
                    sgy_path = _src_dir / vol.segy_file
                    uploaded = self.upload_file_collection(
                        sgy_path, segy_record_id, KIND_FILE_COLLECTION_SEGY,
                        f"SEG-Y {vol.display_name}",
                        f"Original SEG-Y: {vol.display_name}",
                    )
                    if not uploaded:
                        print(f"  ✗ SEG-Y upload failed for {vol.segy_file}")
                        continue
                    segy_record_id = uploaded
                else:
                    print(f"  Reusing SEG-Y dataset: {segy_record_id}")

                # Upload VDS
                print("  [OpenVDS upload]")
                vds_path = _vds_dir / vol.vds_file
                vds_collection_path = f"sd://{self.partition}/{vol.vds_dataset_id}"
                uploaded_vds = self.upload_file_collection(
                    vds_path, vds_record_id, KIND_FILE_COLLECTION_VDS,
                    f"OpenVDS {vol.display_name}",
                    f"OpenVDS converted: {vol.display_name}",
                    collection_path=vds_collection_path,
                )
                if not uploaded_vds:
                    print(f"  ✗ VDS upload failed for {vol.vds_file}")
                    continue
                vds_record_id = uploaded_vds

            wpc_records.append(
                self.build_seismic_trace_data_record(vol, segy_record_id, vds_record_id)
            )

        if not wpc_records:
            sys.exit("No records built – aborting")

        # Prepend BinGrid record
        wpc_records.insert(0, self.build_bingrid_record())

        if dry_run:
            print("\n" + json.dumps(wpc_records, indent=2))
            return wpc_records

        # Push to Storage
        print(f"\n=== Push {len(wpc_records)} record(s) to Storage ===")
        result = self.client.put_records(wpc_records)
        stored = result.get("recordIds", [])
        print(f"  ✓ Stored {len(stored)} record(s)")

        print("\n" + "═" * 64)
        print("Done.")
        return wpc_records


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="Generic seismic OpenVDS ingestion into OSDU.\n"
                    "Supports two modes:\n"
                    "  1. JSON config:  ingest_seismic_vds config.json instance\n"
                    "  2. Auto-scan:    ingest_seismic_vds --scan file.sgy instance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("config", nargs="?", default=None,
                    help="Path to survey JSON config file (omit if using --scan)")
    ap.add_argument("instance", help="Target OSDU instance name (e.g. interop, eqndev)")
    ap.add_argument("--scan", type=Path, default=None, metavar="FILE",
                    help="Auto-scan metadata from a .sgy or VDS directory (no config needed)")
    ap.add_argument("--scan-vds", type=Path, default=None, metavar="DIR",
                    help="Also scan a VDS directory (used with --scan for best results)")
    ap.add_argument("--name", default="",
                    help="Display name override (with --scan)")
    ap.add_argument("--convert", action="store_true",
                    help="Run SEGYImport to convert .sgy → .vds before upload")
    ap.add_argument("--skip-upload", action="store_true",
                    help="Skip file upload, only create WPC records")
    ap.add_argument("--upload-segy", action="store_true",
                    help="Also upload SEG-Y dataset records")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print records — no remote calls")
    ap.add_argument("--src-dir", type=Path, default=None,
                    help="Override src_dir from config (directory with .sgy files)")
    ap.add_argument("--vds-dir", type=Path, default=None,
                    help="Override vds_dir from config (directory with VDS outputs)")
    ap.add_argument("--legal-tag", default="",
                    help="Override legal tag (e.g. opendes-default-legal-tag)")
    ap.add_argument("--owners", nargs="*", default=None,
                    help="Override ACL owners (space-separated)")
    ap.add_argument("--viewers", nargs="*", default=None,
                    help="Override ACL viewers (space-separated)")
    ap.add_argument("--save-config", type=Path, default=None, metavar="OUT.json",
                    help="Save the scanned config to a JSON file (with --scan)")
    args = ap.parse_args()

    # Determine survey config source
    if args.scan:
        segy_path = args.scan if args.scan.suffix.lower() in (".sgy", ".segy") else None
        vds_path = args.scan if not segy_path else args.scan_vds
        if not segy_path and not vds_path:
            vds_path = args.scan  # assume it's a VDS directory
        survey = survey_from_scan(
            segy_path=segy_path,
            vds_path=vds_path or args.scan_vds,
            name=args.name,
        )
        # Optionally save the generated config
        if args.save_config:
            _save_survey_config(survey, args.save_config)
            print(f"\n  ✓ Config saved to {args.save_config}")
    elif args.config:
        survey = load_survey_config(args.config)
    else:
        ap.error("Provide a config JSON file or use --scan <file>")

    ingestor = SeismicVdsIngestor.from_instance_name(
        args.instance, survey,
        legal_tag=args.legal_tag,
        owners=args.owners,
        viewers=args.viewers,
    )
    ingestor.run(
        dry_run=args.dry_run,
        skip_upload=args.skip_upload,
        upload_segy=args.upload_segy,
        convert=args.convert,
        src_dir=args.src_dir,
        vds_dir=args.vds_dir,
    )


def _save_survey_config(survey: SurveyConfig, path: Path):
    """Serialize a SurveyConfig to JSON for later reuse."""
    from dataclasses import asdict
    data = asdict(survey)
    # Restructure: move instance fields into nested object
    inst_keys = ("legal_tag", "owners", "viewers", "countries")
    inst = {k: data.pop(k) for k in inst_keys if data.get(k)}
    if inst:
        data["instance"] = inst
    path.write_text(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
