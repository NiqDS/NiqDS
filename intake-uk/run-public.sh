#!/usr/bin/env bash
# Make the backend reachable from your phone over the public internet, now.
#
# This starts the app locally and opens a public HTTPS tunnel to it with
# Cloudflare Tunnel (a "quick tunnel" — no account, no domain). It prints a
# https://<random>.trycloudflare.com address. Type that address into the iOS app
# (or open it in the phone browser) and the app is alive — from any network, not
# just your Wi-Fi.
#
# This is the bridge until you deploy to a permanent host (see docs/setup/deploy.md).
#
# Usage:
#   ./run-public.sh                 # offline mock backend (photos flagged as blurry)
#   LLM_BACKEND=anthropic ANTHROPIC_API_KEY=sk-ant-... ./run-public.sh   # reads photos
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
PY="./.venv/bin/python"
[ -x "$PY" ] || PY="python3"

# Served over HTTPS (via the tunnel) -> mark session cookies Secure.
export INTAKE_SESSION_SECURE="${INTAKE_SESSION_SECURE:-1}"

if ! command -v cloudflared >/dev/null 2>&1; then
  cat <<'MSG'
cloudflared is not installed — it creates the public HTTPS link.

Install it:
  macOS:         brew install cloudflared
  Debian/Ubuntu: see https://pkg.cloudflare.com  (or download the binary)
  Any OS:        https://github.com/cloudflare/cloudflared/releases

Prefer ngrok instead? Run the app with ./run.sh, then in another terminal:
  ngrok http 8000
and use the https://<id>.ngrok-free.app address it prints.
MSG
  exit 1
fi

echo "Starting the backend on 127.0.0.1:${PORT} (backend: ${LLM_BACKEND:-mock})…"
"$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning &
APP_PID=$!
cleanup() { kill "$APP_PID" "${CF_PID:-}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# Wait for the app to answer before exposing it.
for _ in $(seq 1 30); do
  curl -sf "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1 && break
  sleep 0.5
done

echo
echo "Opening a public HTTPS tunnel… the https://…trycloudflare.com link below is"
echo "what you type into the iOS app (Settings → server URL) or your phone browser."
echo "Press Ctrl+C to stop (the link dies with it)."
echo "──────────────────────────────────────────────────────────────────────────────"
cloudflared tunnel --url "http://127.0.0.1:${PORT}" &
CF_PID=$!
wait "$CF_PID"
