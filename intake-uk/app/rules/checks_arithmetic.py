"""Arithmetic checks — the demo. Every calculation uses ``Decimal``; no float
ever appears on the money path.
"""

from __future__ import annotations

from decimal import Decimal

from app.models import DocType, ExtractedDocument, Flag
from app.rules.engine import document_rule, make_flag

TOLERANCE = Decimal("0.02")  # rounding tolerance in GBP
_STANDARD_RATES = (Decimal("0"), Decimal("5"), Decimal("20"))
_RATE_TOLERANCE = Decimal("0.5")  # percentage points

_INVOICE_TYPES = {DocType.PURCHASE_INVOICE, DocType.SALES_INVOICE}


@document_rule
def ari_vat_001(doc: ExtractedDocument) -> list[Flag]:
    """ARI-VAT-001 — net + VAT != gross (tolerance £0.02)."""

    if doc.net_total is None or doc.vat_total is None or doc.gross_total is None:
        return []
    expected = doc.net_total.amount + doc.vat_total.amount
    if abs(expected - doc.gross_total.amount) <= TOLERANCE:
        return []
    return [
        make_flag(
            "ARI-VAT-001",
            field="gross_total",
            document=doc.source_file,
            evidence=f"£{doc.gross_total.amount}",
            supplier_name=doc.supplier_name or "the supplier",
        )
    ]


@document_rule
def ari_line_001(doc: ExtractedDocument) -> list[Flag]:
    """ARI-LINE-001 — sum of line nets != document net (tolerance £0.02)."""

    if doc.net_total is None:
        return []
    line_nets = [li.net.amount for li in doc.line_items if li.net is not None]
    if not line_nets:
        return []
    total = sum(line_nets, Decimal("0"))
    if abs(total - doc.net_total.amount) <= TOLERANCE:
        return []
    return [
        make_flag(
            "ARI-LINE-001",
            field="line_items",
            document=doc.source_file,
            evidence=f"£{doc.net_total.amount}",
            supplier_name=doc.supplier_name or "the supplier",
        )
    ]


@document_rule
def ari_rate_001(doc: ExtractedDocument) -> list[Flag]:
    """ARI-RATE-001 — implied VAT rate not within 0.5pp of 0%, 5% or 20% (WARN)."""

    if doc.net_total is None or doc.vat_total is None:
        return []
    net = doc.net_total.amount
    if net == 0:
        return []
    implied = (doc.vat_total.amount / net) * Decimal("100")
    if any(abs(implied - r) <= _RATE_TOLERANCE for r in _STANDARD_RATES):
        return []
    return [
        make_flag(
            "ARI-RATE-001",
            field="vat_total",
            document=doc.source_file,
            evidence=f"{implied.quantize(Decimal('0.1'))}%",
            supplier_name=doc.supplier_name or "the supplier",
        )
    ]


@document_rule
def ari_neg_001(doc: ExtractedDocument) -> list[Flag]:
    """ARI-NEG-001 — negative gross on a document typed as an invoice."""

    if doc.doc_type not in _INVOICE_TYPES:
        return []
    if doc.gross_total is None or doc.gross_total.amount >= 0:
        return []
    return [
        make_flag(
            "ARI-NEG-001",
            field="gross_total",
            document=doc.source_file,
            evidence=f"£{doc.gross_total.amount}",
            supplier_name=doc.supplier_name or "the supplier",
        )
    ]
