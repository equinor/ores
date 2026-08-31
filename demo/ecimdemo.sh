#!/usr/bin/env bash
# ecimdemo.sh — Launch ORES locally against interop OSDU + local etp-client
#
# Architecture:
#   ORES :8000 (uvicorn, local)
#     ├── OSDU catalog/auth → admeinterop.energy.azure.com (client_credentials)
#     └── RDDMS REST+GraphQL → local etp-client :8080
#                                 └── ETP WebSocket → interop ETP server (wss)
#
# The local M27 etp-client proxies to interop's ETP server over WebSocket,
# which means array reads, GraphQL deep search, and statistics all work —
# even though interop's REST API alone doesn't expose arrays.
#
# Usage:
#   ./demo/ecimdemo.sh              # start ORES + etp-client
#   ./demo/ecimdemo.sh --no-client  # ORES only (etp-client already running)
#
set -euo pipefail
cd "$(dirname "$0")/.."
REPO_ROOT="$PWD"

# ─── Load secrets from k8s/secret.yaml + configmap via env_from_k8s ──────── #
eval "$(python3 k8s/env_from_k8s.py 2>/dev/null)" || true

# ─── Ports ────────────────────────────────────────────────────────────────── #
ORES_PORT=8000
RDDMS_PORT=8080
RDDMS_ROOT="$HOME/rddms"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

echo -e "${BOLD}"
echo "┌─────────────────────────────────────────────────────────┐"
echo "│  ECIM Demo — ORES + etp-client → interop ETP           │"
echo "│                                                         │"
echo "│  Web UI        http://127.0.0.1:${ORES_PORT}                     │"
echo "│  etp-client    http://localhost:${RDDMS_PORT}                    │"
echo "│  ETP target    wss://admeinterop.energy.azure.com       │"
echo "│  OSDU catalog  https://admeinterop.energy.azure.com     │"
echo "└─────────────────────────────────────────────────────────┘"
echo -e "${NC}"

# ─── Parse flags ──────────────────────────────────────────────────────────── #
START_CLIENT=true
for arg in "$@"; do
    case "$arg" in
        --no-client) START_CLIENT=false ;;
    esac
done

# ─── Kill previous processes on our ports ─────────────────────────────────── #
for p in $ORES_PORT $RDDMS_PORT; do
    old_pids=$(lsof -ti tcp:$p 2>/dev/null || true)
    if [[ -n "$old_pids" ]]; then
        echo "⟳ Killing previous process on port $p"
        echo "$old_pids" | xargs kill -9 2>/dev/null || true
    fi
done
sleep 0.3

# ─── Start etp-client pointed at interop's ETP server ────────────────────── #
if $START_CLIENT; then
    if [[ ! -f "$RDDMS_ROOT/dist/src/lib/restApi/RestServer.js" ]]; then
        echo -e "${RED}✗ etp-client not built — run: cd ~/rddms && npm run build${NC}"
        exit 1
    fi

    echo -e "${CYAN}→${NC} Starting etp-client on :${RDDMS_PORT} → interop ETP..."
    cd "$RDDMS_ROOT"

    # Point at interop's ETP server (WebSocket), not Docker
    RDMS_ETP_SSL=true \
    RDMS_ETP_PROTOCOL=wss \
    RDMS_ETP_HOST=admeinterop.energy.azure.com \
    RDMS_ETP_PORT=443 \
    RDMS_ETP_PATH="/api/reservoir-ddms-etp/v2" \
    RDMS_REST_PORT="${RDDMS_PORT}" \
    RDMS_REST_ROOT_PATH="/api/reservoir-ddms/v2/" \
    RDMS_DATA_PARTITION_MODE=single \
    RDMS_DATA_PARTITION_ID=opendes \
    RDMS_OSDU_URL="https://admeinterop.energy.azure.com" \
    RDMS_SSL_VERIFY=false \
    nohup node dist/src/lib/restApi/RestServer.js > /tmp/ecimdemo-client.log 2>&1 &
    echo $! > /tmp/ecimdemo-client.pid

    echo -n "  Waiting for etp-client"
    for i in $(seq 1 20); do
        if curl -sf http://localhost:${RDDMS_PORT}/api/reservoir-ddms/v2/health/readiness >/dev/null 2>&1; then
            echo ""
            echo -e "${GREEN}✓${NC} etp-client on :${RDDMS_PORT} → interop ETP"
            break
        fi
        echo -n "."
        sleep 1
    done

    cd "$REPO_ROOT"
fi

# ─── ORES environment: interop instance via local etp-client ─────────────── #

# Interop OSDU credentials (for catalog search, storage, auth)
export INSTANCE_INTEROP_HOSTNAME="admeinterop.energy.azure.com"
export INSTANCE_INTEROP_DATA_PARTITION_ID="opendes"
export INSTANCE_INTEROP_AUTH_MODE="client_credentials"
# TENANT_ID, CLIENT_ID, CLIENT_SECRET, SCOPE loaded from k8s/secret.yaml above
export INSTANCE_INTEROP_AUTHORITY="osdu"
export INSTANCE_INTEROP_SCHEMA_SOURCE="wks"
export INSTANCE_INTEROP_DEFAULT_LEGAL_TAG="opendes-ReservoirDDMS-Legal-Tag"
export INSTANCE_INTEROP_DEFAULT_OWNERS="data.default.owners@opendes.dataservices.energy"
export INSTANCE_INTEROP_DEFAULT_VIEWERS="data.default.viewers@opendes.dataservices.energy"
export INSTANCE_INTEROP_DEFAULT_COUNTRIES="US"
export INSTANCE_INTEROP_SSL_VERIFY="false"

# RDDMS calls → local etp-client (which proxies to interop's ETP server)
export INSTANCE_INTEROP_RDDMS_BASE_PATH="/api/reservoir-ddms/v2"
export RDDMS_LOCAL_URL="http://localhost:${RDDMS_PORT}"

# GraphQL endpoint on local etp-client
export RDDMS_GRAPHQL_URL="http://localhost:${RDDMS_PORT}/graphql"

# Default instance
export DEFAULT_INSTANCE="interop"
export DEFAULT_DATASPACE="maap/drogon201"

# General
export LOG_LEVEL="INFO"
export DEBUG="False"
export SECRET_KEY="ecimdemo-local-dev-key"
export HTTPS_ONLY="false"

# ─── Start ORES ──────────────────────────────────────────────────────────── #
echo -e "${CYAN}→${NC} Starting ORES on :${ORES_PORT}..."
echo -e "  Instance:  interop (admeinterop.energy.azure.com)"
echo -e "  RDDMS:     http://localhost:${RDDMS_PORT} (etp-client → interop ETP)"
echo -e "  GraphQL:   ${RDDMS_GRAPHQL_URL}"
echo -e "  Dataspace: ${DEFAULT_DATASPACE}"
echo ""

cd "$REPO_ROOT"
exec "$HOME/.venv/bin/uvicorn" app.main:app \
    --host 0.0.0.0 --port "$ORES_PORT" \
    --reload --reload-dir app
