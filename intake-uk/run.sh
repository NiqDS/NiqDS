#!/usr/bin/env bash
# One command to start everything. Zero configuration, zero API keys — the
# default backend is the offline `mock`.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
if [ ! -d .venv ]; then
  echo "Creating virtualenv..."
  "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# Generate the synthetic fixture PDFs on first run.
if [ ! -f fixtures/documents/01_clean_invoice.pdf ]; then
  echo "Generating fixture documents..."
  python fixtures/generate.py
fi

export LLM_BACKEND="${LLM_BACKEND:-mock}"
# Bind all interfaces by default so a phone on the same Wi-Fi can reach it
# (needed to test the iOS app on a real device). Use HOST=127.0.0.1 ./run.sh to
# restrict to this machine. This is a dev server — don't expose it publicly.
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

# Best-effort LAN address, so you know what to type into the iOS app.
LAN_IP=""
if command -v ipconfig >/dev/null 2>&1; then
  LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
fi
if [ -z "$LAN_IP" ] && command -v hostname >/dev/null 2>&1; then
  LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
fi

echo ""
echo "Intake Gate — backend: $LLM_BACKEND  (binding $HOST:$PORT)"
echo "  On this Mac:        http://127.0.0.1:$PORT"
if [ -n "$LAN_IP" ]; then
  echo "  On your iPhone:     http://$LAN_IP:$PORT   ← set this in the app (gear icon)"
fi
echo ""
exec uvicorn app.main:app --host "$HOST" --port "$PORT"
