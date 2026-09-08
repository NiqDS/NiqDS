"""Tests for the single-document checker behind the scan app."""

from __future__ import annotations

from datetime import date

from app.models import DocType, ExtractedDocument, LineItem, Money
from app.single import check_single


def _invoice(**kw) -> ExtractedDocument:
    base = dict(
        source_file="scan.jpg",
        doc_type=DocType.PURCHASE_INVOICE,
        confidence=0.95,
        supplier_name="Hartley Supplies Ltd",
        supplier_vat_number="197126932",
        document_number="INV-1001",
        document_date=date(2026, 2, 20),
        net_total=Money(amount="100.00"),
        vat_total=Money(amount="20.00"),
        gross_total=Money(amount="120.00"),
        raw_text_excerpt="Hartley Supplies Ltd invoice INV-1001 dated 20 February 2026 total 120.00",
    )
    base.update(kw)
    return ExtractedDocument(**base)


def _fields(result):
    return {f.key: f.status for f in result.fields}


def test_clean_invoice_is_ready():
    r = check_single(_invoice())
    assert r.verdict == "ready"
    assert r.doc_type_label == "Purchase invoice"
    assert _fields(r)["supplier_name"] == "ok"
    assert _fields(r)["gross_total"] == "ok"
    assert r.fixes == []


def test_missing_date_needs_fix():
    r = check_single(_invoice(document_date=None))
    assert r.verdict == "fix"
    assert _fields(r)["document_date"] == "missing"
    assert any("date" in fix.lower() for fix in r.fixes)


def test_bad_vat_is_invalid_field():
    r = check_single(_invoice(supplier_vat_number="917126932"))  # transposed → invalid
    assert r.verdict == "fix"
    assert _fields(r)["supplier_vat_number"] == "invalid"
    assert any("VAT" in fix for fix in r.fixes)


def test_arithmetic_error_flags_total():
    r = check_single(_invoice(gross_total=Money(amount="130.00")))  # 100+20 != 130
    assert r.verdict == "fix"
    assert _fields(r)["gross_total"] == "invalid"


def test_low_confidence_is_unreadable():
    r = check_single(_invoice(confidence=0.2, raw_text_excerpt="blurry"))
    assert r.verdict == "unreadable"
    assert r.fixes  # tells the user to retake


def test_unknown_type():
    doc = ExtractedDocument(
        source_file="x.jpg", doc_type=DocType.UNKNOWN, confidence=0.9,
        supplier_name="Something", document_date=date(2026, 2, 1),
        raw_text_excerpt="a delivery note of some kind, 5 boxes received",
    )
    r = check_single(doc)
    assert r.verdict == "unknown"


def test_receipt_optional_vat_not_missing():
    doc = ExtractedDocument(
        source_file="r.jpg", doc_type=DocType.RECEIPT, confidence=0.9,
        supplier_name="Cafe Nero", document_date=date(2026, 2, 15),
        gross_total=Money(amount="4.20"), supplier_vat_number=None,
        raw_text_excerpt="Cafe Nero receipt total 4.20 on 15 February 2026",
    )
    r = check_single(doc)
    assert r.verdict == "ready"
    assert _fields(r)["supplier_vat_number"] == "optional"
