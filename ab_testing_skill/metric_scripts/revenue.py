"""Financial metric: выручка (revenue) -- spec step 3/5.

Usable both as a balance-check attribute and as a financial-effect
"статья" during pilot monitoring.

PRODUCTION: swap for the real PySpark job; keep the signature.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from metric_scripts._common import lookup_column


def run(inn_list: list[str], as_of_date: date, spark: Any = None) -> dict[str, Any]:
    return lookup_column(inn_list, column="revenue", cast=float)
