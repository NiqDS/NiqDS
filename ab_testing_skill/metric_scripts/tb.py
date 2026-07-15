"""Grouping attribute: territorial bank (ТБ) -- spec step 3.

PRODUCTION: swap for the real PySpark job; keep the signature.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from metric_scripts._common import lookup_column


def run(inn_list: list[str], as_of_date: date, spark: Any = None) -> dict[str, Any]:
    return lookup_column(inn_list, column="tb", cast=str)
