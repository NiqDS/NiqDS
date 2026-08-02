"""Deterministic document-type classification from page text.

This is a *hint* generator, not a validation decision. UNKNOWN is a legitimate,
useful outcome — it is itself a flag (CLS-TYPE-001), not a silent pass.
"""

from __future__ import annotations

import re

from app.models import DocType


def classify(text: str) -> DocType:
    t = (text or "").lower()

    # Bank statement: statement + period/balance language.
    if "statement" in t and re.search(r"\b(sort code|account (no|number)|opening balance|closing balance|statement period)\b", t):
        return DocType.BANK_STATEMENT
    if re.search(r"\bbank statement\b", t):
        return DocType.BANK_STATEMENT

    # Delivery notes, purchase orders, quotes etc. are none of the four types.
    if re.search(r"\b(delivery note|goods received note|purchase order|quotation|remittance advice)\b", t):
        return DocType.UNKNOWN

    if "receipt" in t and "invoice" not in t:
        return DocType.RECEIPT

    if "invoice" in t:
        # Sales invoice if the business is the one issuing it (heuristic).
        if re.search(r"\b(sales invoice|tax invoice to|bill to)\b", t):
            return DocType.SALES_INVOICE
        return DocType.PURCHASE_INVOICE

    return DocType.UNKNOWN
