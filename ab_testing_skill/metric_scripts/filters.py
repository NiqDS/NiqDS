"""Loader/validator for metric_scripts/filters.json.

Same shape as subscriptions.py: the JSON file is the single place a new
filter gets defined, and everything downstream (the web form, the CLI,
the metric scripts) reads it from here rather than hardcoding a list.

A filter is only *declared* here -- how it actually narrows a query lives
in the metric script that receives it, because only the script knows
which column of which table the filter maps to. The pipeline just passes
the selected `{code: value}` dict straight through.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

FILTERS_PATH = Path(__file__).resolve().parent / "filters.json"

ALL_METRICS = "*"


@dataclass
class FilterDefinition:
    code: str
    label: str
    description: str
    type: str  # "categorical" | "numeric" | "date"
    applies_to: list[str]
    values: list[str] | None = None

    def applies_to_metric(self, metric_code: str) -> bool:
        return ALL_METRICS in self.applies_to or metric_code in self.applies_to


@lru_cache(maxsize=1)
def _load() -> dict[str, FilterDefinition]:
    with open(FILTERS_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    return {
        code: FilterDefinition(
            code=code,
            label=entry["label"],
            description=entry.get("description", ""),
            type=entry.get("type", "categorical"),
            applies_to=list(entry.get("applies_to") or [ALL_METRICS]),
            values=entry.get("values"),
        )
        for code, entry in raw.items()
        if not code.startswith("_")
    }


def list_filters() -> dict[str, FilterDefinition]:
    return dict(_load())


def get_filter(code: str) -> FilterDefinition:
    filters = _load()
    if code not in filters:
        known = ", ".join(sorted(filters)) or "(none registered)"
        raise KeyError(f"no filter named '{code}' in {FILTERS_PATH}. Known filters: {known}")
    return filters[code]


def filters_for_metric(metric_code: str) -> dict[str, FilterDefinition]:
    return {code: f for code, f in _load().items() if f.applies_to_metric(metric_code)}


def validate_selection(selected: dict[str, Any], metric_codes: list[str]) -> None:
    """Rejects unknown filter codes, out-of-range categorical values, and

    filters that don't apply to any of the requested metrics -- up front,
    before a Spark job is launched, so a typo fails in milliseconds
    instead of after a cluster round trip.
    """
    for code, value in selected.items():
        definition = get_filter(code)  # raises KeyError naming the known filters

        if not any(definition.applies_to_metric(m) for m in metric_codes):
            raise ValueError(
                f"filter '{code}' does not apply to any of the requested metrics "
                f"({', '.join(metric_codes)}); it applies to: {', '.join(definition.applies_to)}"
            )

        if definition.type == "categorical" and definition.values:
            chosen = value if isinstance(value, list) else [value]
            unknown = [v for v in chosen if v not in definition.values]
            if unknown:
                raise ValueError(
                    f"filter '{code}' got value(s) {unknown} outside its allowed set "
                    f"{definition.values}"
                )

        if definition.type == "numeric" and not isinstance(value, (int, float)):
            raise ValueError(f"filter '{code}' expects a number, got {value!r}")
