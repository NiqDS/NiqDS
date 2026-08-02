"""Format checks — VAT number, dates, currency, postcode, sort/account codes,
supplier name, legibility.

Each rule is a pure function ``(ExtractedDocument) -> list[Flag]``.
"""

from __future__ import annotations

from app.models import DocType, ExtractedDocument, Flag
from app.rules.engine import document_rule, make_flag
from app.util import (
    parse_uk_date,
    valid_account_number,
    valid_sort_code,
    valid_uk_postcode,
    valid_uk_vat,
)

LEGIBILITY_CONFIDENCE_THRESHOLD = 0.40
MIN_TEXT_CHARS = 20


@document_rule
def fmt_vat_001(doc: ExtractedDocument) -> list[Flag]:
    """FMT-VAT-001 — UK VAT registration number fails the check digit."""

    vat = doc.supplier_vat_number
    if not vat:
        return []
    if valid_uk_vat(vat):
        return []
    return [
        make_flag(
            "FMT-VAT-001",
            field="supplier_vat_number",
            document=doc.source_file,
            evidence=vat,
            supplier_name=doc.supplier_name or "the supplier",
        )
    ]


@document_rule
def fmt_date_001(doc: ExtractedDocument) -> list[Flag]:
    """FMT-DATE-001 — document date missing or unparseable.

    Bank statements are dated by their period, not a single document date, so
    they are exempt from this check.
    """

    if doc.doc_type == DocType.BANK_STATEMENT:
        return []
    if doc.document_date is not None:
        return []
    return [
        make_flag(
            "FMT-DATE-001",
            field="document_date",
            document=doc.source_file,
            supplier_name=doc.supplier_name or "the supplier",
        )
    ]


@document_rule
def fmt_date_002(doc: ExtractedDocument) -> list[Flag]:
    """FMT-DATE-002 — the date could be read two ways (DD/MM vs MM/DD).

    We resolve UK-style (DD/MM) during extraction, but if the *token* in the
    audit excerpt is genuinely ambiguous we surface a WARN rather than guess
    silently.
    """

    if doc.document_date is None:
        return []
    _parsed, ambiguous = parse_uk_date(doc.raw_text_excerpt)
    if not ambiguous:
        return []
    # Report the offending token as day/month/year for the human reader.
    evidence = doc.document_date.strftime("%d/%m/%Y")
    return [
        make_flag(
            "FMT-DATE-002",
            field="document_date",
            document=doc.source_file,
            evidence=evidence,
            supplier_name=doc.supplier_name or "the supplier",
        )
    ]


@document_rule
def fmt_cur_001(doc: ExtractedDocument) -> list[Flag]:
    """FMT-CUR-001 — currency is not GBP (WARN, not BLOCK)."""

    for money in (doc.gross_total, doc.net_total, doc.vat_total):
        if money is not None and money.currency and money.currency.upper() != "GBP":
            return [
                make_flag(
                    "FMT-CUR-001",
                    field="currency",
                    document=doc.source_file,
                    evidence=money.currency.upper(),
                    supplier_name=doc.supplier_name or "the supplier",
                )
            ]
    return []


@document_rule
def fmt_post_001(doc: ExtractedDocument) -> list[Flag]:
    """FMT-POST-001 — a postcode-looking token in the audit excerpt is malformed.

    Only fires when something that clearly *looks like* a postcode attempt is
    present but fails the pattern — a document with no postcode at all is fine.
    """

    import re

    text = doc.raw_text_excerpt or ""
    # A crude "there is a postcode here" trigger: two groups near the end.
    candidates = re.findall(r"\b([A-Za-z]{1,2}\d[A-Za-z\d]?\s*\d[A-Za-z]{2})\b", text)
    # If a well-formed postcode exists we are happy; only flag if a malformed
    # one is present and no valid one is.
    if any(valid_uk_postcode(c) for c in candidates):
        return []
    # Look for a malformed attempt: an outward code followed by digits/letters.
    malformed = re.search(r"\b([A-Za-z]{1,2}\d[A-Za-z\d]?\s+\d[A-Za-z]{1,3})\b", text)
    if malformed and not valid_uk_postcode(malformed.group(1)):
        return [
            make_flag(
                "FMT-POST-001",
                field="postcode",
                document=doc.source_file,
                evidence=malformed.group(1).upper(),
                supplier_name=doc.supplier_name or "the supplier",
            )
        ]
    return []


@document_rule
def fmt_sort_001(doc: ExtractedDocument) -> list[Flag]:
    """FMT-SORT-001 — sort code not 6 digits (bank statements only)."""

    if doc.doc_type != DocType.BANK_STATEMENT:
        return []
    ident = doc.account_identifier
    if ident is None:
        return []
    # Sort codes are formatted nn-nn-nn; treat a hyphenated identifier as one.
    if "-" not in ident:
        return []
    if valid_sort_code(ident):
        return []
    return [
        make_flag(
            "FMT-SORT-001",
            field="account_identifier",
            document=doc.source_file,
            evidence=ident,
        )
    ]


@document_rule
def fmt_acct_001(doc: ExtractedDocument) -> list[Flag]:
    """FMT-ACCT-001 — account number not 8 digits (bank statements only).

    A bare last-4 identifier (e.g. ``4471``) is an intentional partial and is
    not flagged; a full account number that isn't 8 digits is.
    """

    if doc.doc_type != DocType.BANK_STATEMENT:
        return []
    ident = doc.account_identifier
    if ident is None:
        return []
    from app.util import digits_only

    d = digits_only(ident)
    if "-" in ident:  # that's a sort code, handled elsewhere
        return []
    if len(d) <= 4:  # deliberate partial ("ending 4471")
        return []
    if valid_account_number(ident):
        return []
    return [
        make_flag(
            "FMT-ACCT-001",
            field="account_identifier",
            document=doc.source_file,
            evidence=ident,
        )
    ]


@document_rule
def fmt_supp_001(doc: ExtractedDocument) -> list[Flag]:
    """FMT-SUPP-001 — supplier name absent or under 2 characters.

    Bank statements name the bank, not a supplier, so they are exempt.
    """

    if doc.doc_type == DocType.BANK_STATEMENT:
        return []
    name = (doc.supplier_name or "").strip()
    if len(name) >= 2:
        return []
    return [
        make_flag(
            "FMT-SUPP-001",
            field="supplier_name",
            document=doc.source_file,
        )
    ]


@document_rule
def fmt_legib_001(doc: ExtractedDocument) -> list[Flag]:
    """FMT-LEGIB-001 — extraction confidence too low OR too little text.

    Do NOT try to guess at low-confidence documents; flagging is the correct
    behaviour and is a selling point.
    """

    too_low_conf = doc.confidence < LEGIBILITY_CONFIDENCE_THRESHOLD
    too_little_text = len((doc.raw_text_excerpt or "").strip()) < MIN_TEXT_CHARS
    if not (too_low_conf or too_little_text):
        return []
    return [
        make_flag(
            "FMT-LEGIB-001",
            field="confidence",
            document=doc.source_file,
            evidence=f"{doc.confidence:.2f}",
        )
    ]


@document_rule
def cls_type_001(doc: ExtractedDocument) -> list[Flag]:
    """CLS-TYPE-001 — document type could not be identified (UNKNOWN).

    UNKNOWN is itself a flag, not a silent pass.
    """

    if doc.doc_type != DocType.UNKNOWN:
        return []
    return [
        make_flag(
            "CLS-TYPE-001",
            field="doc_type",
            document=doc.source_file,
            evidence=doc.source_file,
        )
    ]
