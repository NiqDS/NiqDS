"""Shared demo data loader for the bundled metric scripts.

Not part of the pluggable contract -- real bank scripts have their own
data access (Hive/Spark tables) and don't need this module. It exists so
the bundled bank is a working reference implementation of the script
contract, filters included, without needing a cluster.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

REFERENCE_PATH = Path(__file__).resolve().parent.parent / "sample_data" / "attributes_reference.csv"

# How a filter code from filters.json maps onto a column of the demo
# reference CSV. A production script does the equivalent by adding a
# .where(...) clause on the real table instead.
FILTER_COLUMNS: dict[str, str] = {
    "segment": "segment",
    "sub_segment": "segmca",
    "period_type": "period_type",
    "reporting_year": "report_year",
    "active_only": "is_active",
}


@lru_cache(maxsize=1)
def _load_reference() -> dict[str, dict[str, str]]:
    with open(REFERENCE_PATH, newline="", encoding="utf-8") as f:
        return {row["inn"]: row for row in csv.DictReader(f)}


def _row_matches(row: dict[str, str], filters: dict[str, Any]) -> bool:
    for code, wanted in filters.items():
        column = FILTER_COLUMNS.get(code)
        if column is None:
            # An unmapped filter must not be silently ignored: returning
            # unfiltered numbers that look valid is worse than failing.
            raise ValueError(
                f"demo metric scripts cannot apply filter '{code}' "
                f"(no column mapping in {Path(__file__).name}:FILTER_COLUMNS)"
            )
        actual = row.get(column)
        if code == "active_only":
            if str(wanted).lower() in ("yes", "true", "1") and str(actual) != "1":
                return False
            continue
        wanted_values = {str(v) for v in (wanted if isinstance(wanted, list) else [wanted])}
        if str(actual) not in wanted_values:
            return False
    return True


def lookup_column(
    inn_list: list[str],
    column: str,
    cast: Callable[[str], Any] = str,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Returns {inn: value} for the demo reference data.

    IDs that are absent, or whose row is excluded by `filters`, come back
    as None -- mirroring what a real query does when a client has no
    matching row.
    """
    reference = _load_reference()
    result: dict[str, Any] = {}
    for inn in inn_list:
        row = reference.get(inn)
        if row is None or (filters and not _row_matches(row, filters)):
            result[inn] = None
            continue
        raw = row.get(column)
        if raw in (None, ""):
            result[inn] = None
            continue
        try:
            result[inn] = cast(raw)
        except (TypeError, ValueError):
            result[inn] = None
    return result
