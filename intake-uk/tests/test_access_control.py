"""Access-control tests for the practice bundle tool.

These lock in the fix for the broken-access-control finding: the bundle routes
(`/`, `/upload`, `/demo`, `/bundle/{id}`, `/report`, `/chase`) require a logged-in
user, and a bundle is only ever visible to the account that created it. A second
user must not be able to read another practice's client documents by guessing or
enumerating a bundle id (IDOR).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ac.db")
    db.init_db()
    import app.main as main

    return main.app


def _new_client(app) -> TestClient:
    # A fresh client = a fresh cookie jar = a distinct browser/session.
    c = TestClient(app)
    c.__enter__()
    return c


def _signup(client, email, password="supersecret1"):
    r = client.post("/signup", data={"email": email, "password": password},
                    follow_redirects=False)
    assert r.status_code in (302, 303)


def _make_demo_bundle(client) -> str:
    r = client.post("/demo", data={"scenario": "BUNDLE-A-INVOICES"},
                    follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("/bundle/B-")
    return loc.rsplit("/", 1)[1]


# --- unauthenticated access is refused ------------------------------------- #

@pytest.mark.parametrize("path", ["/", "/bundle/B-anything", "/bundle/B-x/report", "/bundle/B-x/chase"])
def test_get_routes_require_login(app_env, path):
    client = _new_client(app_env)
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_post_routes_require_login(app_env):
    client = _new_client(app_env)
    for path, data in [("/demo", {"scenario": "BUNDLE-A-INVOICES"}),
                       ("/upload", {"client_name": "X", "declared_period_start": "2026-01-01",
                                    "declared_period_end": "2026-03-31"})]:
        r = client.post(path, data=data, follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/login"
    # And nothing was written.
    assert db.list_bundles(1) == []


# --- the owner can see their own bundle ------------------------------------ #

def test_owner_can_view_their_bundle(app_env):
    client = _new_client(app_env)
    _signup(client, "owner@biz.co.uk")
    bundle_id = _make_demo_bundle(client)

    # Full-entropy id (not the old 32-bit uuid4().hex[:8]).
    assert len(bundle_id) == len("B-") + 32

    for suffix in ("", "/report", "/chase"):
        r = client.get(f"/bundle/{bundle_id}{suffix}")
        assert r.status_code == 200


# --- another user cannot (IDOR) -------------------------------------------- #

def test_other_user_cannot_read_bundle(app_env):
    owner = _new_client(app_env)
    _signup(owner, "owner@biz.co.uk")
    bundle_id = _make_demo_bundle(owner)

    attacker = _new_client(app_env)
    _signup(attacker, "attacker@biz.co.uk")

    # The bundle exists, but it's not the attacker's — reads as "not found",
    # never the other practice's client data.
    for suffix in ("", "/report"):
        r = attacker.get(f"/bundle/{bundle_id}{suffix}", follow_redirects=False)
        assert r.status_code == 404
    # And it never appears in their own list.
    r = attacker.get("/")
    assert bundle_id not in r.text


def test_db_get_bundle_is_owner_scoped(app_env):
    # Direct unit-level check on the data layer.
    owner = _new_client(app_env)
    _signup(owner, "owner@biz.co.uk")
    bundle_id = _make_demo_bundle(owner)

    owner_row = db.get_user_by_email("owner@biz.co.uk")
    assert db.get_bundle(bundle_id, owner_row["id"]) is not None
    # A different (non-existent) owner id gets nothing.
    assert db.get_bundle(bundle_id, owner_row["id"] + 999) is None
