"""Load the hand-written JSON fixtures and scenario definitions into typed
:class:`Bundle` objects.

Used by the tests, the eval harness and the demo seed. Touches no model.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.models import Bundle, ExtractedDocument

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
EXTRACTED_DIR = FIXTURES_DIR / "extracted"
LABELS_DIR = FIXTURES_DIR / "labels"
SCENARIOS_FILE = FIXTURES_DIR / "scenarios.json"


def load_extracted(name: str) -> ExtractedDocument:
    """Load one extracted-document fixture by stem name."""

    path = EXTRACTED_DIR / f"{name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return ExtractedDocument.model_validate(data)


def load_labels(name: str) -> list[str]:
    """Load the expected rule ids for one fixture."""

    path = LABELS_DIR / f"{name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("expected", []))


@lru_cache(maxsize=1)
def _scenarios_raw() -> list[dict]:
    data = json.loads(SCENARIOS_FILE.read_text(encoding="utf-8"))
    return data["scenarios"]


def scenario_names() -> list[str]:
    return [s["bundle_id"] for s in _scenarios_raw()]


def build_bundle(bundle_id: str) -> Bundle:
    """Build a :class:`Bundle` for a named scenario."""

    for s in _scenarios_raw():
        if s["bundle_id"] == bundle_id:
            docs = [load_extracted(n) for n in s["documents"]]
            return Bundle(
                bundle_id=s["bundle_id"],
                client_name=s["client_name"],
                declared_period_start=s["declared_period_start"],
                declared_period_end=s["declared_period_end"],
                expected_accounts=s.get("expected_accounts", []),
                documents=docs,
            )
    raise KeyError(bundle_id)


def scenario_meta(bundle_id: str) -> dict:
    for s in _scenarios_raw():
        if s["bundle_id"] == bundle_id:
            return s
    raise KeyError(bundle_id)


def all_bundles() -> list[Bundle]:
    return [build_bundle(name) for name in scenario_names()]
