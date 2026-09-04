"""Grouping attribute: legal form (ОПФ) -- spec step 3.

PRODUCTION: swap for the real PySpark job; keep the signature, and
apply `filters` inside the query (see metric_scripts/filters.json).
"""
from __future__ import annotations

from datetime import date
from typing import Any

from metric_scripts._common import lookup_column


def run(
    inn_list: list[str],
    as_of_date: date,
    spark: Any = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return lookup_column(inn_list, column="opf", cast=str, filters=filters)
