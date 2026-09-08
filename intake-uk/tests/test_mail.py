"""Tests for the accountant-draft builder (note, mailto, .eml with attachments)."""

from __future__ import annotations

import email
from email import policy

from app import mail


def _items():
    return [
        mail.DraftItem(scan_id="S-1", label="Purchase invoice", source_file="inv1.pdf",
                       verdict="ready", fixes=[], file_bytes=b"%PDF-1 ready"),
        mail.DraftItem(scan_id="S-2", label="Purchase invoice", source_file="inv2.pdf",
                       verdict="fix", fixes=["The VAT number isn't valid. Please check and resend."],
                       file_bytes=b"%PDF-1 fix"),
    ]


def test_build_draft_note_groups_and_counts():
    d = mail.build_draft("me@biz.co.uk", "acct@firm.co.uk", _items(), extra_note="Cheers!")
    assert d.to == "acct@firm.co.uk"
    assert "2 documents" in d.subject and "1 to check" in d.subject
    assert "Ready (1):" in d.body_text
    assert "Still to sort out (1):" in d.body_text
    assert "The VAT number isn't valid" in d.body_text
    assert "Cheers!" in d.body_text
    assert d.body_text.strip().endswith("me@biz.co.uk")


def test_all_ready_subject():
    items = [mail.DraftItem("S-1", "Receipt", "r.jpg", "ready", [], b"x")]
    d = mail.build_draft("me@biz.co.uk", "acct@firm.co.uk", items)
    assert "all checked" in d.subject
    assert "Still to sort out" not in d.body_text


def test_mailto_is_encoded():
    d = mail.build_draft("me@biz.co.uk", "acct@firm.co.uk", _items())
    link = mail.to_mailto(d)
    assert link.startswith("mailto:acct%40firm.co.uk?")
    assert "subject=" in link and "body=" in link
    assert " " not in link  # spaces must be percent-encoded


def test_eml_has_attachments_and_draft_header():
    d = mail.build_draft("me@biz.co.uk", "acct@firm.co.uk", _items())
    raw = mail.to_eml(d, "me@biz.co.uk")
    msg = email.message_from_bytes(raw, policy=policy.default)
    assert msg["To"] == "acct@firm.co.uk"
    assert msg["X-Unsent"] == "1"
    names = [p.get_filename() for p in msg.iter_attachments()]
    assert "inv1.pdf" in names and "inv2.pdf" in names


def test_unknown_provider_raises():
    d = mail.build_draft("me@biz.co.uk", "acct@firm.co.uk", _items())
    try:
        mail.create_remote_draft(d, "me@biz.co.uk", "carrierpigeon", "tok")
        assert False, "unknown provider should raise"
    except mail.MailNotConfigured:
        pass


def test_gmail_draft_request(monkeypatch):
    import base64

    captured = {}

    def fake_post_json(url, token, payload):
        captured.update(url=url, token=token, payload=payload)
        return {"id": "draft123"}

    monkeypatch.setattr(mail.oauth, "post_json", fake_post_json)
    d = mail.build_draft("me@biz.co.uk", "acct@firm.co.uk", _items())
    link = mail.create_remote_draft(d, "me@biz.co.uk", "gmail", "tok-abc")

    assert "gmail.googleapis.com" in captured["url"] and captured["token"] == "tok-abc"
    raw = captured["payload"]["message"]["raw"]
    decoded = base64.urlsafe_b64decode(raw + "===").decode("utf-8", "ignore")
    assert "acct@firm.co.uk" in decoded and "Subject" in decoded
    assert "mail.google.com" in link


def test_microsoft_draft_creates_message_then_attachments(monkeypatch):
    calls = []

    def fake_post_json(url, token, payload):
        calls.append((url, payload))
        if url.endswith("/messages"):
            return {"id": "m1", "webLink": "https://outlook.office.com/mail/deeplink/m1"}
        return {}

    monkeypatch.setattr(mail.oauth, "post_json", fake_post_json)
    d = mail.build_draft("me@biz.co.uk", "acct@firm.co.uk", _items())
    link = mail.create_remote_draft(d, "me@biz.co.uk", "microsoft", "tok")

    assert calls[0][0].endswith("/messages")
    assert calls[0][1]["toRecipients"][0]["emailAddress"]["address"] == "acct@firm.co.uk"
    attach_calls = [c for c in calls if c[0].endswith("/attachments")]
    assert len(attach_calls) == 2  # one per document
    assert "contentBytes" in attach_calls[0][1]
    assert "outlook.office.com" in link
