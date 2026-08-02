"""Deterministic, offline fake extractor.

Keeps the repo runnable with zero configuration and zero API keys. For the
shipped fixtures it returns the hand-written extracted JSON keyed by filename, so
the demo (drop the 12 generated PDFs in, watch red come out) is fully
reproducible. For any other file it does a best-effort regex transcription of
the page text — good enough to exercise the pipeline, never used for validation.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from app.util import parse_uk_date

_EXTRACTED_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "extracted"


@lru_cache(maxsize=1)
def _fixture_index() -> dict[str, dict]:
    index: dict[str, dict] = {}
    if _EXTRACTED_DIR.exists():
        for path in _EXTRACTED_DIR.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            index[data["source_file"]] = data
    return index


class MockBackend:
    name = "mock"

    def extract_json(self, source_file: str, text: str) -> dict:
        basename = Path(source_file).name
        fixture = _fixture_index().get(basename)
        if fixture is not None:
            return dict(fixture)
        return _naive_extract(basename, text)


def _naive_extract(source_file: str, text: str) -> dict:
    from app.ingest.classify import classify

    doc_type = classify(text).value
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    supplier = lines[0] if lines else None

    vat = None
    m = re.search(r"\bVAT(?:\s*(?:No|Number|Reg)\.?:?)?\s*((?:GB)?[\d\s]{9,15})", text, re.I)
    if m:
        vat = m.group(1).strip()

    docnum = None
    m = re.search(r"\b(?:Invoice|Inv|Receipt|Ref)\.?\s*(?:No\.?|#|number)?\s*[:\-]?\s*([A-Z0-9\-]{3,})", text, re.I)
    if m:
        docnum = m.group(1)

    doc_date, _ = parse_uk_date(text)

    def find_money(label):
        m = re.search(rf"{label}\s*[:£$€]?\s*([\d,]+\.\d{{2}})", text, re.I)
        if not m:
            return None
        currency = "GBP"
        if "€" in text or re.search(r"\bEUR\b", text):
            currency = "EUR"
        elif "$" in text or re.search(r"\bUSD\b", text):
            currency = "USD"
        return {"amount": m.group(1).replace(",", ""), "currency": currency}

    return {
        "doc_type": doc_type,
        "supplier_name": supplier,
        "supplier_vat_number": vat,
        "customer_name": None,
        "document_number": docnum,
        "document_date": doc_date.isoformat() if doc_date else None,
        "period_start": None,
        "period_end": None,
        "net_total": find_money("Net"),
        "vat_total": find_money("VAT"),
        "gross_total": find_money("Total"),
        "line_items": [],
        "account_identifier": None,
        "raw_text_excerpt": text[:800],
    }
