#!/usr/bin/env bash
# Start the Streamlit dashboard and expose it publicly via ngrok.
#
# Usage:
#   scripts/serve_dashboard.sh [PORT]
#
# Env:
#   NGROK_AUTHTOKEN   optional — passed to `ngrok config add-authtoken` once.
#   NGROK_DOMAIN      optional — if set, ngrok reserves this static domain.

set -euo pipefail

PORT="${1:-8501}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$REPO_ROOT/logs"
mkdir -p "$LOG_DIR"

STREAMLIT_LOG="$LOG_DIR/streamlit.log"
NGROK_LOG="$LOG_DIR/ngrok.log"

cleanup() {
  local code=$?
  echo
  echo "[serve_dashboard] shutting down..."
  [[ -n "${STREAMLIT_PID:-}" ]] && kill "$STREAMLIT_PID" 2>/dev/null || true
  [[ -n "${NGROK_PID:-}" ]] && kill "$NGROK_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  exit "$code"
}
trap cleanup EXIT INT TERM

if ! command -v ngrok >/dev/null 2>&1; then
  echo "[serve_dashboard] ngrok not found on PATH" >&2
  exit 1
fi

if [[ -n "${NGROK_AUTHTOKEN:-}" ]]; then
  ngrok config add-authtoken "$NGROK_AUTHTOKEN" >/dev/null
fi

cd "$REPO_ROOT"

echo "[serve_dashboard] starting Streamlit on :$PORT (log: $STREAMLIT_LOG)"
uv run streamlit run src/dashboard/app.py \
  --server.port "$PORT" \
  --server.address 127.0.0.1 \
  --server.headless true \
  --browser.gatherUsageStats false \
  >"$STREAMLIT_LOG" 2>&1 &
STREAMLIT_PID=$!

# Wait until Streamlit is accepting connections.
echo "[serve_dashboard] waiting for Streamlit to come up..."
for _ in {1..60}; do
  if curl -sf "http://127.0.0.1:$PORT/_stcore/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
if ! curl -sf "http://127.0.0.1:$PORT/_stcore/health" >/dev/null 2>&1; then
  echo "[serve_dashboard] Streamlit did not come up; see $STREAMLIT_LOG" >&2
  exit 1
fi
echo "[serve_dashboard] Streamlit up (pid $STREAMLIT_PID)"

NGROK_ARGS=(http "$PORT" --log=stdout)
if [[ -n "${NGROK_DOMAIN:-}" ]]; then
  NGROK_ARGS+=(--domain="$NGROK_DOMAIN")
fi

echo "[serve_dashboard] starting ngrok (log: $NGROK_LOG)"
ngrok "${NGROK_ARGS[@]}" >"$NGROK_LOG" 2>&1 &
NGROK_PID=$!

# ngrok exposes a local API on 4040; poll it for the public URL.
PUBLIC_URL=""
for _ in {1..40}; do
  PUBLIC_URL="$(curl -sf http://127.0.0.1:4040/api/tunnels 2>/dev/null \
    | python3 -c 'import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    sys.exit(0)
for t in d.get("tunnels", []):
    u=t.get("public_url","")
    if u.startswith("https://"):
        print(u); break
' || true)"
  if [[ -n "$PUBLIC_URL" ]]; then
    break
  fi
  sleep 0.5
done

if [[ -z "$PUBLIC_URL" ]]; then
  echo "[serve_dashboard] ngrok tunnel did not register; see $NGROK_LOG" >&2
  exit 1
fi

echo
echo "================================================================"
echo "  Dashboard:   http://127.0.0.1:$PORT"
echo "  Public URL:  $PUBLIC_URL"
echo "  ngrok UI:    http://127.0.0.1:4040"
echo "================================================================"
echo "Ctrl-C to stop both processes."

wait "$STREAMLIT_PID" "$NGROK_PID"
