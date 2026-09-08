"""JSON API tests (FastAPI TestClient, in-process, no network).

A temp DB is used so these don't touch the real data/gate.db.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Point the DB at a temp file and (re)init it before the app starts.
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "api.db")
    db.init_db()
    import app.main as main

    with TestClient(main.app) as c:
        yield c


def _register(client, email="api@biz.co.uk", password="supersecret1"):
    # Web signup seeds a user (the API has no public signup by design).
    r = client.post("/signup", data={"email": email, "password": password},
                    follow_redirects=False)
    assert r.status_code in (303, 302)


def test_health_open(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_scan_requires_auth(client):
    with open(FIXTURES / "01_clean_invoice.pdf", "rb") as f:
        r = client.post("/api/scan", files={"file": ("01_clean_invoice.pdf", f, "application/pdf")})
    assert r.status_code == 401
    assert r.json()["detail"]  # JSON error, not an HTML page


def test_login_returns_token_and_scan_with_bearer(client):
    _register(client)
    r = client.post("/api/login", json={"email": "api@biz.co.uk", "password": "supersecret1"})
    assert r.status_code == 200
    token = r.json()["token"]
    assert token and r.json()["email"] == "api@biz.co.uk"

    headers = {"Authorization": f"Bearer {token}"}
    with open(FIXTURES / "02_bad_vat_invoice.pdf", "rb") as f:
        r = client.post("/api/scan", headers=headers,
                        files={"file": ("02_bad_vat_invoice.pdf", f, "application/pdf")})
    assert r.status_code == 200
    body = r.json()
    assert body["doc_type"] == "PURCHASE_INVOICE"
    assert body["verdict"] == "fix"
    assert body["scan_id"].startswith("S-")
    # the bad VAT field is reported invalid, with a rule-id in the audit flags
    vat = next(fld for fld in body["fields"] if fld["key"] == "supplier_vat_number")
    assert vat["status"] == "invalid"
    assert any(fl["rule_id"] == "FMT-VAT-001" for fl in body["flags"])

    # it also lists + fetches back
    scan_id = body["scan_id"]
    assert any(s["scan_id"] == scan_id for s in client.get("/api/scans", headers=headers).json())
    got = client.get(f"/api/scan/{scan_id}", headers=headers)
    assert got.status_code == 200 and got.json()["scan_id"] == scan_id


def test_bad_login_401(client):
    _register(client)
    r = client.post("/api/login", json={"email": "api@biz.co.uk", "password": "wrong"})
    assert r.status_code == 401


def test_bad_token_401(client):
    r = client.get("/api/scans", headers={"Authorization": "Bearer not.a.real.token"})
    assert r.status_code == 401
