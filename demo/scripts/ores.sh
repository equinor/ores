#!/usr/bin/env bash
# demo/ores - Start ORES with local RDDMS (Docker Postgres + ETP server)
#
# Ensures the docker-compose services (postgres on 5433, etp-server on 9002)
# are running before launching the uvicorn dev server.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/demo/drogonresqml/docker-compose.yaml"

# ─── Ensure local RDDMS Docker services are running ──────────────────────── #

if ! command -v docker &>/dev/null; then
    echo "ERROR: docker is not installed or not in PATH" >&2
    exit 1
fi

# Check if the compose services are already running
if docker compose -f "$COMPOSE_FILE" ps --status running 2>/dev/null | grep -q "postgres"; then
    echo "✓ RDDMS docker services already running"
else
    echo "→ Starting RDDMS docker services (postgres + etp-server)..."
    docker compose -f "$COMPOSE_FILE" up -d
    echo "✓ RDDMS docker services started"
fi

# ─── Set GRAPHQL_PG_CONN_STRING if not already set ───────────────────────── #

export GRAPHQL_PG_CONN_STRING="${GRAPHQL_PG_CONN_STRING:-host=localhost port=5433 dbname=rddms user=foo password=bar}"

# ─── Load env vars from k8s config/secret YAMLs ──────────────────────────── #

cd "$REPO_ROOT"
eval "$(python k8s/env_from_k8s.py)"

# ─── Launch ORES ──────────────────────────────────────────────────────────── #

echo "→ Starting ORES on http://127.0.0.1:8000/"
exec python -m uvicorn app.main:app --reload --port 8000
