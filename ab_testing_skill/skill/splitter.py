"""Step 4 of the spec: split the checked INN list into Control (КГ) and

Target (ЦГ) groups.

Per the clarified requirements: stratify on the chosen grouping metrics
(OKVED / OPF / TB / tenure bucket, or whichever subset the user picked in
step 3), split roughly 50/50 *within each stratum* so both groups have the
same composition, then check that the two groups' means on the financial
metrics don't diverge by more than `SplitConfig.max_relative_imbalance`.
If they do, reshuffle within strata (new random assignment, same strata)
and retry up to `max_reshuffle_attempts` times.
"""
from __future__ import annotations

import random
import statistics
from typing import Any

from .config import SplitConfig
from .models import SplitResult

TENURE_BUCKETS: list[tuple[float, float]] = [
    (0, 1),
    (1, 3),
    (3, 5),
    (5, 10),
    (10, float("inf")),
]


def bucket_tenure(years: float | None) -> str:
    if years is None:
        return "unknown"
    for lo, hi in TENURE_BUCKETS:
        if lo <= years < hi:
            return f"{lo}-{hi}" if hi != float("inf") else f"{lo}+"
    return "unknown"


def _stratum_key(inn: str, grouping_values: dict[str, dict[str, Any]]) -> tuple[str, ...]:
    parts = []
    for metric, values in grouping_values.items():
        raw = values.get(inn)
        value = bucket_tenure(raw) if metric == "tenure" else raw
        parts.append(f"{metric}={value}")
    return tuple(parts)


def _build_strata(inn_list: list[str], grouping_values: dict[str, dict[str, Any]]) -> dict[tuple, list[str]]:
    strata: dict[tuple, list[str]] = {}
    for inn in inn_list:
        key = _stratum_key(inn, grouping_values)
        strata.setdefault(key, []).append(inn)
    return strata


def _assign(strata: dict[tuple, list[str]], target_ratio: float, seed: int) -> tuple[list[str], list[str]]:
    rng = random.Random(seed)
    control: list[str] = []
    target: list[str] = []
    for members in strata.values():
        shuffled = members[:]
        rng.shuffle(shuffled)
        n_target = round(len(shuffled) * target_ratio)
        target.extend(shuffled[:n_target])
        control.extend(shuffled[n_target:])
    return control, target


def _balance_report(
    control: list[str],
    target: list[str],
    financial_values: dict[str, dict[str, Any]],
    max_relative_imbalance: float,
) -> dict[str, dict[str, float]]:
    report: dict[str, dict[str, float]] = {}
    for metric, values in financial_values.items():
        c_vals = [values[i] for i in control if values.get(i) is not None]
        t_vals = [values[i] for i in target if values.get(i) is not None]
        if not c_vals or not t_vals:
            continue
        c_mean = statistics.mean(c_vals)
        t_mean = statistics.mean(t_vals)
        relative_diff = abs(c_mean - t_mean) / c_mean if c_mean else (0.0 if t_mean == 0 else 1.0)
        report[metric] = {
            "control_mean": c_mean,
            "target_mean": t_mean,
            "relative_diff": relative_diff,
            "balanced": 1.0 if relative_diff <= max_relative_imbalance else 0.0,
        }
    return report


def split(
    inn_list: list[str],
    grouping_values: dict[str, dict[str, Any]],
    financial_values: dict[str, dict[str, Any]],
    config: SplitConfig,
) -> SplitResult:
    strata = _build_strata(inn_list, grouping_values)
    base_seed = config.random_seed if config.random_seed is not None else random.randint(0, 2**31)

    control: list[str] = []
    target: list[str] = []
    balance_report: dict[str, dict[str, float]] = {}
    balanced = not financial_values  # nothing to balance against => trivially balanced
    attempt = 0

    while attempt < max(1, config.max_reshuffle_attempts):
        control, target = _assign(strata, config.target_ratio, seed=base_seed + attempt)
        attempt += 1
        if not financial_values:
            break
        balance_report = _balance_report(control, target, financial_values, config.max_relative_imbalance)
        balanced = bool(balance_report) and all(r["balanced"] == 1.0 for r in balance_report.values())
        if balanced:
            break

    strata_summary = {
        " & ".join(key) if key else "(no grouping metrics)": {"total": len(members)}
        for key, members in strata.items()
    }

    return SplitResult(
        control=control,
        target=target,
        strata_summary=strata_summary,
        balance_report=balance_report,
        attempts_used=attempt,
        balanced=balanced,
    )
