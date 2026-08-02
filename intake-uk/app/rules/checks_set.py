"""Bundle-level / set checks.

These are what nothing else on the market does — gap detection, expected-account
coverage, duplicates and missing document types. They are prioritised.
"""

from __future__ import annotations

import calendar
import json
from datetime import date, timedelta
from pathlib import Path

from app.models import Bundle, DocType, ExtractedDocument, Flag
from app.rules.engine import bundle_rule, make_flag
from app.util import digits_only, normalise_name

# --- client profiles (stub for SET-EMPTY-001) ------------------------------

# Maps client_name -> list of DocType names the client normally submits.
CLIENT_PROFILES: dict[str, list[str]] = {}

_DEFAULT_PROFILE_PATH = (
    Path(__file__).resolve().parents[2] / "fixtures" / "client_profiles.json"
)


def load_client_profiles(path: Path | None = None) -> None:
    global CLIENT_PROFILES
    p = path or _DEFAULT_PROFILE_PATH
    if p.exists():
        CLIENT_PROFILES = json.loads(p.read_text(encoding="utf-8"))


def set_client_profiles(profiles: dict[str, list[str]]) -> None:
    global CLIENT_PROFILES
    CLIENT_PROFILES = profiles


load_client_profiles()


# --- helpers ----------------------------------------------------------------


def _last4(identifier: str | None) -> str:
    d = digits_only(identifier or "")
    return d[-4:] if len(d) >= 4 else d


def _last_day_of_month(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _describe_gap(start: date, end: date) -> str:
    """A whole calendar month renders as 'April 2026'; anything else as a range."""

    if (
        start.day == 1
        and start.month == end.month
        and start.year == end.year
        and end == _last_day_of_month(start)
    ):
        return start.strftime("%B %Y")
    return f"{start.strftime('%-d %B %Y')} to {end.strftime('%-d %B %Y')}"


# --- SET-STMT-001 -----------------------------------------------------------


@bundle_rule
def set_stmt_001(bundle: Bundle) -> list[Flag]:
    """Statement period gap detection, per account."""

    statements = [
        d
        for d in bundle.documents
        if d.doc_type == DocType.BANK_STATEMENT
        and d.period_start is not None
        and d.period_end is not None
    ]
    if not statements:
        return []

    by_account: dict[str, list[ExtractedDocument]] = {}
    for s in statements:
        by_account.setdefault(_last4(s.account_identifier), []).append(s)

    flags: list[Flag] = []
    for account, docs in by_account.items():
        docs = sorted(docs, key=lambda d: d.period_start)  # type: ignore[arg-type]

        # Gap before the first statement.
        first = docs[0]
        if first.period_start > bundle.declared_period_start:  # type: ignore[operator]
            flags.append(
                _gap_flag(bundle.declared_period_start, first.period_start - timedelta(days=1), account)  # type: ignore[operator]
            )

        # Gaps between consecutive statements.
        for prev, nxt in zip(docs, docs[1:]):
            expected_next = prev.period_end + timedelta(days=1)  # type: ignore[operator]
            if nxt.period_start > expected_next:  # type: ignore[operator]
                flags.append(
                    _gap_flag(expected_next, nxt.period_start - timedelta(days=1), account)  # type: ignore[operator]
                )

        # Gap after the last statement.
        last = docs[-1]
        if last.period_end < bundle.declared_period_end:  # type: ignore[operator]
            flags.append(
                _gap_flag(last.period_end + timedelta(days=1), bundle.declared_period_end, account)  # type: ignore[operator]
            )

    return flags


def _gap_flag(start: date, end: date, account: str) -> Flag:
    return make_flag(
        "SET-STMT-001",
        field="period",
        document=None,
        evidence=_describe_gap(start, end),
        account=account,
    )


# --- SET-ACCT-001 -----------------------------------------------------------


@bundle_rule
def set_acct_001(bundle: Bundle) -> list[Flag]:
    """Any expected account with zero documents → BLOCK."""

    covered = {
        _last4(d.account_identifier)
        for d in bundle.documents
        if d.doc_type == DocType.BANK_STATEMENT and d.account_identifier
    }
    flags: list[Flag] = []
    for expected in bundle.expected_accounts:
        if _last4(expected) not in covered:
            flags.append(
                make_flag(
                    "SET-ACCT-001",
                    field="expected_accounts",
                    document=None,
                    evidence=_last4(expected),
                )
            )
    return flags


# --- SET-DUP-001 ------------------------------------------------------------


@bundle_rule
def set_dup_001(bundle: Bundle) -> list[Flag]:
    """Duplicate detection: exact key match, plus a fuzzy no-number variant."""

    flags: list[Flag] = []
    docs = [
        d
        for d in bundle.documents
        if d.doc_type in {DocType.PURCHASE_INVOICE, DocType.SALES_INVOICE, DocType.RECEIPT}
    ]

    seen_exact: dict[tuple, str] = {}
    for d in docs:
        if not d.document_number or d.gross_total is None:
            continue
        key = (normalise_name(d.supplier_name), d.document_number, d.gross_total.amount)
        if key in seen_exact:
            flags.append(_dup_flag(d))
        else:
            seen_exact[key] = d.source_file

    # Fuzzy: same supplier + same gross + dates within 3 days + no doc number.
    numberless = [
        d for d in docs
        if not d.document_number and d.gross_total is not None and d.document_date
    ]
    for i, a in enumerate(numberless):
        for b in numberless[i + 1 :]:
            if (
                normalise_name(a.supplier_name) == normalise_name(b.supplier_name)
                and a.gross_total.amount == b.gross_total.amount  # type: ignore[union-attr]
                and abs((a.document_date - b.document_date).days) <= 3  # type: ignore[operator]
            ):
                flags.append(_dup_flag(b))

    return flags


def _dup_flag(doc: ExtractedDocument) -> Flag:
    ident = doc.document_number or (
        doc.document_date.strftime("%-d %B %Y") if doc.document_date else doc.source_file
    )
    return make_flag(
        "SET-DUP-001",
        field="document_number",
        document=doc.source_file,
        evidence=ident,
        supplier_name=doc.supplier_name or "the supplier",
    )


# --- SET-EMPTY-001 ----------------------------------------------------------


@bundle_rule
def set_empty_001(bundle: Bundle) -> list[Flag]:
    """Bundle missing a document type the client normally submits (WARN)."""

    expected_types = CLIENT_PROFILES.get(bundle.client_name)
    if not expected_types:
        return []
    present = {d.doc_type.value for d in bundle.documents}
    flags: list[Flag] = []
    for t in expected_types:
        if t not in present:
            flags.append(
                make_flag(
                    "SET-EMPTY-001",
                    field="doc_type",
                    document=None,
                    evidence=_friendly_type(t),
                )
            )
    return flags


def _friendly_type(doc_type: str) -> str:
    return {
        "PURCHASE_INVOICE": "purchase invoices",
        "SALES_INVOICE": "sales invoices",
        "RECEIPT": "receipts",
        "BANK_STATEMENT": "bank statements",
    }.get(doc_type, doc_type.lower())
