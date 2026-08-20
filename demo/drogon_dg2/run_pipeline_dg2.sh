#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# run_pipeline_dg2.sh - Drogon DG2 (Concept Select) end-to-end pipeline
#
# DEPRECATED - Use the generic Python pipeline runner instead:
#   python demo/run_pipeline.py drogon_dg2
#
# Pre-requisite: DG1 pipeline has been run.
#
# Pipeline:
#   DG2 params (×0.8) → DG2 raw volumes (×0.8) → DG2 statistics →
#   DG2 activity → DG2 risks → DG2 documents → DG2 BD →
#   records → ingestion
#
# Usage:
#   ./demo/drogon_dg2/run_pipeline_dg2.sh              # full pipeline
#   ./demo/drogon_dg2/run_pipeline_dg2.sh --skip-ingest # generate only
#   ./demo/drogon_dg2/run_pipeline_dg2.sh --delay 5    # custom delay
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

SKIP_INGEST=false
DELAY=3

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-ingest) SKIP_INGEST=true; shift ;;
    --delay) DELAY="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# ── Pre-check: verify DG1 shared manifests exist ────────────────
echo -e "\n═══ Pre-check: DG1 shared manifests ═══"
if [[ ! -f demo/drogon_dg1/manifest_masterwp_drogon.json ]]; then
  echo "ERROR: DG1 manifest missing - run DG1 pipeline first" >&2
  exit 1
fi
echo "  OK manifest_masterwp_drogon.json"

# ── Step 1: Generate DG2 Parameters (porosity ×0.8) ──────────────
echo -e "\n═══ Step 1: DG2 Parameters (porosity ×0.8) ═══"
python demo/drogon_dg2/genparamsmanifest_dg2.py

# ── Step 2: Generate DG2 Raw Volumes (pore volumes ×0.8) ──────
echo -e "\n═══ Step 2: DG2 Raw Volumes (×0.8) ═══"
python demo/drogon_dg2/genrawmanifest_dg2.py

# ── Step 3: Generate DG2 Statistics ───────────────────────────
echo -e "\n═══ Step 3: DG2 Statistics ═══"
python demo/drogon_dg2/genstatmanifest_dg2.py

# ── Step 4: Generate DG2 Activity ───────────────────────────
echo -e "\n═══ Step 4: DG2 Activity ═══"
python demo/drogon_dg2/gen_activity_dg2.py

# ── Step 5: Generate DG2 Risks ──────────────────────────────
echo -e "\n═══ Step 5: DG2 Risks ═══"
python demo/drogon_dg2/gen_risk_dg2.py

# ── Step 6: Generate DG2 Documents ────────────────────────────
echo -e "\n═══ Step 6: DG2 Documents ═══"
python demo/drogon_dg2/gen_documents_dg2.py

# ── Step 6b: Generate DG2 DevelopmentConcept WPC ────────────────
echo -e "\n═══ Step 6b: DG2 DevelopmentConcept WPC ═══"
python demo/drogon_dg2/gen_devconcept_dg2.py

# ── Step 6c: Generate DG2 GeoLabelSet ─────────────────────────
echo -e "\n═══ Step 6c: DG2 GeoLabelSet ═══"
python demo/drogon_dg2/gengeolabelset_dg2.py

# ── Step 6d: Generate DG2 Evidence Package ─────────────────────
echo -e "\n═══ Step 6d: DG2 Evidence Package ═══"
python demo/drogon_dg2/gen_collection_dg2.py

# ── Step 7: Generate DG2 Business Decision ────────────────────
echo -e "\n═══ Step 7: DG2 Business Decision ═══"
python demo/drogon_dg2/gen_businessdecision_dg2.py

# ── Step 8: Split manifests → individual record files ─────────
echo -e "\n═══ Step 8: Manifests → records ═══"
rm -f demo/drogon_dg2/records/*.json
python demo/drogon_dg2/manifest2records_dg2.py

if [[ "$SKIP_INGEST" == "true" ]]; then
  echo -e "\n═══ Ingestion skipped ═══"
  echo "  Run manually: python demo/drogon_dg2/ingest_records_batch.py --delay $DELAY"
  exit 0
fi

# ── Step 9: Ingest via Storage API ─────────────────────────────
echo -e "\n═══ Step 9: Storage API ingestion ═══"
python demo/drogon_dg2/ingest_records_batch.py --delay "$DELAY"

echo -e "\n═══ DG2 Pipeline complete ═══"
