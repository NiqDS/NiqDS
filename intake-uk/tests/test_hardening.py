"""Tests for retention sweep and security headers."""

from __future__ import annotations

import os
import time

from fastapi.testclient import TestClient

from app import config, db, retention


def test_retention_keeps_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "up")
    monkeypatch.setattr(config, "SCAN_DIR", tmp_path / "sc")
    (tmp_path / "up").mkdir()
    f = tmp_path / "up" / "old.pdf"
    f.write_bytes(b"x")
    assert retention.sweep(days=0) == 0
    assert f.exists()


def test_retention_deletes_old_keeps_new(tmp_path, monkeypatch):
    up = tmp_path / "up"
    up.mkdir()
    monkeypatch.setattr(config, "UPLOAD_DIR", up)
    monkeypatch.setattr(config, "SCAN_DIR", tmp_path / "sc")

    old = up / "old.pdf"
    old.write_bytes(b"x")
    old_time = time.time() - 40 * 86400
    os.utime(old, (old_time, old_time))

    new = up / "new.pdf"
    new.write_bytes(b"x")

    removed = retention.sweep(days=30)
    assert removed == 1
    assert not old.exists()
    assert new.exists()


def test_security_headers_present(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "h.db")
    db.init_db()
    import app.main as main

    with TestClient(main.app) as c:
        r = c.get("/")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"
        assert "Referrer-Policy" in r.headers
