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
from app.util import valid_uk_vat

_N, _R, _P = 2**14, 8, 1  # scrypt cost parameters
_SECRET_PATH = config.SECRET_PATH
MIN_PASSWORD_LEN = 8

# Business-profile options. These are *functional* attributes — they say which
# checks are relevant to a user (e.g. VAT rules only matter to a VAT-registered
# business) — not an identity/KYC verification.
BUSINESS_TYPES = {
    "sole_trader": "Sole trader",
    "partnership": "Partnership",
    "limited_company": "Limited company",
    "llp": "LLP",
    "charity": "Charity / non-profit",
    "other": "Other",
}
MTD_STATUSES = {
    "not_applicable": "Not applicable / not sure",
    "vat": "MTD for VAT",
    "itsa": "MTD for Income Tax (ITSA)",
    "exempt": "Exempt",
}


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


def register(
    email: str,
    password: str,
    *,
    business_type: str | None = None,
    vat_registered: bool = False,
    vat_number: str | None = None,
    mtd_status: str | None = None,
) -> tuple[int | None, str | None]:
    """Create a user (with an optional business profile).

    Returns (user_id, error_message). The profile fields are optional, but if a
    VAT number is supplied it is validated with the same deterministic check-digit
    rule the engine uses on invoices — a small, honest demonstration that the
    number the user typed is really a valid UK VAT number.
    """

    email = normalise_email(email)
    if "@" not in email or "." not in email:
        return None, "Please enter a valid email address."
    if len(password) < MIN_PASSWORD_LEN:
        return None, f"Password must be at least {MIN_PASSWORD_LEN} characters."

    business_type = (business_type or "").strip().lower() or None
    if business_type is not None and business_type not in BUSINESS_TYPES:
        return None, "Please choose a valid business type."
    mtd_status = (mtd_status or "").strip().lower() or None
    if mtd_status is not None and mtd_status not in MTD_STATUSES:
        return None, "Please choose a valid MTD status."

    vat_number = (vat_number or "").strip() or None
    if vat_number is not None and not valid_uk_vat(vat_number):
        return None, "That VAT number doesn't look like a valid UK VAT number — please check it."

    if db.get_user_by_email(email):
        return None, "An account with that email already exists."

    user_id = db.create_user(email, hash_password(password))
    if any(v is not None for v in (business_type, vat_number, mtd_status)) or vat_registered:
        db.set_profile(
            user_id,
            business_type=business_type,
            vat_registered=vat_registered,
            vat_number=vat_number,
            mtd_status=mtd_status,
        )
    return user_id, None


def authenticate(email: str, password: str) -> int | None:
    user = db.get_user_by_email(normalise_email(email))
    if user and verify_password(password, user["pw_hash"]):
        return int(user["id"])
    return None
