"""Runtime configuration from environment variables.

Keeps deployment knobs (data location, retention, cookie security, upload cap)
in one place so the same codebase runs locally and on a host with a persistent
volume. All values have safe local defaults.
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def _flag(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


# Where the SQLite DB, uploaded files, scans and the session secret live.
# Point INTAKE_DATA_DIR at a mounted volume in production so data survives
# container restarts/redeploys.
DATA_DIR = Path(os.environ.get("INTAKE_DATA_DIR") or (_REPO / "data")).resolve()

DB_PATH = DATA_DIR / "gate.db"
UPLOAD_DIR = DATA_DIR / "uploads"
SCAN_DIR = DATA_DIR / "scans"
SECRET_PATH = DATA_DIR / "secret.key"

# Delete uploaded/scanned files older than this many days on startup.
# 0 (default) keeps files forever. Set e.g. INTAKE_RETENTION_DAYS=30 in prod.
RETENTION_DAYS = int(os.environ.get("INTAKE_RETENTION_DAYS", "0") or "0")

# Mark session cookies Secure (HTTPS-only). Turn on in production (behind TLS).
SESSION_SECURE = _flag("INTAKE_SESSION_SECURE", default=False)

# Reject uploads whose declared size exceeds this (MB).
MAX_UPLOAD_MB = int(os.environ.get("INTAKE_MAX_UPLOAD_MB", "25") or "25")

# Send HSTS header (only meaningful when actually served over HTTPS).
HSTS = _flag("INTAKE_HSTS", default=False)


def ensure_dirs() -> None:
    for d in (DATA_DIR, UPLOAD_DIR, SCAN_DIR):
        d.mkdir(parents=True, exist_ok=True)
