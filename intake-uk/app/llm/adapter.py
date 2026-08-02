"""Provider-agnostic LLM extraction adapter.

The model's ONLY job is turning a document into typed JSON. Every pass/fail
decision is made elsewhere by deterministic code. Three backends are supported:

    * ``mock``      — deterministic, offline, no API key (the default)
    * ``anthropic`` — Claude, via the ``anthropic`` SDK
    * ``openai``    — GPT, via the ``openai`` SDK

Switching ``LLM_BACKEND=mock`` -> ``anthropic`` requires no code change outside
``.env``. The real backends are imported lazily so the app runs offline on the
default backend with neither SDK installed.
"""

from __future__ import annotations

import json
import os
import re
from typing import Protocol

from app.models import ExtractedDocument

# The extraction contract handed to the model. Field-by-field, JSON only.
EXTRACTION_PROMPT = """You are a document extraction engine for a UK bookkeeping intake system.
Return ONLY a single JSON object describing the document. Do not validate,
correct, or judge anything — transcribe exactly what the document says. If a
field is not present, use null.

JSON shape (money is an object {"amount": "<string>", "currency": "GBP"}):
{
  "doc_type": "PURCHASE_INVOICE | RECEIPT | BANK_STATEMENT | SALES_INVOICE | UNKNOWN",
  "supplier_name": string|null,
  "supplier_vat_number": string|null,
  "customer_name": string|null,
  "document_number": string|null,
  "document_date": "YYYY-MM-DD"|null,
  "period_start": "YYYY-MM-DD"|null,
  "period_end": "YYYY-MM-DD"|null,
  "net_total": money|null,
  "vat_total": money|null,
  "gross_total": money|null,
  "line_items": [{"description": string|null, "net": money|null,
                  "vat_rate": string|null, "vat": money|null, "gross": money|null}],
  "account_identifier": string|null
}

Read dates UK-style (DD/MM/YYYY). Transcribe amounts as strings, never rounding.
Document text follows:
---
{TEXT}
---
Return only the JSON object."""


class ExtractionBackend(Protocol):
    name: str

    def extract_json(self, source_file: str, text: str) -> dict:  # pragma: no cover
        ...


def _coerce_money(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return {"amount": str(value.get("amount")), "currency": value.get("currency", "GBP")}
    # Bare number/string -> assume GBP.
    return {"amount": str(value), "currency": "GBP"}


def _coerce(raw: dict, source_file: str, page_count: int, confidence: float) -> ExtractedDocument:
    """Turn a backend's loose JSON into a validated ExtractedDocument."""

    data = dict(raw)
    for key in ("net_total", "vat_total", "gross_total"):
        data[key] = _coerce_money(data.get(key))
    items = []
    for li in data.get("line_items") or []:
        items.append(
            {
                "description": li.get("description"),
                "quantity": li.get("quantity"),
                "unit_price": _coerce_money(li.get("unit_price")),
                "net": _coerce_money(li.get("net")),
                "vat_rate": li.get("vat_rate"),
                "vat": _coerce_money(li.get("vat")),
                "gross": _coerce_money(li.get("gross")),
            }
        )
    data["line_items"] = items
    data.setdefault("doc_type", "UNKNOWN")
    data["source_file"] = source_file
    data["page_count"] = page_count
    data.setdefault("confidence", confidence)
    # Backends never see the audit excerpt; fill it from the source text upstream.
    data.setdefault("raw_text_excerpt", raw.get("raw_text_excerpt", ""))
    return ExtractedDocument.model_validate(data)


def get_backend(name: str | None = None) -> ExtractionBackend:
    name = (name or os.environ.get("LLM_BACKEND", "mock")).lower()
    if name == "mock":
        from app.llm.mock import MockBackend

        return MockBackend()
    if name == "anthropic":
        return _AnthropicBackend()
    if name == "openai":
        return _OpenAIBackend()
    raise ValueError(f"unknown LLM backend: {name!r}")


def extract(
    source_file: str,
    text: str,
    *,
    page_count: int = 1,
    confidence: float = 0.95,
    backend: str | None = None,
) -> ExtractedDocument:
    """Extract a typed document using the configured backend."""

    be = get_backend(backend)
    raw = be.extract_json(source_file, text)
    doc = _coerce(raw, source_file, page_count, confidence)
    if not doc.raw_text_excerpt:
        doc = doc.model_copy(update={"raw_text_excerpt": text[:800]})
    return doc


def _extract_json_object(s: str) -> dict:
    """Pull the first JSON object out of a model response."""

    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", s).strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model response")
    return json.loads(s[start : end + 1])


class _AnthropicBackend:
    name = "anthropic"

    def extract_json(self, source_file: str, text: str) -> dict:
        import anthropic  # lazy — only needed for this backend

        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
        prompt = EXTRACTION_PROMPT.replace("{TEXT}", text)
        resp = client.messages.create(
            model=model,
            max_tokens=2000,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        return _extract_json_object(resp.content[0].text)


class _OpenAIBackend:
    name = "openai"

    def extract_json(self, source_file: str, text: str) -> dict:
        import openai  # lazy — only needed for this backend

        client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        prompt = EXTRACTION_PROMPT.replace("{TEXT}", text)
        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        return _extract_json_object(resp.choices[0].message.content)
