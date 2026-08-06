#!/usr/bin/env python3
"""
ingest_seismic_vds.py – Ingest Drogon seismic as OpenVDS into OSDU.

Thin wrapper around the generic ``demo.scripts.ingest_seismic_vds`` module.
Uses the Drogon config at demo/scripts/inputs/seismic_drogon.json.

Usage
-----
  python demo/drogonresqml/ingest_seismic_vds.py interop
  python demo/drogonresqml/ingest_seismic_vds.py interop --convert
  python demo/drogonresqml/ingest_seismic_vds.py interop --dry-run
  python demo/drogonresqml/ingest_seismic_vds.py interop --skip-upload
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEMO_DIR = SCRIPT_DIR.parent
REPO_ROOT = DEMO_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from demo.scripts.ingest_seismic_vds import SeismicVdsIngestor, load_survey_config  # noqa: E402

# Default paths
CONFIG_FILE = DEMO_DIR / "scripts" / "inputs" / "seismic_drogon.json"
SRC_DIR = SCRIPT_DIR / "src"
VDS_DIR = SRC_DIR / "vds"


def main():
    ap = argparse.ArgumentParser(
        description="Ingest Drogon seismic (OpenVDS) into OSDU"
    )
    ap.add_argument("instance", choices=["interop", "eqndev"],
                    help="Target OSDU instance")
    ap.add_argument("--config", type=Path, default=CONFIG_FILE,
                    help="Survey config JSON (default: seismic_drogon.json)")
    ap.add_argument("--convert", action="store_true",
                    help="Run SEGYImport to convert .sgy → .vds before upload")
    ap.add_argument("--skip-upload", action="store_true",
                    help="Skip file upload, only create WPC records")
    ap.add_argument("--upload-segy", action="store_true",
                    help="Also upload SEG-Y dataset records")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print records — no remote calls")
    args = ap.parse_args()

    survey = load_survey_config(args.config)
    ingestor = SeismicVdsIngestor.from_instance_name(args.instance, survey)
    ingestor.run(
        dry_run=args.dry_run,
        skip_upload=args.skip_upload,
        upload_segy=args.upload_segy,
        convert=args.convert,
        src_dir=SRC_DIR,
        vds_dir=VDS_DIR,
    )


if __name__ == "__main__":
    main()
