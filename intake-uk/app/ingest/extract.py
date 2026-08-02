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
    doc = adapter.extract(
        source_file=loaded.source_file,
        text=loaded.text,
        page_count=loaded.page_count,
        confidence=loaded.confidence,
        backend=backend,
    )
    # The loader's confidence (e.g. an unreadable scan) is authoritative over any
    # optimism from the extractor.
    if loaded.confidence < doc.confidence:
        doc = doc.model_copy(update={"confidence": loaded.confidence})
    return doc


def extract_path(path: str | Path, backend: str | None = None) -> ExtractedDocument:
    return extract_document(load_file(path), backend=backend)
