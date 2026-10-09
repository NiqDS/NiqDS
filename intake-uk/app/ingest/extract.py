"""page(s) -> typed record via the LLM adapter.

This is the only place a model touches the pipeline. Its output is typed JSON;
nothing here makes a pass/fail decision.
"""

from __future__ import annotations

from pathlib import Path

from app.ingest.loader import LoadedDocument, load_file
from app.llm import adapter
from app.models import ExtractedDocument


def extract_document(loaded: LoadedDocument, backend: str | None = None) -> ExtractedDocument:
    # If the document is a scan/photo and the active backend can read images,
    # extract from the page image(s) (vision). Otherwise read the text layer.
    use_vision = bool(loaded.images) and adapter.supports_vision(backend)
    # For a vision read we trust the model's self-reported confidence (it asks
    # the model to flag an unclear photo); default optimistic only as a fallback.
    base_confidence = 0.85 if use_vision else loaded.confidence

    doc = adapter.extract(
        source_file=loaded.source_file,
        text=loaded.text,
        page_count=loaded.page_count,
        confidence=base_confidence,
        backend=backend,
        images=loaded.images if use_vision else None,
        image_media_type=loaded.image_media_type,
    )

    # When we could NOT read the image (no vision backend), the loader's low
    # scan confidence is authoritative, so FMT-LEGIB-001 fires rather than the
    # system trusting a blind guess. When vision WAS used, the model's reported
    # confidence stands.
    if not use_vision and loaded.confidence < doc.confidence:
        doc = doc.model_copy(update={"confidence": loaded.confidence})
    return doc


def extract_path(path: str | Path, backend: str | None = None) -> ExtractedDocument:
    return extract_document(load_file(path), backend=backend)
