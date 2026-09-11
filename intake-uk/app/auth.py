"""Lightweight authentication for the scan app.

Prototype-grade, deliberately simple: passwords are hashed with ``hashlib.scrypt``
(a per-user random salt), and the logged-in user id is kept in a signed session
cookie (Starlette ``SessionMiddleware``). This is enough to demo a real
log-in → capture → check flow.

Not yet production-hardened: no email verification, password reset, rate
limiting, or account lockout. Those belong in the Phase 1 platform build.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from app import config, db

_N, _R, _P = 2**14, 8, 1  # scrypt cost parameters
_SECRET_PATH = config.SECRET_PATH
MIN_PASSWORD_LEN = 8


def session_secret() -> str:
    """A stable secret for signing session cookies.

    From ``INTAKE_SECRET`` if set; otherwise generated once and cached in
    ``data/secret.key`` so sessions survive a restart in local use.
    """

    env = os.environ.get("INTAKE_SECRET")
    if env:
        return env
    if _SECRET_PATH.exists():
        return _SECRET_PATH.read_text(encoding="utf-8").strip()
    _SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(32)
    _SECRET_PATH.write_text(token, encoding="utf-8")
    return token


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def register(email: str, password: str) -> tuple[int | None, str | None]:
    """Create a user. Returns (user_id, error_message)."""

    email = normalise_email(email)
    if "@" not in email or "." not in email:
        return None, "Please enter a valid email address."
    if len(password) < MIN_PASSWORD_LEN:
        return None, f"Password must be at least {MIN_PASSWORD_LEN} characters."
    if db.get_user_by_email(email):
        return None, "An account with that email already exists."
    user_id = db.create_user(email, hash_password(password))
    return user_id, None


def authenticate(email: str, password: str) -> int | None:
    user = db.get_user_by_email(normalise_email(email))
    if user and verify_password(password, user["pw_hash"]):
        return int(user["id"])
    return None
