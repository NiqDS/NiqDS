"""Temporal checks — period boundaries, future dates, stale documents.

The current date is injected (default ``date.today()``) so tests are
deterministic.
"""

from __future__ import annotations

from datetime import date

from app.models import DocType, ExtractedDocument, Flag
from app.rules.engine import bundle_rule, make_flag

STALE_MONTHS = 24

# Optional injected "today" so a whole bundle run is deterministic (tests, eval,
# reproducible demos). None means use the real system date.
_TODAY: date | None = None


def set_today(d: date | None) -> None:
    global _TODAY
    _TODAY = d


def _fmt_uk(d: date) -> str:
    return d.strftime("%-d %B %Y") if hasattr(d, "strftime") else str(d)


def _fmt_period(start: date, end: date) -> str:
    return f"{start.strftime('%-d %B %Y')} to {end.strftime('%-d %B %Y')}"


def check_temporal(
    doc: ExtractedDocument,
    period_start: date,
    period_end: date,
    today: date | None = None,
) -> list[Flag]:
    """All document-level temporal rules for one document.

    Bundle-scoped because they compare a document's date against the bundle's
    declared period.
    """

    today = today or date.today()
    flags: list[Flag] = []
    d = doc.document_date

    # Bank statements are validated by their period elsewhere (SET-STMT-001).
    if doc.doc_type == DocType.BANK_STATEMENT or d is None:
        return flags

    supplier = doc.supplier_name or "the supplier"

    # TMP-FUTURE-001 — future date. Checked first; it subsumes period breach.
    if d > today:
        flags.append(
            make_flag(
                "TMP-FUTURE-001",
                field="document_date",
                document=doc.source_file,
                evidence=_fmt_uk(d),
                supplier_name=supplier,
            )
        )
        return flags

    # TMP-PERIOD-001 — outside declared period.
    if d < period_start or d > period_end:
        flags.append(
            make_flag(
                "TMP-PERIOD-001",
                field="document_date",
                document=doc.source_file,
                evidence=_fmt_uk(d),
                period=_fmt_period(period_start, period_end),
                supplier_name=supplier,
            )
        )

    # TMP-STALE-001 — more than 24 months old (WARN).
    months_old = (today.year - d.year) * 12 + (today.month - d.month)
    if months_old > STALE_MONTHS:
        flags.append(
            make_flag(
                "TMP-STALE-001",
                field="document_date",
                document=doc.source_file,
                evidence=_fmt_uk(d),
                supplier_name=supplier,
            )
        )

    return flags


@bundle_rule
def temporal_rules(bundle) -> list[Flag]:  # type: ignore[no-untyped-def]
    flags: list[Flag] = []
    for doc in bundle.documents:
        flags.extend(
            check_temporal(
                doc,
                bundle.declared_period_start,
                bundle.declared_period_end,
                today=_TODAY,
            )
        )
    return flags
