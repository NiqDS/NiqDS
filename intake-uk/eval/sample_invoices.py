"""Run the four user-supplied invoice images through the deterministic engine.

The automated vision/OCR extraction path is not built yet (deferred "Task A"),
so the fields below were transcribed BY HAND from the four images. That hand
transcription stands in for the model's extraction step. Every pass/fail
decision below is still made by the deterministic rules engine — the part of
the product that is actually being demonstrated.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models import DocType, ExtractedDocument, LineItem, Money
from app.rules.engine import run_bundle, sort_flags
from app.models import Bundle
from app.single import check_single


def M(amount: str, currency: str = "GBP") -> Money:
    return Money(amount=Decimal(amount), currency=currency)


DOCS = [
    # 1) Plumbing Co. #42228 — US supplier, no VAT, no date filled in.
    ExtractedDocument(
        source_file="5b66e880 · Plumbing Co #42228.png",
        doc_type=DocType.PURCHASE_INVOICE,
        confidence=0.92,
        supplier_name="Plumbing Co.",
        supplier_vat_number=None,
        customer_name="Mr Rogers",
        document_number="42228",
        document_date=None,  # "DATE ISSUED:" left blank on the invoice
        net_total=None,
        vat_total=None,
        gross_total=M("135", "USD"),
        line_items=[
            LineItem(description="Toilet bowl", quantity=Decimal("1"), gross=M("50", "USD")),
            LineItem(description="Branch line pipe", quantity=Decimal("1"), gross=M("15", "USD")),
            LineItem(description="Pipe connectors", quantity=Decimal("4"), gross=M("20", "USD")),
        ],
        raw_text_excerpt="PLUMBING CO. INVOICE NO: 42228 TOTAL DUE: $135 ... Labor $50 Total $135",
    ),
    # 2) Ellington Wood Decor #042022 — UK, GBP, no VAT shown.
    ExtractedDocument(
        source_file="6168f4e5 · Ellington Wood Decor #042022.png",
        doc_type=DocType.PURCHASE_INVOICE,
        confidence=0.97,
        supplier_name="Ellington Wood Decor",
        supplier_vat_number=None,
        customer_name="Your client",
        document_number="042022",
        document_date=date(2022, 4, 30),
        net_total=None,
        vat_total=None,
        gross_total=M("600", "GBP"),
        line_items=[
            LineItem(description="Sample service", quantity=Decimal("1"), gross=M("400")),
            LineItem(description="Sample service 1", quantity=Decimal("1"), gross=M("200")),
        ],
        raw_text_excerpt="INVOICE Ellington Wood Decor, 36 Terrick Rd, Ellington PE18 2NT ... TOTAL (GBP) £600.00",
    ),
    # 3) RealHandy #100-13 — UK, VAT 20%, VAT number GB123456789.
    ExtractedDocument(
        source_file="97097d5e · RealHandy #100-13.png",
        doc_type=DocType.PURCHASE_INVOICE,
        confidence=0.96,
        supplier_name="RealHandy",
        supplier_vat_number="GB123456789",
        customer_name="Mr Peter McDonald",
        document_number="100-13",
        document_date=date(2021, 8, 24),
        net_total=M("620"),
        vat_total=M("124"),
        gross_total=M("744"),
        line_items=[
            LineItem(description="Installation of new kitchen sink", quantity=Decimal("2"),
                     unit_price=M("70"), vat_rate=Decimal("20"), gross=M("168")),
            LineItem(description="Bathroom Refurbishment", quantity=Decimal("4"),
                     unit_price=M("120"), vat_rate=Decimal("20"), gross=M("576")),
        ],
        raw_text_excerpt="RealHandy ... VAT number: GB123456789 Total excl. VAT 620.00 GBP VAT 20% 124.00 GBP Total amount due 744.00 GBP",
    ),
    # 4) ABC Seller #012345 — UK, mixed/exempt lines, VAT number GB999 9999 73.
    ExtractedDocument(
        source_file="12efb195 · ABC Seller #012345.png",
        doc_type=DocType.SALES_INVOICE,
        confidence=0.95,
        supplier_name="ABC Seller",
        supplier_vat_number="GB999 9999 73",
        customer_name="XYZ Buyer",
        document_number="012345",
        document_date=date(2020, 5, 27),
        net_total=M("3300"),
        vat_total=M("60"),
        gross_total=M("3360"),
        line_items=[
            LineItem(description="Services, Products & Goods | Domestic", quantity=Decimal("1"), net=M("300"), vat_rate=Decimal("20")),
            LineItem(description="Services, Products & Goods | Export", quantity=Decimal("1"), net=M("800")),
            LineItem(description="Digital Goods | Export", quantity=Decimal("1"), net=M("400")),
            LineItem(description="Education & Training", quantity=Decimal("1"), net=M("600")),
            LineItem(description="Medical Service", quantity=Decimal("1"), net=M("1200")),
        ],
        raw_text_excerpt="ABC Seller ... VAT Reg No: GB999 9999 73 Subtotal GBP 3,300.00 VAT(20%) GBP 60.00 Total GBP 3,360.00",
    ),
]


def line(char="─", n=78):
    print(char * n)


for doc in DOCS:
    res = check_single(doc)
    line("═")
    print(f"FILE:    {doc.source_file}")
    print(f"TYPE:    {res.doc_type_label}   (extraction confidence {doc.confidence:.2f})")
    print(f"VERDICT: {res.verdict.upper()}  —  {res.headline}")
    print()
    for c in res.fields:
        mark = {"ok": "✓", "warn": "!", "invalid": "✗", "missing": "✗", "optional": "·"}.get(c.status, "?")
        val = c.value if c.value is not None else "—"
        print(f"  [{mark}] {c.label:<14} {val:<18} {c.status.upper()}")
        if c.note:
            print(f"        └ {c.note}")
    if res.fixes:
        print("\n  What the client would be asked to fix:")
        for fx in res.fixes:
            print(f"    • {fx}")
    print("\n  Rule audit trail:")
    for f in sort_flags(res.flags):
        print(f"    {f.severity:<5} {f.rule_id:<14} field={f.field or '-':<20} evidence={f.evidence!r}")

# Also run all four as one bundle so the set-level rules (duplicates, coverage) fire.
line("═")
bundle = Bundle(
    bundle_id="B-USER-INVOICES",
    client_name="Test client",
    declared_period_start=date(2020, 1, 1),
    declared_period_end=date(2026, 12, 31),
    documents=DOCS,
)
bflags = [f for f in sort_flags(run_bundle(bundle)) if f.document is None]
print("BUNDLE-LEVEL flags (all four together):")
if not bflags:
    print("  (none)")
for f in bflags:
    print(f"  {f.severity:<5} {f.rule_id:<14} {f.message}")
