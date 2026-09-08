"""Single-document checker for the scan app.

Given one extracted document, it reports — per field — what was found and whether
it's filled in correctly, plus an overall verdict. It reuses the deterministic
rules engine for every validity decision (VAT check digit, arithmetic,
legibility, …); nothing here makes a judgement the engine doesn't.

This is the phone-first counterpart to the practice bundle view: one document,
"is this complete and correct?".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.models import DocType, ExtractedDocument, Flag, Money
from app.rules.checks_format import LEGIBILITY_CONFIDENCE_THRESHOLD  # noqa: F401
from app.rules.engine import run_document

DOC_TYPE_LABEL = {
    DocType.PURCHASE_INVOICE: "Purchase invoice",
    DocType.SALES_INVOICE: "Sales invoice",
    DocType.RECEIPT: "Receipt",
    DocType.BANK_STATEMENT: "Bank statement",
    DocType.UNKNOWN: "Unrecognised document",
}

# (attribute, label, required?) per document type.
_EXPECTED: dict[DocType, list[tuple[str, str, bool]]] = {
    DocType.PURCHASE_INVOICE: [
        ("supplier_name", "Supplier", True),
        ("supplier_vat_number", "VAT number", False),
        ("document_number", "Invoice number", True),
        ("document_date", "Date", True),
        ("net_total", "Net", True),
        ("vat_total", "VAT", False),
        ("gross_total", "Total", True),
    ],
    DocType.RECEIPT: [
        ("supplier_name", "Shop / supplier", True),
        ("document_date", "Date", True),
        ("gross_total", "Total", True),
        ("supplier_vat_number", "VAT number", False),
    ],
    DocType.BANK_STATEMENT: [
        ("account_identifier", "Account / sort code", True),
        ("period_start", "Statement from", True),
        ("period_end", "Statement to", True),
    ],
}
_EXPECTED[DocType.SALES_INVOICE] = _EXPECTED[DocType.PURCHASE_INVOICE]


@dataclass
class FieldCheck:
    key: str
    label: str
    status: str  # "ok" | "missing" | "invalid" | "warn" | "optional"
    value: str | None
    note: str | None = None


@dataclass
class SingleResult:
    source_file: str
    doc_type: DocType
    doc_type_label: str
    confidence: float
    verdict: str  # "ready" | "fix" | "unreadable" | "unknown"
    headline: str
    subhead: str
    fields: list[FieldCheck] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)  # plain-English things to fix
    flags: list[Flag] = field(default_factory=list)  # for audit / traceability


def _display(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, Money):
        sym = {"GBP": "£", "EUR": "€", "USD": "$"}.get(value.currency, "")
        return f"{sym}{value.amount}"
    if isinstance(value, date):
        return value.strftime("%-d %b %Y")
    text = str(value).strip()
    return text or None


def check_single(doc: ExtractedDocument) -> SingleResult:
    flags = run_document(doc)
    by_field: dict[str | None, list[Flag]] = {}
    for f in flags:
        by_field.setdefault(f.field, []).append(f)

    label = DOC_TYPE_LABEL.get(doc.doc_type, "Document")

    # 1) Too unclear to read — don't trust any extracted field.
    legibility = [f for f in flags if f.rule_id == "FMT-LEGIB-001"]
    if legibility:
        return SingleResult(
            source_file=doc.source_file, doc_type=doc.doc_type, doc_type_label=label,
            confidence=doc.confidence, verdict="unreadable",
            headline="Too blurry to read",
            subhead="We couldn't read this clearly enough to trust it. Please retake the photo in better light, filling the frame.",
            fixes=[legibility[0].message], flags=flags,
        )

    # 2) Couldn't identify the document type.
    if doc.doc_type == DocType.UNKNOWN:
        return SingleResult(
            source_file=doc.source_file, doc_type=doc.doc_type, doc_type_label=label,
            confidence=doc.confidence, verdict="unknown",
            headline="Not a document we recognise",
            subhead="This doesn't look like an invoice, receipt or bank statement. Check you photographed the right page.",
            fixes=[], flags=flags,
        )

    # 3) Field-by-field completeness + validity.
    fields: list[FieldCheck] = []
    fixes: list[str] = []
    for attr, flabel, required in _EXPECTED.get(doc.doc_type, []):
        value = getattr(doc, attr, None)
        disp = _display(value)
        field_flags = by_field.get(attr, [])
        block = next((f for f in field_flags if f.severity == "BLOCK"), None)
        warn = next((f for f in field_flags if f.severity == "WARN"), None)

        if disp is None and required:
            # Absent required field reads as "missing", even if a rule also fired
            # on it (e.g. a missing date). Prefer the rule's client-safe message.
            note = block.message if block else f"We couldn't find the {flabel.lower()} on this document."
            fields.append(FieldCheck(attr, flabel, "missing", None, note))
            fixes.append(note)
        elif disp is None:
            fields.append(FieldCheck(attr, flabel, "optional", None, "Not present (that's usually fine)."))
        elif block is not None:
            fields.append(FieldCheck(attr, flabel, "invalid", disp, block.message))
            fixes.append(block.message)
        elif warn is not None:
            fields.append(FieldCheck(attr, flabel, "warn", disp, warn.message))
        else:
            fields.append(FieldCheck(attr, flabel, "ok", disp, None))

    # Any document-scoped BLOCK not tied to a listed field (e.g. line-item sum).
    for f in flags:
        if f.severity == "BLOCK" and f.field not in {c.key for c in fields}:
            if f.message not in fixes:
                fixes.append(f.message)

    needs_fix = any(c.status in {"invalid", "missing"} for c in fields) or bool(
        [f for f in flags if f.severity == "BLOCK" and f.field not in {c.key for c in fields}]
    )
    if needs_fix:
        verdict, headline = "fix", "A few things to fix"
        subhead = f"We read this as a {label.lower()}. Sort the items below and it's good to send."
    else:
        verdict, headline = "ready", "Looks complete"
        subhead = f"We read this as a {label.lower()} and everything expected is present and valid."

    return SingleResult(
        source_file=doc.source_file, doc_type=doc.doc_type, doc_type_label=label,
        confidence=doc.confidence, verdict=verdict, headline=headline, subhead=subhead,
        fields=fields, fixes=fixes, flags=flags,
    )
