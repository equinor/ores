#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# run_resqml_pipeline.sh - Drogon RESQML pipeline (generate + ingest)
#
# 1. Runs gen_resqml.py to create EPC files
# 2. Runs ingest_rddms.sh to import EPCs into OSDU Reservoir DDMS
#
# Usage:
#   ./demo/drogon_dg1/resqml/run_resqml_pipeline.sh
#   ./demo/drogon_dg1/resqml/run_resqml_pipeline.sh --skip-generate
#   ./demo/drogon_dg1/resqml/run_resqml_pipeline.sh --skip-ingest
#   ./demo/drogon_dg1/resqml/run_resqml_pipeline.sh --dataspace "maap/my_test" --dry-run
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

DATASPACE_NAME="maap/drogon_dg"
SKIP_GENERATE=false
SKIP_INGEST=false
SKIP_CREATE=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dataspace) DATASPACE_NAME="$2"; shift 2 ;;
    --skip-generate) SKIP_GENERATE=true; shift ;;
    --skip-ingest) SKIP_INGEST=true; shift ;;
    --skip-create) SKIP_CREATE=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
DROGON_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║        Drogon RESQML Pipeline (generate + ingest)       ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Generate RESQML EPC files ─────────────────────────────────────
if [[ "$SKIP_GENERATE" == "false" ]]; then
  echo "┌─────────────────────────────────────────┐"
  echo "│  Step 1/2: Generate RESQML EPC files    │"
  echo "└─────────────────────────────────────────┘"
  echo ""

  GEN_SCRIPT="$DROGON_DIR/gen_resqml.py"
  if [[ ! -f "$GEN_SCRIPT" ]]; then
    echo "ERROR: gen_resqml.py not found at $GEN_SCRIPT" >&2
    exit 1
  fi

  cd "$REPO_ROOT"
  python "$GEN_SCRIPT"
  echo ""
else
  echo "  Skipping RESQML generation (--skip-generate)"
  echo ""
fi

# ── Step 2: Ingest to RDDMS ──────────────────────────────────────────────
if [[ "$SKIP_INGEST" == "false" ]]; then
  echo "┌─────────────────────────────────────────┐"
  echo "│  Step 2/2: Ingest EPCs to RDDMS         │"
  echo "└─────────────────────────────────────────┘"
  echo ""

  INGEST_SCRIPT="$SCRIPT_DIR/ingest_rddms.sh"
  if [[ ! -f "$INGEST_SCRIPT" ]]; then
    echo "ERROR: ingest_rddms.sh not found at $INGEST_SCRIPT" >&2
    exit 1
  fi

  INGEST_ARGS=(--dataspace "$DATASPACE_NAME")
  [[ "$SKIP_CREATE" == "true" ]] && INGEST_ARGS+=(--skip-create)
  [[ "$DRY_RUN" == "true" ]] && INGEST_ARGS+=(--dry-run)

  bash "$INGEST_SCRIPT" "${INGEST_ARGS[@]}"
else
  echo "  Skipping RDDMS ingest (--skip-ingest)"
  echo ""
fi

echo ""
echo "Pipeline complete."
