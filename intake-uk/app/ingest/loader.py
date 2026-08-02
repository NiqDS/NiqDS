"""File -> pages (text or raster).

Text-layer PDFs are read with ``pdfplumber``. Scans with no usable text layer
are rasterised with ``pypdfium2`` (and images opened with ``Pillow``) so a real
vision backend could read them; here we record a low confidence, because a
document we cannot read is one we must flag (FMT-LEGIB-001), never guess at.

Heavy imports are done lazily so importing this module (and running the rules
tests) needs none of the PDF stack installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

MIN_TEXT_CHARS = 20
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


@dataclass
class LoadedDocument:
    source_file: str
    text: str
    page_count: int
    confidence: float
    is_scan: bool = False
    pages: list[str] = field(default_factory=list)


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

    # No usable text layer -> rasterise (a real vision model would read this).
    _rasterise(path)  # produces images; confidence stays low for the demo
    return LoadedDocument(path.name, text, max(len(pages), 1), 0.20, is_scan=True, pages=pages)


def _rasterise(path: Path) -> list:
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        return [pdf[i].render(scale=2).to_pil() for i in range(len(pdf))]
    except Exception:
        return []


def _load_image(path: Path) -> LoadedDocument:
    # We have no OCR engine in the MVP stack; an image is treated as a scan with
    # low confidence so FMT-LEGIB-001 fires rather than the system guessing.
    try:
        from PIL import Image

        with Image.open(path) as im:
            im.verify()
    except Exception:
        pass
    return LoadedDocument(path.name, "", 1, 0.20, is_scan=True)
