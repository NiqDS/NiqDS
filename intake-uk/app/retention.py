"""Data retention — delete stored client files after a configurable period.

Uploaded documents and scans hold client financial data. When
``INTAKE_RETENTION_DAYS`` is set (>0), files older than that under the uploads
and scans directories are removed on startup (and can be called on a schedule).
Extracted records kept in the database are unaffected — this removes the raw
files only.
"""

from __future__ import annotations

import time
from pathlib import Path

from app import config


def sweep(days: int | None = None) -> int:
    """Delete files older than ``days`` under the uploads/scans dirs.

    Returns the number of files removed. A non-positive ``days`` keeps everything.
    """

    days = config.RETENTION_DAYS if days is None else days
    if days <= 0:
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for root in (config.UPLOAD_DIR, config.SCAN_DIR):
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                        removed += 1
                except OSError:
                    continue
    _prune_empty_dirs(config.UPLOAD_DIR)
    _prune_empty_dirs(config.SCAN_DIR)
    return removed


def _prune_empty_dirs(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir():
            try:
                next(path.iterdir())
            except StopIteration:
                try:
                    path.rmdir()
                except OSError:
                    pass
