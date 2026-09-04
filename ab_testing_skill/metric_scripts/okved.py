"""Grouping attribute: industry (OKVED code) -- spec step 3, "Отрасль по ОКВЭД".

PRODUCTION: replace this body with the real PySpark job that resolves
OKVED for a batch of INNs, keeping the
`run(inn_list, as_of_date, spark, filters)` signature so
skill/metrics/runner.py needs no changes.
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
    return lookup_column(inn_list, column="okved", cast=str, filters=filters)
