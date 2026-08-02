"""SQLite persistence — a single file at ``data/gate.db``.

Bundles are stored as their validated JSON; flags are recomputed on read by the
deterministic engine (they are cheap and must never drift from the current rule
set).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from app.models import Bundle

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "gate.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bundles (
                bundle_id             TEXT PRIMARY KEY,
                client_name           TEXT NOT NULL,
                declared_period_start TEXT NOT NULL,
                declared_period_end   TEXT NOT NULL,
                created_at            TEXT NOT NULL,
                data_json             TEXT NOT NULL
            )
            """
        )


def save_bundle(bundle: Bundle) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO bundles
                (bundle_id, client_name, declared_period_start,
                 declared_period_end, created_at, data_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                bundle.bundle_id,
                bundle.client_name,
                bundle.declared_period_start.isoformat(),
                bundle.declared_period_end.isoformat(),
                datetime.utcnow().isoformat(timespec="seconds"),
                bundle.model_dump_json(),
            ),
        )


def get_bundle(bundle_id: str) -> Bundle | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT data_json FROM bundles WHERE bundle_id = ?", (bundle_id,)
        ).fetchone()
    if row is None:
        return None
    return Bundle.model_validate_json(row["data_json"])


def list_bundles() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT bundle_id, client_name, created_at FROM bundles "
            "ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]
