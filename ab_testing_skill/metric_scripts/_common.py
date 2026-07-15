"""Shared demo data loader for the bundled metric scripts.

Not part of the pluggable contract -- real bank scripts will have their
own data access (Hive/Spark tables) and don't need this module.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

REFERENCE_PATH = Path(__file__).resolve().parent.parent / "sample_data" / "attributes_reference.csv"


@lru_cache(maxsize=1)
def _load_reference() -> dict[str, dict[str, str]]:
    with open(REFERENCE_PATH, newline="", encoding="utf-8") as f:
        return {row["inn"]: row for row in csv.DictReader(f)}


def lookup_column(inn_list: list[str], column: str, cast: Callable[[str], Any] = str) -> dict[str, Any]:
    reference = _load_reference()
    result: dict[str, Any] = {}
    for inn in inn_list:
        row = reference.get(inn)
        raw = row.get(column) if row else None
        if raw in (None, ""):
            result[inn] = None
            continue
        try:
            result[inn] = cast(raw)
        except (TypeError, ValueError):
            result[inn] = None
    return result
