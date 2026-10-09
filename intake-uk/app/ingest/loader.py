"""File -> pages (text or raster).

Text-layer PDFs are read with ``pdfplumber``. Scans with no usable text layer
are rasterised with ``pypdfium2`` (and images opened with ``Pillow``) into page
images, so a real **vision** backend can read them. When no vision backend is
configured, a document we cannot read stays low-confidence and is flagged
(FMT-LEGIB-001) — never guessed at.

Heavy imports are done lazily so importing this module (and running the rules
tests) needs none of the PDF/image stack installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

MIN_TEXT_CHARS = 20
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".heic"}
# Cap how many page images we hand a vision model (cost / token control).
MAX_VISION_PAGES = 3
# What a scan is worth before a reader has looked at it: below the FMT-LEGIB
# threshold, so a scan with no vision backend is flagged, not guessed.
SCAN_CONFIDENCE = 0.20

_MEDIA_TYPE = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".tif": "image/png", ".tiff": "image/png", ".bmp": "image/png",
    ".webp": "image/webp", ".heic": "image/png",
}


@dataclass
class LoadedDocument:
    source_file: str
    text: str
    page_count: int
    confidence: float
    is_scan: bool = False
    pages: list[str] = field(default_factory=list)
    # Page images (bytes) for a vision backend, plus their media type. Empty for
    # a clean text-layer document (it needs no image).
    images: list[bytes] = field(default_factory=list)
    image_media_type: str | None = None


def load_file(path: str | Path) -> LoadedDocument:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _load_pdf(path)
    if suffix in IMAGE_SUFFIXES:
        return _load_image(path)
    if suffix in {".txt", ".text"}:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return LoadedDocument(path.name, text, 1, _confidence(text))
    # Unknown container — treat as an unreadable scan.
    return LoadedDocument(path.name, "", 1, 0.15, is_scan=True)


def _confidence(text: str) -> float:
    return 0.95 if len(text.strip()) >= MIN_TEXT_CHARS else 0.20


def _load_pdf(path: Path) -> LoadedDocument:
    import pdfplumber

    pages: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    text = "\n".join(pages).strip()
    if len(text) >= MIN_TEXT_CHARS:
        return LoadedDocument(path.name, text, len(pages), 0.95, pages=pages)

    # No usable text layer -> rasterise so a vision model can read it.
    images = _rasterise(path)
    return LoadedDocument(
        path.name, text, max(len(pages), 1), SCAN_CONFIDENCE, is_scan=True,
        pages=pages, images=images, image_media_type="image/png" if images else None,
    )


def _rasterise(path: Path) -> list[bytes]:
    """Render the first few PDF pages to PNG bytes (empty list on any failure)."""

    try:
        import io

        import pypdfium2 as pdfium

        out: list[bytes] = []
        pdf = pdfium.PdfDocument(str(path))
        for i in range(min(len(pdf), MAX_VISION_PAGES)):
            pil = pdf[i].render(scale=2).to_pil()
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            out.append(buf.getvalue())
        return out
    except Exception:
        return []


def _load_image(path: Path) -> LoadedDocument:
    """A photo/scan: carry the image bytes for a vision backend.

    Confidence stays low here; it is the *reader* (a vision model, downstream)
    that earns a higher confidence by actually transcribing the image. With no
    vision backend, the low confidence makes FMT-LEGIB-001 fire rather than the
    system guessing.
    """

    data = b""
    try:
        from PIL import Image

        with Image.open(path) as im:
            im.verify()
        data = path.read_bytes()
    except Exception:
        data = b""
    media = _MEDIA_TYPE.get(path.suffix.lower(), "image/png")
    return LoadedDocument(
        path.name, "", 1, SCAN_CONFIDENCE, is_scan=True,
        images=[data] if data else [], image_media_type=media if data else None,
    )
