"""Vision-extraction tests (offline).

The real anthropic/openai vision calls need a key and network, so here we inject
a fake vision-capable backend and prove the *plumbing* and the *decision logic*:

  * image files and text-less scans carry page image bytes;
  * with no vision backend, a scan stays low-confidence and FMT-LEGIB-001 fires
    (the system flags, it does not guess);
  * with a vision backend, the document is read from the image and the model's
    confidence stands;
  * a vision read that reports low confidence (blurry photo) still flags.
"""

from __future__ import annotations

import io

import pytest

from app.ingest.extract import extract_document
from app.ingest.loader import load_file
from app.llm import adapter
from app.rules.engine import run_document


def _png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (12, 12), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def image_file(tmp_path):
    p = tmp_path / "receipt_photo.png"
    p.write_bytes(_png_bytes())
    return p


class _FakeVision:
    """A vision backend that records the images it was handed."""

    name = "fake"
    supports_vision = True

    def __init__(self, result: dict):
        self.result = result
        self.seen_images = None
        self.seen_media = None

    def extract_json(self, source_file, text, images=None, media_type=None):
        self.seen_images = images
        self.seen_media = media_type
        return dict(self.result, source_file=source_file)


def _install(monkeypatch, backend):
    monkeypatch.setattr(adapter, "_VISION_BACKENDS", {"anthropic", "openai", "fake"})
    monkeypatch.setattr(adapter, "get_backend", lambda name=None: backend)


# --- loader ---------------------------------------------------------------- #

def test_image_file_carries_bytes(image_file):
    loaded = load_file(image_file)
    assert loaded.is_scan is True
    assert loaded.images and loaded.images[0][:4] == b"\x89PNG"
    assert loaded.image_media_type == "image/png"
    assert loaded.confidence < 0.4  # unread -> below the legibility threshold


def test_text_pdf_has_no_images():
    from pathlib import Path

    pdf = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "01_clean_invoice.pdf"
    loaded = load_file(pdf)
    assert loaded.images == []
    assert loaded.confidence >= 0.9


# --- no vision backend: flag, don't guess ---------------------------------- #

def test_scan_without_vision_is_flagged(image_file):
    # Default mock backend cannot read images.
    loaded = load_file(image_file)
    doc = extract_document(loaded, backend="mock")
    assert doc.confidence < 0.4
    assert any(f.rule_id == "FMT-LEGIB-001" for f in run_document(doc))


# --- vision backend: read the image ---------------------------------------- #

def test_vision_reads_image(monkeypatch, image_file):
    fake = _FakeVision({
        "doc_type": "PURCHASE_INVOICE",
        "supplier_name": "RealHandy",
        "supplier_vat_number": "GB999 9999 73",
        "document_number": "100-13",
        "document_date": "2021-08-24",
        "net_total": {"amount": "620", "currency": "GBP"},
        "vat_total": {"amount": "124", "currency": "GBP"},
        "gross_total": {"amount": "744", "currency": "GBP"},
        "confidence": 0.93,
        "raw_text_excerpt": "RealHandy VAT GB999999973 Total 744.00",
    })
    _install(monkeypatch, fake)

    loaded = load_file(image_file)
    doc = extract_document(loaded, backend="fake")

    # the image actually reached the backend
    assert fake.seen_images and fake.seen_media == "image/png"
    # the model's confidence stands (not clamped to the loader's 0.20)
    assert doc.confidence == pytest.approx(0.93)
    assert doc.supplier_name == "RealHandy"
    # a legible, well-formed invoice -> no legibility flag
    assert not any(f.rule_id == "FMT-LEGIB-001" for f in run_document(doc))


def test_vision_low_confidence_still_flags(monkeypatch, image_file):
    # A blurry photo: the model reports it could not read it clearly.
    fake = _FakeVision({"doc_type": "UNKNOWN", "confidence": 0.2,
                        "raw_text_excerpt": "blurry"})
    _install(monkeypatch, fake)

    doc = extract_document(load_file(image_file), backend="fake")
    assert doc.confidence == pytest.approx(0.2)
    assert any(f.rule_id == "FMT-LEGIB-001" for f in run_document(doc))
