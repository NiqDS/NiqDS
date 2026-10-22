"""Financial metric: СДО -- spec step 3/5.

Usable both as a balance-check attribute and as a financial-effect
"статья" during pilot monitoring.

PRODUCTION: swap for the real PySpark job; keep the signature, and
apply `filters` inside the query (see metric_scripts/filters.json).
"""
from __future__ import annotations

from datetime import date
from typing import Any

from metric_scripts._common import lookup_column


#: This script is the bundled demo stub: it reads
#: sample_data/attributes_reference.csv and ignores `spark`. The runner
#: refuses to call it once AB_SKILL_USE_SPARK is on -- see
#: skill/metrics/runner.py:DemoDataInProductionError. Delete this line when
#: the script actually queries the mart.
DEMO_ONLY = True

def run(
    inn_list: list[str],
    as_of_date: date,
    spark: Any = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return lookup_column(inn_list, column="sdo", cast=float, filters=filters)
