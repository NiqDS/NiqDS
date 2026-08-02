"""Arithmetic-rule tests. Money is Decimal throughout — no float."""

from __future__ import annotations

from decimal import Decimal

from app.models import DocType, ExtractedDocument, LineItem, Money
from app.rules import checks_arithmetic as ari


def _invoice(**kw) -> ExtractedDocument:
    base = dict(
        source_file="x.pdf",
        doc_type=DocType.PURCHASE_INVOICE,
        confidence=0.95,
        supplier_name="Acme Ltd",
        raw_text_excerpt="Acme Ltd invoice dated 20 February 2026 total due",
    )
    base.update(kw)
    return ExtractedDocument(**base)


def test_ari_vat_mismatch_fires():
    doc = _invoice(
        net_total=Money(amount="200.00"),
        vat_total=Money(amount="40.00"),
        gross_total=Money(amount="241.20"),
    )
    flags = ari.ari_vat_001(doc)
    assert flags and flags[0].rule_id == "ARI-VAT-001"
    assert flags[0].severity == "BLOCK"


def test_ari_vat_within_tolerance_is_silent():
    doc = _invoice(
        net_total=Money(amount="100.00"),
        vat_total=Money(amount="20.00"),
        gross_total=Money(amount="120.01"),  # 1p rounding, within £0.02
    )
    assert not ari.ari_vat_001(doc)


def test_ari_vat_uses_decimal_not_float():
    # 0.1 + 0.2 == 0.3 exactly with Decimal; would drift with float.
    doc = _invoice(
        net_total=Money(amount="0.10"),
        vat_total=Money(amount="0.20"),
        gross_total=Money(amount="0.30"),
    )
    assert not ari.ari_vat_001(doc)
    assert isinstance(doc.net_total.amount, Decimal)


def test_ari_line_sum_mismatch():
    doc = _invoice(
        net_total=Money(amount="200.00"),
        line_items=[
            LineItem(net=Money(amount="120.00")),
            LineItem(net=Money(amount="70.00")),  # sums to 190, not 200
        ],
    )
    flags = ari.ari_line_001(doc)
    assert flags and flags[0].rule_id == "ARI-LINE-001"


def test_ari_line_sum_ok():
    doc = _invoice(
        net_total=Money(amount="200.00"),
        line_items=[LineItem(net=Money(amount="120.00")), LineItem(net=Money(amount="80.00"))],
    )
    assert not ari.ari_line_001(doc)


def test_ari_rate_non_standard_warns():
    doc = _invoice(net_total=Money(amount="100.00"), vat_total=Money(amount="12.50"))
    flags = ari.ari_rate_001(doc)  # 12.5% is not 0/5/20
    assert flags and flags[0].severity == "WARN"


def test_ari_rate_standard_is_silent():
    for vat in ("0.00", "5.00", "20.00"):
        doc = _invoice(net_total=Money(amount="100.00"), vat_total=Money(amount=vat))
        assert not ari.ari_rate_001(doc)


def test_ari_negative_gross_on_invoice_warns():
    doc = _invoice(gross_total=Money(amount="-60.00"))
    flags = ari.ari_neg_001(doc)
    assert flags and flags[0].rule_id == "ARI-NEG-001"
    # A negative on a receipt is not this rule's concern.
    receipt = _invoice(doc_type=DocType.RECEIPT, gross_total=Money(amount="-60.00"))
    assert not ari.ari_neg_001(receipt)
