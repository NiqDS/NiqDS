"""Build a "send to my accountant" draft from a set of scanned documents.

Produces a subject + a plain-English note (what's ready, what needs fixing) and
turns it into a draft the user can actually send. Delivery is a small connector
abstraction — the same pattern as the LLM adapter — so the app can grow from
local drafts to one-click drafts in the user's work mailbox without changing the
calling code:

    * ``local``     — a downloadable ``.eml`` (documents attached) + a ``mailto:``
                      link. Works offline, no accounts to link. (default)
    * ``gmail``     — create a draft in the user's Gmail via the Gmail API
    * ``microsoft`` — create a draft in Microsoft 365 via Microsoft Graph

The two remote connectors are scaffolded and documented (see
``docs/roadmap/email-drafts.md``); they need OAuth credentials and a deployed
callback, so they raise a clear error until configured.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from email.message import EmailMessage
from mimetypes import guess_type
from urllib.parse import quote

from app.models import DocType
from app.single import SingleResult

MAX_ATTACHMENTS = 20  # keep drafts sendable; long lists get ignored anyway


@dataclass
class DraftItem:
    scan_id: str
    label: str  # e.g. "Purchase invoice"
    source_file: str
    verdict: str  # ready | fix | unreadable | unknown
    fixes: list[str] = field(default_factory=list)
    file_bytes: bytes | None = None


@dataclass
class Draft:
    to: str
    subject: str
    body_text: str
    items: list[DraftItem]


_READY = {"ready"}


def build_draft(
    from_email: str,
    to_email: str,
    items: list[DraftItem],
    period_label: str | None = None,
    extra_note: str | None = None,
) -> Draft:
    """Assemble the subject and the plain-English note."""

    ready = [i for i in items if i.verdict in _READY]
    attention = [i for i in items if i.verdict not in _READY]

    n, k = len(items), len(attention)
    period = f" for {period_label}" if period_label else ""
    if k:
        subject = f"My records{period} — {n} document{'s' if n != 1 else ''}, {k} to check"
    else:
        subject = f"My records{period} — {n} document{'s' if n != 1 else ''}, all checked"

    lines = ["Hi,", ""]
    lines.append(
        f"Here {'are' if n != 1 else 'is'} {n} document{'s' if n != 1 else ''}"
        f"{period}. I ran {'them' if n != 1 else 'it'} through a quick check first:"
    )
    lines.append("")

    if ready:
        lines.append(f"Ready ({len(ready)}):")
        for i in ready:
            lines.append(f"  - {i.label} ({i.source_file})")
        lines.append("")

    if attention:
        lines.append(f"Still to sort out ({len(attention)}):")
        for i in attention:
            head = f"  - {i.label} ({i.source_file})"
            if i.fixes:
                lines.append(head + ":")
                for fix in i.fixes:
                    lines.append(f"      • {fix}")
            else:
                lines.append(head)
        lines.append("")

    if extra_note and extra_note.strip():
        lines.append(extra_note.strip())
        lines.append("")

    lines.append("The documents are attached.")
    lines.append("")
    lines.append("Thanks,")
    lines.append(from_email)

    return Draft(to=to_email, subject=subject, body_text="\n".join(lines), items=items)


def to_mailto(draft: Draft) -> str:
    """A ``mailto:`` link that opens a pre-filled draft (body only — mailto can't
    carry attachments)."""

    q = f"subject={quote(draft.subject)}&body={quote(draft.body_text)}"
    return f"mailto:{quote(draft.to)}?{q}"


def to_eml(draft: Draft, from_email: str) -> bytes:
    """A standards-compliant ``.eml`` draft with the documents attached.

    Opening it in Outlook / Apple Mail / Thunderbird starts a new message the
    user can review and send. Nothing is sent from here.
    """

    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = draft.to
    msg["Subject"] = draft.subject
    msg["X-Unsent"] = "1"  # Outlook opens X-Unsent:1 messages as an editable draft
    msg.set_content(draft.body_text)

    for item in draft.items[:MAX_ATTACHMENTS]:
        if not item.file_bytes:
            continue
        ctype, _ = guess_type(item.source_file)
        maintype, subtype = (ctype.split("/", 1) if ctype else ("application", "octet-stream"))
        msg.add_attachment(
            item.file_bytes, maintype=maintype, subtype=subtype, filename=item.source_file
        )
    return bytes(msg)


# --- remote connectors: create the draft in the user's linked mailbox -------

import base64  # noqa: E402

from app import oauth  # noqa: E402

_GMAIL_DRAFTS = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
_GMAIL_WEB = "https://mail.google.com/mail/u/0/#drafts"
_GRAPH_MESSAGES = "https://graph.microsoft.com/v1.0/me/messages"


class MailNotConfigured(RuntimeError):
    pass


def create_remote_draft(draft: Draft, from_email: str, provider: str, access_token: str) -> str:
    """Create a draft in the user's linked work mailbox. Returns a web link/id.

    ``gmail``     → POST gmail/v1/users/me/drafts (scope gmail.compose)
    ``microsoft`` → POST /me/messages then /attachments (scope Mail.ReadWrite)
    """

    if provider == "gmail":
        return _create_gmail_draft(draft, from_email, access_token)
    if provider == "microsoft":
        return _create_microsoft_draft(draft, access_token)
    raise MailNotConfigured(f"Unknown mail provider: {provider!r}")


def _create_gmail_draft(draft: Draft, from_email: str, access_token: str) -> str:
    raw = base64.urlsafe_b64encode(to_eml(draft, from_email)).decode("ascii")
    resp = oauth.post_json(_GMAIL_DRAFTS, access_token, {"message": {"raw": raw}})
    return _GMAIL_WEB if resp.get("id") else _GMAIL_WEB


def _create_microsoft_draft(draft: Draft, access_token: str) -> str:
    # Creating a message (not sending it) leaves it in Drafts.
    body = {
        "subject": draft.subject,
        "body": {"contentType": "Text", "content": draft.body_text},
        "toRecipients": [{"emailAddress": {"address": draft.to}}],
    }
    msg = oauth.post_json(_GRAPH_MESSAGES, access_token, body)
    msg_id = msg.get("id")
    for item in draft.items[:MAX_ATTACHMENTS]:
        if not item.file_bytes or not msg_id:
            continue
        ctype, _ = guess_type(item.source_file)
        oauth.post_json(
            f"{_GRAPH_MESSAGES}/{msg_id}/attachments", access_token,
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": item.source_file,
                "contentType": ctype or "application/octet-stream",
                "contentBytes": base64.b64encode(item.file_bytes).decode("ascii"),
            },
        )
    return msg.get("webLink", "https://outlook.office.com/mail/drafts")
