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
