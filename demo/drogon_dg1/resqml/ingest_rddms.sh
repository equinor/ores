#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# ingest_rddms.sh - Import Drogon RESQML EPC files into OSDU RDDMS
#
# Uses Docker ETP client (same pattern as RDDMS bootcamp notebook 10.3).
#
# Prerequisites:
#   - Docker running
#   - Image tagged as 'open-etp-sslclient'
#   - .env file at repo root
#
# Usage:
#   ./demo/drogon_dg1/resqml/ingest_rddms.sh
#   ./demo/drogon_dg1/resqml/ingest_rddms.sh --dry-run
#   ./demo/drogon_dg1/resqml/ingest_rddms.sh --dataspace "maap/my_test"
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

DATASPACE_NAME="maap/drogon_dg"
DRY_RUN=false
SKIP_CREATE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dataspace) DATASPACE_NAME="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --skip-create) SKIP_CREATE=true; shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# ── Load .env ──────────────────────────────────────────────────────────────
ENV_FILE="$REPO_ROOT/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: .env not found at $ENV_FILE" >&2
  exit 1
fi

get_env() {
  for key in "$@"; do
    val=$(grep -m1 "^${key}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | sed 's/^["'\'']\|["'\''"]$//g')
    if [[ -n "$val" ]]; then echo "$val"; return; fi
  done
}

OSDU_BASE_URL=$(get_env OSDU_HOST OSDU_BASE_URL)
DATA_PARTITION_ID=$(get_env DATA_PARTITION_ID OSDU_PARTITION)
AZURE_TENANT_ID=$(get_env AZURE_TENANT_ID OSDU_TENANT_ID)
AZURE_CLIENT_ID=$(get_env AZURE_CLIENT_ID OSDU_CLIENT_ID)
AZURE_SCOPE=$(get_env AZURE_SCOPE OSDU_SCOPE)
REFRESH_TOKEN=$(get_env refresh_token REFRESH_TOKEN)
LEGAL_TAG=$(get_env DEFAULT_LEGAL_TAG)
LEGAL_TAG="${LEGAL_TAG:-${DATA_PARTITION_ID}-equinor-private-default}"

ETP_URL="wss://${OSDU_BASE_URL}/api/reservoir-ddms-etp/v2/"
DOCKER_IMAGE="open-etp-sslclient"

echo "=== Configuration ==="
echo "  Host:       $OSDU_BASE_URL"
echo "  Partition:  $DATA_PARTITION_ID"
echo "  ETP URL:    $ETP_URL"
echo "  Dataspace:  $DATASPACE_NAME"
echo "  Image:      $DOCKER_IMAGE"
echo ""

# ── Authenticate ───────────────────────────────────────────────────────────
echo "=== Authenticate ==="
TOKEN_URL="https://login.microsoftonline.com/${AZURE_TENANT_ID}/oauth2/v2.0/token"
TOKEN=$(curl -s -X POST "$TOKEN_URL" \
  -d "grant_type=refresh_token&client_id=${AZURE_CLIENT_ID}&refresh_token=${REFRESH_TOKEN}&scope=${AZURE_SCOPE}" \
  -H "Content-Type: application/x-www-form-urlencoded" | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "  Token acquired"
echo ""

# ── Build ETP credentials ─────────────────────────────────────────────────
ETP_CREDS="--server-url $ETP_URL --data-partition-id $DATA_PARTITION_ID --auth bearer --jwt-token $TOKEN"
SPACE_CMD="/bin/openETPServer space $ETP_CREDS"

# ── Copy EPC+H5 files to temp dir ─────────────────────────────────────────
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

for name in drogon_tables.epc drogon_tables.h5 drogon_activity.epc drogon_activity.h5; do
  src="$SCRIPT_DIR/$name"
  if [[ -f "$src" ]]; then
    cp "$src" "$TEMP_DIR/"
    echo "  Copied $name"
  else
    echo "  WARNING: $name not found at $src"
  fi
done
echo ""

# ── Step 1: List dataspaces ────────────────────────────────────────────────
echo "=== Step 1: List dataspaces ==="
if [[ "$DRY_RUN" == "true" ]]; then
  echo "  [DRY-RUN] would list dataspaces"
else
  docker run --rm --entrypoint=sh "$DOCKER_IMAGE" -c "$SPACE_CMD space --list" || true
fi
echo ""

# ── Step 2: Create dataspace ──────────────────────────────────────────────
if [[ "$SKIP_CREATE" == "false" ]]; then
  echo "=== Step 2: Delete + re-create dataspace '$DATASPACE_NAME' ==="
  DOMAIN="${DATA_PARTITION_ID}.dataservices.energy"
  XDATA="{\"legaltags\":[\"${LEGAL_TAG}\"],\"otherRelevantDataCountries\":[\"NO\"],\"owners\":[\"data.default.owners@${DOMAIN}\"],\"viewers\":[\"data.default.viewers@${DOMAIN}\"]}"

  if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [DRY-RUN] would delete + create dataspace"
  else
    docker run --rm --entrypoint=sh "$DOCKER_IMAGE" -c "$SPACE_CMD space --delete -s $DATASPACE_NAME" 2>/dev/null || true
    sleep 2
    docker run --rm --entrypoint=sh "$DOCKER_IMAGE" -c "$SPACE_CMD space --new -s $DATASPACE_NAME --xdata '$XDATA'"
  fi
  echo ""
else
  echo "=== Step 2: Skipping dataspace creation ==="
  echo ""
fi

# ── Step 3: Import EPC files ──────────────────────────────────────────────
echo "=== Step 3: Import EPC files ==="
for epc_name in drogon_tables.epc drogon_activity.epc; do
  if [[ ! -f "$TEMP_DIR/$epc_name" ]]; then
    echo "  ERROR: $epc_name not found — run gen_resqml.py first" >&2
    exit 1
  fi

  echo "  Importing $epc_name ..."
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [DRY-RUN] would import $epc_name"
  else
    docker run --rm -v "${TEMP_DIR}:/data" --entrypoint=sh "$DOCKER_IMAGE" \
      -c "$SPACE_CMD space -s $DATASPACE_NAME --import-epc /data/$epc_name"
    if [[ $? -ne 0 ]]; then
      echo "  ERROR: import of $epc_name failed" >&2
      exit 1
    fi
  fi
done
echo ""

echo "=== RDDMS ingest complete ==="
