"""Rule registry + runner.

The hard architectural constraint of this product lives here: **the model
extracts, deterministic code validates.** Every function in this package is
ordinary Python that takes a document or a bundle and returns a list of typed
:class:`~app.models.Flag` objects. No validation decision depends on model
inference, and the whole engine runs with no model, no API key and no network
against hand-written JSON fixtures.

Severity and the client-facing message template for every rule live in
``registry.yaml`` — a single source of truth — and are stamped onto each flag
by :func:`make_flag`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from app.models import Bundle, ExtractedDocument, Flag

_REGISTRY_PATH = Path(__file__).with_name("registry.yaml")


@dataclass(frozen=True)
class RuleMeta:
    id: str
    name: str
    severity: str  # BLOCK | WARN | INFO
    scope: str  # document | bundle
    message: str


def _load_registry() -> dict[str, RuleMeta]:
    raw = yaml.safe_load(_REGISTRY_PATH.read_text(encoding="utf-8")) or []
    registry: dict[str, RuleMeta] = {}
    for entry in raw:
        registry[entry["id"]] = RuleMeta(
            id=entry["id"],
            name=entry["name"],
            severity=entry["severity"],
            scope=entry["scope"],
            message=entry["message"],
        )
    return registry


REGISTRY: dict[str, RuleMeta] = _load_registry()


def make_flag(
    rule_id: str,
    *,
    field: str | None = None,
    document: str | None = None,
    evidence: object | None = None,
    **fmt: object,
) -> Flag:
    """Build a :class:`Flag` from registry metadata.

    ``severity`` and the message template come from ``registry.yaml`` so that a
    rule function never hard-codes either. ``evidence`` and any extra keyword
    arguments are formatted into the message template.
    """

    meta = REGISTRY[rule_id]
    # ``supplier_name`` and ``period`` are commonly interpolated; default them
    # so a template never explodes on a missing key.
    fmt.setdefault("supplier_name", "the supplier")
    fmt.setdefault("period", "this period")
    fmt.setdefault("account", "")
    try:
        message = meta.message.format(evidence=evidence, **fmt)
    except (KeyError, IndexError):  # pragma: no cover - defensive
        message = meta.message
    return Flag(
        rule_id=rule_id,
        severity=meta.severity,  # type: ignore[arg-type]
        field=field,
        document=document,
        message=message,
        evidence=None if evidence is None else str(evidence),
    )


# --- rule registration ------------------------------------------------------

DocumentRule = Callable[[ExtractedDocument], list[Flag]]
BundleRule = Callable[[Bundle], list[Flag]]

DOCUMENT_RULES: list[DocumentRule] = []
BUNDLE_RULES: list[BundleRule] = []


def document_rule(fn: DocumentRule) -> DocumentRule:
    DOCUMENT_RULES.append(fn)
    return fn


def bundle_rule(fn: BundleRule) -> BundleRule:
    BUNDLE_RULES.append(fn)
    return fn


_LOADED = False


def _load_rules() -> None:
    """Import the check modules so their decorators register the rules.

    Imported lazily to avoid a circular import at module load time (the check
    modules import :func:`make_flag`, :func:`document_rule` and
    :func:`bundle_rule` from here).
    """

    global _LOADED
    if _LOADED:
        return
    from app.rules import (  # noqa: F401  (import for side effects)
        checks_arithmetic,
        checks_format,
        checks_set,
        checks_temporal,
    )

    _LOADED = True


def run_document(doc: ExtractedDocument) -> list[Flag]:
    """Run every document-scoped rule against a single document."""

    _load_rules()
    flags: list[Flag] = []
    for rule in DOCUMENT_RULES:
        flags.extend(rule(doc))
    return flags


def run_bundle(bundle: Bundle) -> list[Flag]:
    """Run all document-scoped and bundle-scoped rules against a bundle.

    Returns the complete, deterministic flag set for the bundle.
    """

    _load_rules()
    flags: list[Flag] = []
    for doc in bundle.documents:
        flags.extend(run_document(doc))
    for rule in BUNDLE_RULES:
        flags.extend(rule(bundle))
    return flags


_SEVERITY_ORDER = {"BLOCK": 0, "WARN": 1, "INFO": 2}


def sort_flags(flags: list[Flag]) -> list[Flag]:
    """Stable sort by severity (BLOCK first), then rule id."""

    return sorted(
        flags, key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), f.rule_id)
    )
