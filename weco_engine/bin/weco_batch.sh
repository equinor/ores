#!/usr/bin/env bash
# weco_batch.sh — Shell wrapper for WeCo batch correlation workflow
#
# Usage:
#   bin/weco_batch.sh config.json
#   bin/weco_batch.sh config.json -v -o /tmp/output
#
# The JSON config drives the full import → configure → run → export pipeline.
# See ``python -m weco.batch --help`` for details.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Activate venv if present
if [[ -f "$PROJECT_ROOT/.venv/bin/activate" ]]; then
    source "$PROJECT_ROOT/.venv/bin/activate"
elif [[ -f "$HOME/.venv/bin/activate" ]]; then
    source "$HOME/.venv/bin/activate"
fi

exec python -m weco.batch "$@"
