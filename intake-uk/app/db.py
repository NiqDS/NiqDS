"""SQLite persistence — a single file at ``data/gate.db``.

Bundles are stored as their validated JSON; flags are recomputed on read by the
deterministic engine (they are cheap and must never drift from the current rule
set).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from app import config
from app.models import Bundle

DB_PATH = config.DB_PATH


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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                email            TEXT UNIQUE NOT NULL,
                pw_hash          TEXT NOT NULL,
                accountant_email TEXT,
                created_at       TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scans (
                scan_id    TEXT PRIMARY KEY,
                user_id    INTEGER NOT NULL,
                doc_type   TEXT NOT NULL,
                verdict    TEXT NOT NULL,
                created_at TEXT NOT NULL,
                data_json  TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS oauth_tokens (
                user_id       INTEGER NOT NULL,
                provider      TEXT NOT NULL,
                refresh_token TEXT,
                access_token  TEXT,
                expires_at    INTEGER NOT NULL DEFAULT 0,
                account_email TEXT,
                PRIMARY KEY (user_id, provider)
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


# --- users (for the scan app) ----------------------------------------------


def create_user(email: str, pw_hash: str) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, pw_hash, created_at) VALUES (?, ?, ?)",
            (email, pw_hash, datetime.utcnow().isoformat(timespec="seconds")),
        )
        return int(cur.lastrowid)


def get_user_by_email(email: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, email, pw_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
    return dict(row) if row else None


def get_user(user_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, email, accountant_email FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def set_accountant_email(user_id: int, email: str | None) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET accountant_email = ? WHERE id = ?",
            ((email or "").strip() or None, user_id),
        )


# --- scans -----------------------------------------------------------------


def save_scan(scan_id: str, user_id: int, doc_type: str, verdict: str, data_json: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO scans
                (scan_id, user_id, doc_type, verdict, created_at, data_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                scan_id,
                user_id,
                doc_type,
                verdict,
                datetime.utcnow().isoformat(timespec="seconds"),
                data_json,
            ),
        )


def get_scan(scan_id: str, user_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT scan_id, doc_type, verdict, created_at, data_json FROM scans "
            "WHERE scan_id = ? AND user_id = ?",
            (scan_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def list_scans(user_id: int, limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT scan_id, doc_type, verdict, created_at FROM scans "
            "WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# --- linked mailbox OAuth tokens -------------------------------------------


def save_oauth_token(user_id: int, provider: str, *, refresh_token: str | None,
                     access_token: str | None, expires_at: int, account_email: str | None) -> None:
    with _connect() as conn:
        # Keep an existing refresh token if the provider didn't return a new one.
        existing = conn.execute(
            "SELECT refresh_token FROM oauth_tokens WHERE user_id = ? AND provider = ?",
            (user_id, provider),
        ).fetchone()
        if not refresh_token and existing:
            refresh_token = existing["refresh_token"]
        conn.execute(
            """
            INSERT OR REPLACE INTO oauth_tokens
                (user_id, provider, refresh_token, access_token, expires_at, account_email)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, provider, refresh_token, access_token, expires_at, account_email),
        )


def get_oauth_token(user_id: int, provider: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT provider, refresh_token, access_token, expires_at, account_email "
            "FROM oauth_tokens WHERE user_id = ? AND provider = ?",
            (user_id, provider),
        ).fetchone()
    return dict(row) if row else None


def delete_oauth_token(user_id: int, provider: str) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM oauth_tokens WHERE user_id = ? AND provider = ?", (user_id, provider)
        )


def list_connections(user_id: int) -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT provider FROM oauth_tokens WHERE user_id = ?", (user_id,)
        ).fetchall()
    return [r["provider"] for r in rows]
