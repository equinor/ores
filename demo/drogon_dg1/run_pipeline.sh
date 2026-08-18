#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# run_pipeline.sh - Drogon DG1 end-to-end OSDU pipeline
#
# Pipeline: CSV → manifests → records → Storage API ingestion
#
# Usage:
#   ./demo/drogon_dg1/run_pipeline.sh                  # full pipeline
#   ./demo/drogon_dg1/run_pipeline.sh --skip-ingest    # generate only
#   ./demo/drogon_dg1/run_pipeline.sh --skip-split     # skip CSV split
#   ./demo/drogon_dg1/run_pipeline.sh --delay 5        # custom delay
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

SKIP_SPLIT=false
SKIP_INGEST=false
DELAY=3

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-split) SKIP_SPLIT=true; shift ;;
    --skip-ingest) SKIP_INGEST=true; shift ;;
    --delay) DELAY="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# ── Step 0: Split raw CSV into volumes + parameters ─────────────
if [[ "$SKIP_SPLIT" == "false" ]]; then
  echo -e "\n═══ Step 0: Split CSV ═══"
  python demo/drogon_dg1/split_valysar.py
else
  echo -e "\n═══ Step 0: Split CSV (skipped) ═══"
fi

# ── Step 0b: Generate reference data ──
echo -e "\n═══ Step 0b: Reference data ═══"
python demo/drogon_dg1/genrefpropertytypes_drogon.py
python demo/drogon_dg1/genreffacetrole_drogon.py

# ── Step 1: Generate master data (Reservoir + Segments + WP) ────
echo -e "\n═══ Step 1: Master data ═══"
python demo/drogon_dg1/genmaster_drogon.py

# ── Step 2: Generate RAW volumes WPC ────────────────────────────
echo -e "\n═══ Step 2: RAW volumes WPC ═══"
python demo/drogon_dg1/genrawmanifest_drogon.py

# ── Step 3: Generate statistics WPC ─────────────────────────────
echo -e "\n═══ Step 3: Statistics WPC ═══"
python demo/drogon_dg1/genstatmanifest_drogon.py

# ── Step 4: Generate parameters ColumnBasedTable WPC ────────────
echo -e "\n═══ Step 4: Parameters WPC ═══"
python demo/drogon_dg1/genparamsmanifest_drogon.py

# ── Step 5: Generate Risk ───────────────────────────────────────
echo -e "\n═══ Step 5: Risk ═══"
python demo/drogon_dg1/gen_risk_drogon.py

# ── Step 5b: Generate Activity ───────────────────────────────────
echo -e "\n═══ Step 5b: Activity ═══"
python demo/drogon_dg1/gen_activity_drogon.py

# ── Step 5c: Generate DevelopmentConcept WPC ─────────────────────
echo -e "\n═══ Step 5c: DevelopmentConcept WPC ═══"
python demo/drogon_dg1/gen_devconcept_drogon.py

# ── Step 6: Generate Business Decision ──────────────────────────
echo -e "\n═══ Step 6: Business Decision ═══"
python demo/drogon_dg1/gen_businessdecision_drogon.py

# ── Step 7: Split manifests → individual record files ───────────
echo -e "\n═══ Step 7: Manifests → records ═══"
rm -f demo/drogon_dg1/records/*.json
python demo/drogon_dg1/manifest2records_drogon.py

if [[ "$SKIP_INGEST" == "true" ]]; then
  echo -e "\n═══ Ingestion skipped ═══"
  echo "  Run manually: python demo/drogon_dg1/ingest_records_batch.py --delay $DELAY"
  exit 0
fi

# ── Step 8: Ingest via Storage API ──────────────────────────────
echo -e "\n═══ Step 8: Storage API ingestion ═══"
python demo/drogon_dg1/ingest_records_batch.py --delay "$DELAY"

echo -e "\n═══ DG1 Pipeline complete ═══"
