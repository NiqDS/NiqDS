"""Pluggable email delivery -- spec step 4/5/7 (send CG/TG files to the

requester, a copy + pilot metadata to the dev team, later a dashboard link
to the requester).

`EmailConnector` is a Protocol so `pipeline.py` never imports a concrete
connector directly; wire whichever implementation fits the deployment
target in one place (see skill/pipeline.py's `build_default_connectors`).
"""
from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol


@dataclass
class OutgoingEmail:
    to: list[str]
    subject: str
    body: str
    attachments: list[Path] = field(default_factory=list)


class EmailConnector(Protocol):
    def send(self, message: OutgoingEmail) -> None: ...


class LoggingEmailConnector:
    """Default, side-effect-free connector: writes each message to a local

    outbox directory instead of actually sending mail. Safe to use out of
    the box in this sandbox / in CI; swap for `SmtpEmailConnector` (or a
    Sber-internal mail API client) once real credentials are available.
    """

    def __init__(self, outbox_dir: Path):
        self.outbox_dir = Path(outbox_dir)
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        self.sent: list[OutgoingEmail] = []

    def send(self, message: OutgoingEmail) -> None:
        self.sent.append(message)
        safe_subject = "".join(c if c.isalnum() or c in "-_" else "_" for c in message.subject)[:60]
        out_path = self.outbox_dir / f"{len(self.sent):04d}_{safe_subject}.eml.txt"
        lines = [
            f"To: {', '.join(message.to)}",
            f"Subject: {message.subject}",
            f"Attachments: {', '.join(str(a) for a in message.attachments) or '(none)'}",
            "",
            message.body,
        ]
        out_path.write_text("\n".join(lines), encoding="utf-8")


class SmtpEmailConnector:
    """Production connector -- wire real SMTP settings via env vars/secrets

    manager, not hardcoded here. Attachments are read from disk and
    attached as-is (xlsx/csv).
    """

    def __init__(self, host: str, port: int, sender: str, use_tls: bool = True):
        self.host = host
        self.port = port
        self.sender = sender
        self.use_tls = use_tls

    def send(self, message: OutgoingEmail) -> None:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = ", ".join(message.to)
        msg["Subject"] = message.subject
        msg.set_content(message.body)
        for attachment in message.attachments:
            data = attachment.read_bytes()
            msg.add_attachment(
                data,
                maintype="application",
                subtype="octet-stream",
                filename=attachment.name,
            )
        with smtplib.SMTP(self.host, self.port) as smtp:
            if self.use_tls:
                smtp.starttls()
            smtp.send_message(msg)
