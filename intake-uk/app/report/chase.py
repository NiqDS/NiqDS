"""Build the client chase message.

Generated from BLOCK flags only. Ordered by severity (they're all BLOCK here)
then by how easy the item is for the client to fix. Never more than five items:
long lists get ignored — this is a behavioural design decision, not a technical
one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html import escape

from app.models import Bundle, Flag

MAX_ITEMS = 5

# Lower rank == easier for the client to action, so it goes higher up the list.
# (All BLOCK rules; anything unlisted sorts to the middle.)
_EASE_RANK = {
    "SET-ACCT-001": 0,   # "send the missing account" — trivially actionable
    "SET-STMT-001": 1,   # "send the missing statement"
    "FMT-VAT-001": 2,    # "check and resend the VAT number"
    "TMP-PERIOD-001": 3, # "confirm which period this belongs to"
    "FMT-LEGIB-001": 4,  # "resend a clearer photo"
    "TMP-FUTURE-001": 5,
    "FMT-DATE-001": 6,
    "ARI-VAT-001": 7,    # requires the supplier to reissue — hardest
    "ARI-LINE-001": 8,
    "FMT-SORT-001": 9,
    "FMT-ACCT-001": 10,
    "FMT-SUPP-001": 11,
}


@dataclass
class ChaseMessage:
    client_name: str
    period: str
    text: str
    html: str
    items: list[str]
    overflow: int  # how many BLOCK items were dropped past the cap


def _period_str(bundle: Bundle) -> str:
    def fmt(d: date) -> str:
        return d.strftime("%-d %B %Y")

    return f"{fmt(bundle.declared_period_start)} to {fmt(bundle.declared_period_end)}"


def build_chase(bundle: Bundle, flags: list[Flag]) -> ChaseMessage:
    blocks = [f for f in flags if f.severity == "BLOCK"]
    blocks.sort(key=lambda f: _EASE_RANK.get(f.rule_id, 50))

    period = _period_str(bundle)
    shown = blocks[:MAX_ITEMS]
    overflow = len(blocks) - len(shown)

    items = [f.message for f in shown]

    # --- plain text ---
    lines = [f"Hi {bundle.client_name},", ""]
    lines.append(
        f"Thanks for sending your records for {period}. Before we can complete "
        f"them, we need a few things fixed:"
    )
    lines.append("")
    for i, msg in enumerate(items, 1):
        lines.append(f"{i}. {msg}")
    if overflow > 0:
        lines.append(f"{len(items) + 1}. ...and a few others we'll follow up on.")
    lines.append("")
    lines.append("Once we have these we'll get everything filed.")
    text = "\n".join(lines)

    # --- html ---
    li = "\n".join(f"    <li>{escape(msg)}</li>" for msg in items)
    if overflow > 0:
        li += "\n    <li>…and a few others we'll follow up on.</li>"
    html = (
        f"<p>Hi {escape(bundle.client_name)},</p>\n"
        f"<p>Thanks for sending your records for {escape(period)}. Before we can "
        f"complete them, we need a few things fixed:</p>\n"
        f"<ol>\n{li}\n</ol>\n"
        f"<p>Once we have these we'll get everything filed.</p>"
    )

    return ChaseMessage(
        client_name=bundle.client_name,
        period=period,
        text=text,
        html=html,
        items=items,
        overflow=max(overflow, 0),
    )
