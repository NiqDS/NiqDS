"""Temporal-rule tests. `today` is injected so the tests are deterministic."""

from __future__ import annotations

from datetime import date

from app.models import DocType, ExtractedDocument
from app.rules.checks_temporal import check_temporal


def _doc(d, **kw) -> ExtractedDocument:
    base = dict(
        source_file="x.pdf",
        doc_type=DocType.PURCHASE_INVOICE,
        confidence=0.95,
        supplier_name="Oakwood Trading Ltd",
        document_date=d,
        raw_text_excerpt="Oakwood Trading Ltd invoice",
    )
    base.update(kw)
    return ExtractedDocument(**base)


PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 3, 31)
TODAY = date(2026, 4, 15)


def _ids(flags):
    return {f.rule_id for f in flags}


def test_out_of_period_fires():
    doc = _doc(date(2026, 4, 3))
    flags = check_temporal(doc, PERIOD_START, PERIOD_END, today=TODAY)
    assert "TMP-PERIOD-001" in _ids(flags)
    # Message names both the document date and the declared period.
    msg = next(f for f in flags if f.rule_id == "TMP-PERIOD-001").message
    assert "3 April 2026" in msg
    assert "January 2026" in msg and "March 2026" in msg


def test_in_period_is_silent():
    doc = _doc(date(2026, 2, 20))
    assert not check_temporal(doc, PERIOD_START, PERIOD_END, today=TODAY)


def test_future_date_fires_and_supersedes_period():
    doc = _doc(date(2026, 12, 1))
    flags = check_temporal(doc, PERIOD_START, PERIOD_END, today=TODAY)
    assert _ids(flags) == {"TMP-FUTURE-001"}


def test_stale_document_warns():
    doc = _doc(date(2023, 1, 1))
    flags = check_temporal(doc, date(2023, 1, 1), date(2023, 3, 31), today=TODAY)
    assert "TMP-STALE-001" in _ids(flags)


def test_bank_statement_exempt():
    doc = ExtractedDocument(
        source_file="s.pdf", doc_type=DocType.BANK_STATEMENT, confidence=0.9,
        document_date=None, period_start=date(2026, 5, 1), period_end=date(2026, 5, 31),
        raw_text_excerpt="Barclays statement May 2026",
    )
    assert not check_temporal(doc, PERIOD_START, PERIOD_END, today=TODAY)
