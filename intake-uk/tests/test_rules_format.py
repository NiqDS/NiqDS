"""Format-rule tests. No model, no network — pure functions over typed data."""

from __future__ import annotations

from datetime import date

import pytest

from app.models import DocType, ExtractedDocument, Money
from app.rules import checks_format as fmt
from app.util import parse_uk_date, valid_uk_postcode, valid_uk_vat


# ---------------------------------------------------------------------------
# FMT-VAT-001 — the flagship rule. Table-driven.
# ---------------------------------------------------------------------------

# Valid under the classic "mod 97" variant (and therefore fails "mod 9755").
VALID_CLASSIC = ["197126932", "956341605"]
# Valid under the newer "mod 9755" variant (and therefore fails the classic).
VALID_NEWER = ["427472780", "563431297"]
# Structural / prefix valids.
VALID_FORMAT = [
    "GB 197 126 932",  # GB prefix + spaces, classic
    "197126932001",    # 12-digit branch trader, first 9 valid
    "GD012",           # government department, range 000-499
    "HA599",           # health authority, range 500-999
]
VALID = VALID_CLASSIC + VALID_NEWER + VALID_FORMAT

INVALID = [
    "917126932",  # transposition of a valid number
    "247472780",  # transposition of a valid number
    "291417776",  # fails both variants
    "317066907",  # fails both variants
    "12345678",   # too short
    "1234567890", # 10 digits, not a valid length
    "GD500",      # government dept out of range
    "HA400",      # health authority out of range
    "GB12A456789",# non-numeric body
]


@pytest.mark.parametrize("vat", VALID)
def test_vat_valid(vat):
    assert valid_uk_vat(vat) is True, vat


@pytest.mark.parametrize("vat", INVALID)
def test_vat_invalid(vat):
    assert valid_uk_vat(vat) is False, vat


def test_vat_classic_only_and_newer_only():
    """One number valid only under classic, one only under 9755 — both accepted."""

    # 197126932 is classic-valid; confirm it would fail the 9755 variant alone.
    d = [int(c) for c in "197126932"]
    s = 8*d[0]+7*d[1]+6*d[2]+5*d[3]+4*d[4]+3*d[5]+2*d[6]
    check = d[7]*10 + d[8]
    assert (s + check) % 97 == 0          # passes classic
    assert (s + check + 55) % 97 != 0     # fails 9755
    assert valid_uk_vat("197126932")

    # 427472780 is 9755-valid; confirm it would fail the classic variant alone.
    d = [int(c) for c in "427472780"]
    s = 8*d[0]+7*d[1]+6*d[2]+5*d[3]+4*d[4]+3*d[5]+2*d[6]
    check = d[7]*10 + d[8]
    assert (s + check) % 97 != 0          # fails classic
    assert (s + check + 55) % 97 == 0     # passes 9755
    assert valid_uk_vat("427472780")


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


def test_fmt_vat_rule_fires_on_bad_and_silent_on_good():
    assert fmt.fmt_vat_001(_invoice(supplier_vat_number="917126932"))
    assert not fmt.fmt_vat_001(_invoice(supplier_vat_number="197126932"))
    # Absent VAT number is not FMT-VAT-001's business.
    assert not fmt.fmt_vat_001(_invoice(supplier_vat_number=None))


# ---------------------------------------------------------------------------
# FMT-DATE
# ---------------------------------------------------------------------------


def test_fmt_date_missing():
    doc = _invoice(document_date=None, raw_text_excerpt="no date on this one at all")
    assert fmt.fmt_date_001(doc)
    doc2 = _invoice(document_date=date(2026, 2, 20))
    assert not fmt.fmt_date_001(doc2)


def test_bank_statement_exempt_from_date_rule():
    doc = ExtractedDocument(
        source_file="s.pdf", doc_type=DocType.BANK_STATEMENT, confidence=0.9,
        document_date=None, raw_text_excerpt="Barclays statement period Feb 2026",
    )
    assert not fmt.fmt_date_001(doc)


def test_parse_uk_date_is_dd_mm():
    d, ambiguous = parse_uk_date("Invoice date 03/04/2026")
    assert d == date(2026, 4, 3)  # 3 April, not 4 March
    assert ambiguous is True       # could also be 4 March


def test_parse_uk_date_unambiguous_when_day_over_12():
    d, ambiguous = parse_uk_date("20/02/2026")
    assert d == date(2026, 2, 20)
    assert ambiguous is False


def test_parse_uk_date_textual_never_ambiguous():
    d, ambiguous = parse_uk_date("dated 3 April 2026")
    assert d == date(2026, 4, 3)
    assert ambiguous is False


def test_fmt_date_002_warns_on_ambiguous_token():
    doc = _invoice(document_date=date(2026, 4, 3),
                   raw_text_excerpt="Invoice dated 03/04/2026 total due 60.00")
    flags = fmt.fmt_date_002(doc)
    assert flags and flags[0].rule_id == "FMT-DATE-002"
    assert flags[0].severity == "WARN"


# ---------------------------------------------------------------------------
# FMT-CUR / FMT-POST / FMT-SORT / FMT-ACCT / FMT-SUPP / FMT-LEGIB
# ---------------------------------------------------------------------------


def test_fmt_currency_non_gbp():
    doc = _invoice(gross_total=Money(amount="120.00", currency="EUR"))
    flags = fmt.fmt_cur_001(doc)
    assert flags and flags[0].severity == "WARN"
    doc2 = _invoice(gross_total=Money(amount="120.00", currency="GBP"))
    assert not fmt.fmt_cur_001(doc2)


def test_postcode_helper():
    assert valid_uk_postcode("SW1A 1AA")
    assert valid_uk_postcode("EC1A1BB")
    assert not valid_uk_postcode("LOL 999")


def test_fmt_sort_and_acct():
    good = ExtractedDocument(source_file="s.pdf", doc_type=DocType.BANK_STATEMENT,
                             confidence=0.9, account_identifier="12344471",
                             raw_text_excerpt="Barclays statement account 12344471")
    assert not fmt.fmt_acct_001(good)
    bad_acct = ExtractedDocument(source_file="s.pdf", doc_type=DocType.BANK_STATEMENT,
                                 confidence=0.9, account_identifier="1234567",
                                 raw_text_excerpt="Barclays statement account 1234567")
    assert fmt.fmt_acct_001(bad_acct)
    bad_sort = ExtractedDocument(source_file="s.pdf", doc_type=DocType.BANK_STATEMENT,
                                 confidence=0.9, account_identifier="12-34-5",
                                 raw_text_excerpt="Barclays statement sort 12-34-5")
    assert fmt.fmt_sort_001(bad_sort)


def test_fmt_supplier_missing():
    doc = _invoice(supplier_name="")
    assert fmt.fmt_supp_001(doc)
    assert not fmt.fmt_supp_001(_invoice(supplier_name="Acme Ltd"))


def test_fmt_legibility():
    low_conf = _invoice(confidence=0.2)
    assert fmt.fmt_legib_001(low_conf)
    short_text = _invoice(confidence=0.95, raw_text_excerpt="blur")
    assert fmt.fmt_legib_001(short_text)
    ok = _invoice(confidence=0.95, raw_text_excerpt="a perfectly legible invoice line here")
    assert not fmt.fmt_legib_001(ok)
