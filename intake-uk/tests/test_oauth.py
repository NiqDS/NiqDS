"""OAuth link-flow tests — PKCE, URL building, config gating, token exchange."""

from __future__ import annotations

import base64
import hashlib
import urllib.parse as up

from app import oauth


def test_pkce_challenge_is_s256_of_verifier():
    verifier, challenge = oauth.new_pkce()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert challenge == expected
    assert "=" not in challenge  # url-safe, unpadded


def test_is_configured_reads_env(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    assert not oauth.is_configured("gmail")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    assert oauth.is_configured("gmail")


def test_authorization_url_has_required_params(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "my-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "s")
    url = oauth.authorization_url(
        "gmail", "https://app.example.com/oauth/callback/gmail", "state123", "chal456"
    )
    q = dict(up.parse_qsl(up.urlparse(url).query))
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert q["client_id"] == "my-client-id"
    assert q["redirect_uri"] == "https://app.example.com/oauth/callback/gmail"
    assert q["response_type"] == "code"
    assert q["code_challenge"] == "chal456" and q["code_challenge_method"] == "S256"
    assert q["state"] == "state123"
    assert "gmail.compose" in q["scope"]
    assert q["access_type"] == "offline"  # provider extra param


def test_microsoft_scope_and_endpoint(monkeypatch):
    monkeypatch.setenv("MS_CLIENT_ID", "mid")
    monkeypatch.setenv("MS_CLIENT_SECRET", "s")
    url = oauth.authorization_url("microsoft", "https://x/cb", "st", "ch")
    q = dict(up.parse_qsl(up.urlparse(url).query))
    assert "login.microsoftonline.com" in url
    assert "Mail.ReadWrite" in q["scope"] and "offline_access" in q["scope"]


def test_exchange_code_posts_to_token_url(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "sec")
    captured = {}

    def fake_post_form(url, fields):
        captured.update(url=url, fields=fields)
        return {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}

    monkeypatch.setattr(oauth, "post_form", fake_post_form)
    tok = oauth.exchange_code("gmail", "the-code", "https://x/cb", "verifier")
    assert captured["url"] == "https://oauth2.googleapis.com/token"
    assert captured["fields"]["grant_type"] == "authorization_code"
    assert captured["fields"]["code"] == "the-code"
    assert captured["fields"]["code_verifier"] == "verifier"
    assert tok["access_token"] == "at"
