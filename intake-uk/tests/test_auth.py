"""Auth unit tests — hashing and register/authenticate against a temp DB."""

from __future__ import annotations

import importlib

import pytest

from app import auth, db


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    yield


def test_password_hash_roundtrip():
    h = auth.hash_password("correct horse battery")
    assert h.startswith("scrypt$")
    assert auth.verify_password("correct horse battery", h)
    assert not auth.verify_password("wrong", h)


def test_register_and_authenticate(temp_db):
    uid, err = auth.register("Nick@Example.com", "supersecret1")
    assert err is None and uid
    # email normalised to lowercase on lookup
    assert auth.authenticate("nick@example.com", "supersecret1") == uid
    assert auth.authenticate("nick@example.com", "nope") is None


def test_register_rejects_short_password(temp_db):
    uid, err = auth.register("a@b.com", "short")
    assert uid is None and "8 characters" in err


def test_register_rejects_duplicate(temp_db):
    auth.register("dup@example.com", "supersecret1")
    uid, err = auth.register("dup@example.com", "supersecret1")
    assert uid is None and "already exists" in err


# --- business profile ------------------------------------------------------- #

def test_register_persists_profile(temp_db):
    uid, err = auth.register(
        "sole@trader.co.uk", "supersecret1",
        business_type="sole_trader", vat_registered=True,
        vat_number="GB 999 9999 73", mtd_status="vat",
    )
    assert err is None and uid
    user = db.get_user(uid)
    assert user["business_type"] == "sole_trader"
    assert user["vat_registered"] == 1
    assert user["vat_number"] == "GB 999 9999 73"
    assert user["mtd_status"] == "vat"


def test_register_validates_vat_number(temp_db):
    # GB123456789 fails the UK check digit — reuse of the engine's own rule.
    uid, err = auth.register(
        "bad@vat.co.uk", "supersecret1",
        vat_registered=True, vat_number="GB123456789",
    )
    assert uid is None and "VAT number" in err


def test_register_rejects_unknown_business_type(temp_db):
    uid, err = auth.register("x@y.co.uk", "supersecret1", business_type="megacorp")
    assert uid is None and "business type" in err.lower()


def test_register_without_profile_is_fine(temp_db):
    uid, err = auth.register("plain@user.co.uk", "supersecret1")
    assert err is None and uid
    user = db.get_user(uid)
    assert user["business_type"] is None
    assert user["vat_registered"] is None
