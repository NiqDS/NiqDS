"""OAuth 2.0 (auth-code + PKCE) for linking a work mailbox.

Two providers — Gmail and Microsoft 365 — behind one interface. This is the real
flow: it builds the provider authorisation URL, exchanges the code for tokens,
and refreshes them. It is *gated on credentials*: set the client id/secret env
vars (see docs/roadmap/email-drafts.md) and it goes live; without them the app
falls back to the local .eml / mailto drafts.

Least privilege: Gmail asks only for ``gmail.compose`` (create drafts, cannot
read the inbox or send); Microsoft asks only for ``Mail.ReadWrite``. The user
always reviews and sends from their own mailbox.

Network calls go through the module-level ``post_form`` / ``post_json`` /
``get_json`` helpers so tests can substitute them.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request

PROVIDERS: dict[str, dict] = {
    "gmail": {
        "label": "Gmail",
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scope": "https://www.googleapis.com/auth/gmail.compose",
        "extra_auth": {"access_type": "offline", "prompt": "consent"},
        "id_env": "GOOGLE_CLIENT_ID",
        "secret_env": "GOOGLE_CLIENT_SECRET",
    },
    "microsoft": {
        "label": "Microsoft 365",
        "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scope": "offline_access https://graph.microsoft.com/Mail.ReadWrite",
        "extra_auth": {},
        "id_env": "MS_CLIENT_ID",
        "secret_env": "MS_CLIENT_SECRET",
    },
}


class OAuthError(RuntimeError):
    pass


def provider_label(provider: str) -> str:
    return PROVIDERS[provider]["label"]


def client_id(provider: str) -> str | None:
    return os.environ.get(PROVIDERS[provider]["id_env"])


def client_secret(provider: str) -> str | None:
    return os.environ.get(PROVIDERS[provider]["secret_env"])


def is_configured(provider: str) -> bool:
    return provider in PROVIDERS and bool(client_id(provider)) and bool(client_secret(provider))


# --- PKCE + state ----------------------------------------------------------


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def new_state() -> str:
    return secrets.token_urlsafe(24)


def new_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) using the S256 method."""

    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def authorization_url(provider: str, redirect_uri: str, state: str, code_challenge: str) -> str:
    cfg = PROVIDERS[provider]
    params = {
        "client_id": client_id(provider) or "",
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": cfg["scope"],
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        **cfg["extra_auth"],
    }
    return cfg["auth_url"] + "?" + urllib.parse.urlencode(params)


# --- token exchange / refresh ----------------------------------------------


def exchange_code(provider: str, code: str, redirect_uri: str, code_verifier: str) -> dict:
    cfg = PROVIDERS[provider]
    data = {
        "client_id": client_id(provider) or "",
        "client_secret": client_secret(provider) or "",
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    }
    return post_form(cfg["token_url"], data)


def refresh_access_token(provider: str, refresh_token: str) -> dict:
    cfg = PROVIDERS[provider]
    data = {
        "client_id": client_id(provider) or "",
        "client_secret": client_secret(provider) or "",
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    return post_form(cfg["token_url"], data)


# --- HTTP helpers (stdlib; swappable in tests) -----------------------------


def _request(url: str, *, data: bytes | None, headers: dict, method: str = "POST") -> dict:
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:  # pragma: no cover - network path
        detail = e.read().decode("utf-8", "ignore")
        raise OAuthError(f"{url} -> {e.code}: {detail}") from e
    except urllib.error.URLError as e:  # pragma: no cover - network path
        raise OAuthError(f"{url} -> {e}") from e
    return json.loads(body) if body else {}


def post_form(url: str, fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode("utf-8")
    return _request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})


def post_json(url: str, token: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    return _request(
        url, data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )


def get_json(url: str, token: str) -> dict:
    return _request(url, data=None, method="GET", headers={"Authorization": f"Bearer {token}"})
