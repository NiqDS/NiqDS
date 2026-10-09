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

# The vision contract: the same JSON, read from the page image(s) instead of a
# text layer. The model MUST report how clearly it could read the document, so
# the deterministic FMT-LEGIB rule can flag a blurry photo instead of trusting a
# guess. The model still only transcribes — it never validates or corrects.
VISION_PROMPT = """You are a document extraction engine for a UK bookkeeping intake system.
You are given photo(s)/scan(s) of ONE document. Return ONLY a single JSON object.
Transcribe exactly what you can see — do not validate, correct, or judge. If a
field is not visible, use null.

Add two extra fields:
- "confidence": a number 0.0-1.0 for how clearly you could read the document.
  If it is blurry, cropped, dark, or you are guessing, set it below 0.4 and leave
  the fields you cannot read as null. Do NOT guess at an unclear document.
- "raw_text_excerpt": a short string of the key text you actually read (for audit).

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
  "account_identifier": string|null,
  "confidence": number,
  "raw_text_excerpt": string
}

Read dates UK-style (DD/MM/YYYY). Transcribe amounts as strings, never rounding.
Return only the JSON object."""

# Backends that can read a page image. A scan sent to a non-vision backend stays
# low-confidence and is flagged, never guessed at.
_VISION_BACKENDS = {"anthropic", "openai"}


def supports_vision(name: str | None = None) -> bool:
    name = (name or os.environ.get("LLM_BACKEND", "mock")).lower()
    return name in _VISION_BACKENDS


class ExtractionBackend(Protocol):
    name: str
    supports_vision: bool

    def extract_json(
        self, source_file: str, text: str,
        images: list[bytes] | None = None, media_type: str | None = None,
    ) -> dict:  # pragma: no cover
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
    if data.get("confidence") is not None:
        try:
            data["confidence"] = float(data["confidence"])
        except (TypeError, ValueError):
            data["confidence"] = confidence
    else:
        data["confidence"] = confidence
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
    images: list[bytes] | None = None,
    image_media_type: str | None = None,
) -> ExtractedDocument:
    """Extract a typed document using the configured backend.

    If ``images`` are supplied and the backend can read them, the document is
    read from the image(s) (vision); otherwise it is read from ``text``.
    """

    be = get_backend(backend)
    use_vision = bool(images) and getattr(be, "supports_vision", False)
    if use_vision:
        raw = be.extract_json(source_file, text, images=images, media_type=image_media_type)
    else:
        raw = be.extract_json(source_file, text)
    doc = _coerce(raw, source_file, page_count, confidence)
    if not doc.raw_text_excerpt:
        doc = doc.model_copy(update={"raw_text_excerpt": text[:800] or "(read from image)"})
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
    supports_vision = True

    def extract_json(
        self, source_file: str, text: str,
        images: list[bytes] | None = None, media_type: str | None = None,
    ) -> dict:
        import base64

        import anthropic  # lazy — only needed for this backend

        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
        if images:
            content: list[dict] = [
                {"type": "image", "source": {
                    "type": "base64", "media_type": media_type or "image/png",
                    "data": base64.b64encode(img).decode("ascii")}}
                for img in images
            ]
            content.append({"type": "text", "text": VISION_PROMPT})
        else:
            content = [{"type": "text", "text": EXTRACTION_PROMPT.replace("{TEXT}", text)}]
        resp = client.messages.create(
            model=model, max_tokens=2000, temperature=0,
            messages=[{"role": "user", "content": content}],
        )
        return _extract_json_object(resp.content[0].text)


class _OpenAIBackend:
    name = "openai"
    supports_vision = True

    def extract_json(
        self, source_file: str, text: str,
        images: list[bytes] | None = None, media_type: str | None = None,
    ) -> dict:
        import base64

        import openai  # lazy — only needed for this backend

        client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        if images:
            content: list[dict] = [{"type": "text", "text": VISION_PROMPT}]
            for img in images:
                b64 = base64.b64encode(img).decode("ascii")
                content.append({"type": "image_url", "image_url": {
                    "url": f"data:{media_type or 'image/png'};base64,{b64}"}})
            messages = [{"role": "user", "content": content}]
        else:
            messages = [{"role": "user", "content": EXTRACTION_PROMPT.replace("{TEXT}", text)}]
        resp = client.chat.completions.create(model=model, temperature=0, messages=messages)
        return _extract_json_object(resp.choices[0].message.content)
