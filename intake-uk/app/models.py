"""Pydantic v2 schemas for the Intake Gate.

Money is always ``Decimal`` — never ``float``. The arithmetic checks are the
demo and they must be exact. Do not introduce ``float`` anywhere on the money
path.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_serializer


class DocType(str, Enum):
    PURCHASE_INVOICE = "PURCHASE_INVOICE"
    RECEIPT = "RECEIPT"
    BANK_STATEMENT = "BANK_STATEMENT"
    SALES_INVOICE = "SALES_INVOICE"
    UNKNOWN = "UNKNOWN"


class Money(BaseModel):
    model_config = ConfigDict(frozen=True)

    amount: Decimal  # never float
    currency: str = "GBP"

    @field_serializer("amount")
    def _ser_amount(self, v: Decimal) -> str:
        # Serialise as a string so no float ever appears in JSON output.
        return format(v, "f")

    def __str__(self) -> str:  # pragma: no cover - convenience
        return f"{self.currency} {self.amount}"


class LineItem(BaseModel):
    description: str | None = None
    quantity: Decimal | None = None
    unit_price: Money | None = None
    net: Money | None = None
    vat_rate: Decimal | None = None
    vat: Money | None = None
    gross: Money | None = None


class ExtractedDocument(BaseModel):
    source_file: str
    doc_type: DocType
    confidence: float  # extraction confidence, NOT a pass/fail input
    supplier_name: str | None = None
    supplier_vat_number: str | None = None
    customer_name: str | None = None
    document_number: str | None = None
    document_date: date | None = None
    period_start: date | None = None  # bank statements
    period_end: date | None = None
    net_total: Money | None = None
    vat_total: Money | None = None
    gross_total: Money | None = None
    line_items: list[LineItem] = []
    account_identifier: str | None = None  # last 4 of account, or sort code
    raw_text_excerpt: str = ""  # for audit trail
    page_count: int = 1


class Bundle(BaseModel):
    bundle_id: str
    client_name: str
    declared_period_start: date  # what the client SAYS this covers
    declared_period_end: date
    expected_accounts: list[str] = []  # e.g. ["12345678", "87654321"]
    documents: list[ExtractedDocument] = []


class Flag(BaseModel):
    rule_id: str
    severity: Literal["BLOCK", "WARN", "INFO"]
    field: str | None = None
    document: str | None = None  # source_file, or None for bundle-level
    message: str  # human-readable, client-safe
    evidence: str | None = None  # the offending value
