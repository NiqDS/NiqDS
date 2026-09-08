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


def test_remote_backend_not_configured():
    d = mail.build_draft("me@biz.co.uk", "acct@firm.co.uk", _items())
    try:
        mail.create_remote_draft(d, "me@biz.co.uk")
        assert False, "should not be configured in the prototype"
    except mail.MailNotConfigured:
        pass
