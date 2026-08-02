"""End-to-end rules-engine test over the fixture scenarios.

Asserts that all 12 fixtures produce exactly their labelled flag sets. No model
is involved — the extracted records are hand-written JSON.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.report.chase import build_chase
from app.rules import checks_temporal
from app.rules.engine import run_bundle
from app.scenarios import build_bundle, load_labels, scenario_meta, scenario_names


@pytest.fixture(autouse=True)
def _fixed_today():
    checks_temporal.set_today(date(2026, 8, 2))
    yield
    checks_temporal.set_today(None)


@pytest.mark.parametrize("bundle_id", scenario_names())
def test_scenario_matches_labels(bundle_id):
    bundle = build_bundle(bundle_id)
    meta = scenario_meta(bundle_id)
    flags = run_bundle(bundle)

    # Group the raised rule ids by document (None == bundle-level).
    by_doc: dict[str | None, set[str]] = {}
    for f in flags:
        by_doc.setdefault(f.document, set()).add(f.rule_id)

    # Every document must produce exactly its labelled rule set.
    for stem in meta["documents"]:
        doc = build_bundle(bundle_id)  # cheap; reuse loaded fixture
        source_file = next(
            d.source_file for d in doc.documents
            if d.source_file.startswith(stem.split("_")[0])
        )
        expected = set(load_labels(stem))
        actual = by_doc.get(source_file, set())
        assert actual == expected, f"{stem}: expected {expected}, got {actual}"

    # Bundle-level flags must match the scenario's declared expectations.
    bundle_level = [f for f in flags if f.document is None]
    expected_bundle = meta.get("bundle_flags", [])
    assert len(bundle_level) == len(expected_bundle), (
        f"bundle-level flags: {[f.rule_id for f in bundle_level]}"
    )
    for spec in expected_bundle:
        match = [
            f for f in bundle_level
            if f.rule_id == spec["rule_id"]
            and spec["evidence_contains"] in (f.message + (f.evidence or ""))
        ]
        assert match, f"missing bundle flag {spec}"


def test_april_gap_chase_names_month_and_account():
    """Acceptance: the April-statement-gap fixture produces a chase naming
    'April 2026' and the account."""

    bundle = build_bundle("BUNDLE-B-STATEMENTS")
    flags = run_bundle(bundle)
    chase = build_chase(bundle, flags)
    assert "April 2026" in chase.text
    assert "5555" in chase.text or "4471" in chase.text


def test_no_false_block_on_clean_documents():
    """Zero false positives on BLOCK-severity rules for the clean fixture."""

    bundle = build_bundle("BUNDLE-A-INVOICES")
    flags = run_bundle(bundle)
    clean_blocks = [
        f for f in flags
        if f.document == "01_clean_invoice.pdf" and f.severity == "BLOCK"
    ]
    assert clean_blocks == []
