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
echo ""
echo "Intake Gate running on http://127.0.0.1:8000   (backend: $LLM_BACKEND)"
echo ""
exec uvicorn app.main:app --host 127.0.0.1 --port 8000
