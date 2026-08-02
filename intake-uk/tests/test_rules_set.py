"""Bundle-level / set-rule tests — the differentiating checks."""

from __future__ import annotations

from datetime import date

from app.models import Bundle, DocType, ExtractedDocument, Money
from app.rules import checks_set as st


def _stmt(source, ps, pe, acct="12344471") -> ExtractedDocument:
    return ExtractedDocument(
        source_file=source, doc_type=DocType.BANK_STATEMENT, confidence=0.9,
        period_start=ps, period_end=pe, account_identifier=acct,
        raw_text_excerpt=f"Barclays statement account {acct}",
    )


def _bundle(docs, **kw) -> Bundle:
    base = dict(
        bundle_id="B", client_name="Harbourside Ltd",
        declared_period_start=date(2026, 2, 1), declared_period_end=date(2026, 6, 30),
        documents=docs,
    )
    base.update(kw)
    return Bundle(**base)


def test_statement_gap_named_as_month():
    docs = [
        _stmt("feb.pdf", date(2026, 2, 1), date(2026, 2, 28)),
        _stmt("mar.pdf", date(2026, 3, 1), date(2026, 3, 31)),
        _stmt("may.pdf", date(2026, 5, 1), date(2026, 5, 31)),
        _stmt("jun.pdf", date(2026, 6, 1), date(2026, 6, 30)),
    ]
    flags = st.set_stmt_001(_bundle(docs))
    assert len(flags) == 1
    f = flags[0]
    assert f.rule_id == "SET-STMT-001"
    assert "April 2026" in f.message  # not a count — a named month
    assert "4471" in f.message


def test_statement_gap_at_boundaries():
    # First statement starts after the declared period start -> leading gap.
    docs = [_stmt("mar.pdf", date(2026, 3, 1), date(2026, 3, 31))]
    flags = st.set_stmt_001(_bundle(docs))
    ranges = [f.evidence for f in flags]
    # February missing before, April/May/June missing after.
    assert any("February 2026" == r for r in ranges)


def test_expected_account_with_no_documents_blocks():
    docs = [_stmt("feb.pdf", date(2026, 2, 1), date(2026, 2, 28))]
    flags = st.set_acct_001(_bundle(docs, expected_accounts=["12344471", "99995555"]))
    assert len(flags) == 1
    assert flags[0].rule_id == "SET-ACCT-001"
    assert flags[0].severity == "BLOCK"
    assert "5555" in flags[0].message


def test_duplicate_exact_match():
    def inv(source):
        return ExtractedDocument(
            source_file=source, doc_type=DocType.PURCHASE_INVOICE, confidence=0.95,
            supplier_name="Hartley Supplies Ltd", document_number="INV-1001",
            gross_total=Money(amount="120.00"), document_date=date(2026, 2, 20),
            raw_text_excerpt="Hartley Supplies invoice INV-1001",
        )
    flags = st.set_dup_001(_bundle([inv("a.pdf"), inv("b.pdf")],
                                   declared_period_start=date(2026, 1, 1)))
    assert len(flags) == 1 and flags[0].rule_id == "SET-DUP-001"


def test_duplicate_fuzzy_no_number():
    def inv(source, d):
        return ExtractedDocument(
            source_file=source, doc_type=DocType.RECEIPT, confidence=0.95,
            supplier_name="Corner Shop", document_number=None,
            gross_total=Money(amount="4.20"), document_date=d,
            raw_text_excerpt="Corner Shop receipt",
        )
    flags = st.set_dup_001(_bundle([inv("a.pdf", date(2026, 2, 10)),
                                    inv("b.pdf", date(2026, 2, 12))],
                                   declared_period_start=date(2026, 1, 1)))
    assert len(flags) == 1 and flags[0].rule_id == "SET-DUP-001"


def test_set_empty_uses_client_profile():
    st.set_client_profiles({"Bright Cafe Ltd": ["PURCHASE_INVOICE", "BANK_STATEMENT"]})
    try:
        docs = [_stmt("feb.pdf", date(2026, 2, 1), date(2026, 2, 28))]
        flags = st.set_empty_001(_bundle(docs, client_name="Bright Cafe Ltd"))
        assert len(flags) == 1
        assert flags[0].rule_id == "SET-EMPTY-001"
        assert "purchase invoices" in flags[0].message
    finally:
        st.load_client_profiles()  # restore default
