#!/usr/bin/env bash
# Start the Streamlit dashboard bound to localhost only (no ngrok).
#
# Usage:
#   scripts/serve_dashboard_local.sh [PORT]
#
# Use scripts/serve_dashboard.sh if you also want a public ngrok URL.

set -euo pipefail

PORT="${1:-8501}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$REPO_ROOT"

echo "[serve_dashboard_local] http://127.0.0.1:$PORT"
exec uv run streamlit run src/dashboard/app.py \
  --server.port "$PORT" \
  --server.address 127.0.0.1 \
  --browser.gatherUsageStats false
