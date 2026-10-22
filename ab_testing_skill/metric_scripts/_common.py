"""Shared demo data loader for the bundled metric scripts.

Not part of the pluggable contract -- real bank scripts have their own
data access (Hive/Spark tables) and don't need this module. It exists so
the bundled bank is a working reference implementation of the script
contract, filters included, without needing a cluster.
"""
from __future__ import annotations

import csv
import os
import zlib
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


class DemoDataRequestedInProductionError(RuntimeError):
    """The bundled demo table was read while the skill is in production mode.

    Second net behind skill/metrics/runner.py's DEMO_ONLY check, for a
    script that reads this table without carrying the marker (a new stub,
    or a half-ported script that still falls back here on some path). The
    runner checks by module marker; this fires wherever the demo table is
    actually touched, so neither can be bypassed by accident.
    """


def refuse_demo_reference_in_production() -> None:
    if os.environ.get("AB_SKILL_USE_SPARK", "false").strip().lower() != "true":
        return
    if os.environ.get("AB_SKILL_ALLOW_DEMO_DATA", "false").strip().lower() == "true":
        return
    raise DemoDataRequestedInProductionError(
        f"a metric script read the bundled demo table {REFERENCE_PATH.name} while "
        "AB_SKILL_USE_SPARK=true. These numbers are fabricated: they would end up in "
        "the pilot's strata and balance report, and the result would look valid. Port "
        "the script to the real mart, or set AB_SKILL_ALLOW_DEMO_DATA=true for a "
        "deliberate dry run."
    )


def monthly_series(
    inn_list: list[str],
    column: str,
    months: list[str],
    filters: dict[str, Any] | None = None,
    cast: Callable[[str], Any] = float,
) -> dict[str, Any]:
    """Demo money metric as a monthly series: `{инн: {месяц: значение}}`.

    The bundled reference table holds one number per client, but everything
    the skill judges groups on -- trend, cohort, balance over a window --
    needs a history. So the single number is expanded into a plausible one,
    deterministically from the client's own ИНН: the same client always gets
    the same shape, which is what makes the tests and the demo reproducible.

    Three properties matter and are deliberate:

    * **The mean over the window equals the reference value exactly.** The
      scalar view of a series is its mean, so every caller that asked for
      one number before this existed still gets the same number.
    * **Shapes vary**: growing, declining, irregular (whole months at zero)
      and flat clients all occur, so the cohort rules in `skill/features.py`
      have something real to separate.
    * **Absent stays absent.** A client the reference table does not know
      returns None, not a series of zeros -- see `MetricSeries`.
    """
    base = lookup_column(inn_list, column=column, cast=cast, filters=filters)
    out: dict[str, Any] = {}
    for inn, value in base.items():
        if value is None:
            out[inn] = None
            continue
        out[inn] = _expand_to_months(str(inn), column, float(value), months)
    return out


def _expand_to_months(inn: str, column: str, base: float, months: list[str]) -> dict[str, float]:
    if not months:
        return {}
    seed = zlib.crc32(f"{inn}:{column}".encode("utf-8"))
    profile = seed % 100
    n = len(months)

    if profile < 15:        # growing
        shape = [(1.0 + 0.09 * i) for i in range(n)]
    elif profile < 30:      # declining
        shape = [(1.0 - 0.07 * i) for i in range(n)]
    elif profile < 42:      # irregular: whole months with nothing
        shape = [0.0 if (seed >> i) & 1 else 1.0 for i in range(n)]
        if not any(shape):  # never leave it entirely empty
            shape[-1] = 1.0
    else:                   # flat, with month-to-month noise
        shape = [1.0 + 0.12 * (((seed >> (i * 3)) % 7) - 3) / 3 for i in range(n)]

    # deterministic jitter, then rescale so the window mean is exactly `base`
    shape = [max(s, 0.0) * (1.0 + 0.05 * (((seed >> (i * 5)) % 5) - 2) / 2) for i, s in enumerate(shape)]
    total = sum(shape)
    if total == 0:
        return {month: 0.0 for month in months}
    factor = base * n / total
    return {month: round(shape[i] * factor, 2) for i, month in enumerate(months)}


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
    refuse_demo_reference_in_production()
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
