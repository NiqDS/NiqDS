"""Step 4 of the spec: split the checked INN list into Control (КГ) and

Target (ЦГ) groups.

Per the clarified requirements: stratify on the chosen grouping metrics
(OKVED / OPF / TB / tenure bucket, or whichever subset the user picked in
step 3), split roughly 50/50 *within each stratum* so both groups have the
same composition, then check that the two groups are balanced on the
financial metrics via the standardized mean difference (SMD), which must
stay within `SplitConfig.max_standardized_diff`. If it doesn't, reshuffle
within strata (new random assignment, same strata) and retry up to
`max_reshuffle_attempts` times, keeping the least-imbalanced attempt.
"""
from __future__ import annotations

import math
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
    """Allocates each stratum between CG and TG, carrying the remainder.

    The obvious implementation -- `n_target = round(len(members) *
    target_ratio)` per stratum -- is badly wrong on small strata, and small
    strata are the normal case here: stratifying on four categorical
    attributes (ОКВЭД × ОПФ × ТБ × tenure) over a few hundred clients
    leaves most strata with one member.

    For a stratum of one, `round(1 * 0.5)` is 0 -- Python rounds halves to
    even -- so **every single-member stratum sent its client to control,
    every time**. On the bundled 50-client sample with the spec's own four
    attributes that produced a 47/3 split. Worse, it was invisible:
    reshuffling cannot change the outcome for a one-element list, so all 25
    reshuffle attempts returned the identical degenerate split, and with a
    single financial article the SMD check still reported PASSED.

    Two changes fix it. The remainder of each stratum's exact share is
    carried into the next stratum (largest-remainder allocation), so a run
    of singletons alternates TG/CG instead of all landing in CG and the
    overall ratio converges on `target_ratio`. And the strata themselves
    are visited in a shuffled order, so which stratum absorbs a remainder
    varies with the seed -- which is what gives the reshuffle loop
    something to explore on singleton-heavy lists.
    """
    rng = random.Random(seed)
    control: list[str] = []
    target: list[str] = []
    keys = list(strata)
    rng.shuffle(keys)
    carry = 0.0
    for key in keys:
        members = strata[key]
        shuffled = members[:]
        rng.shuffle(shuffled)
        exact = len(shuffled) * target_ratio + carry
        # 1e-9 absorbs float drift so an exact .0 does not floor downwards
        n_target = min(max(int(math.floor(exact + 1e-9)), 0), len(shuffled))
        carry = exact - n_target
        target.extend(shuffled[:n_target])
        control.extend(shuffled[n_target:])
    return control, target


def _balance_report(
    control: list[str],
    target: list[str],
    financial_values: dict[str, dict[str, Any]],
    max_standardized_diff: float,
) -> dict[str, dict[str, float]]:
    """Standardized mean difference (SMD) per financial metric.

        SMD = |mean_T - mean_C| / sqrt((var_T + var_C) / 2)

    Deliberately NOT a relative difference of means. The earlier
    `abs(c_mean - t_mean) / c_mean` had `abs()` only in the numerator, so a
    negative control mean -- routine for ЧОД/ЧЭП on loss-making clients --
    made the ratio negative and the `<= threshold` comparison true for any
    divergence at all. A pooled standard deviation is non-negative by
    construction, so the sign of the metric can no longer flip the verdict.

    SMD also makes metrics of wildly different scale comparable (turnover
    in billions vs СДО in units), and |SMD| < 0.1 is the conventional
    balance threshold, so the cutoff doesn't need justifying case by case.
    """
    report: dict[str, dict[str, float]] = {}
    for metric, values in financial_values.items():
        c_vals = [values[i] for i in control if values.get(i) is not None]
        t_vals = [values[i] for i in target if values.get(i) is not None]
        if not c_vals or not t_vals:
            continue
        c_mean = statistics.mean(c_vals)
        t_mean = statistics.mean(t_vals)
        c_var = statistics.variance(c_vals) if len(c_vals) > 1 else 0.0
        t_var = statistics.variance(t_vals) if len(t_vals) > 1 else 0.0
        pooled_sd = math.sqrt((c_var + t_var) / 2)
        if pooled_sd == 0:
            # No spread in either group: identical means are perfectly
            # balanced, any difference is unbounded in SMD terms.
            smd = 0.0 if c_mean == t_mean else float("inf")
        else:
            smd = abs(t_mean - c_mean) / pooled_sd
        report[metric] = {
            "control_mean": c_mean,
            "target_mean": t_mean,
            "control_n": float(len(c_vals)),
            "target_n": float(len(t_vals)),
            "smd": smd,
            "balanced": 1.0 if smd <= max_standardized_diff else 0.0,
        }
    return report


def _worst_smd(report: dict[str, dict[str, float]]) -> float:
    """Largest SMD across metrics -- the score a candidate split is ranked by."""
    if not report:
        return float("inf")
    return max(r["smd"] for r in report.values())


class DegenerateSplitError(Exception):
    """One of the groups came out empty, so there is nothing to compare.

    Raised rather than returned: two files, one of them empty, is not a
    usable pilot, and the previous behaviour was to hand it back with a
    balance report that could still read PASSED. It happens when the
    grouping attributes cut the list so finely that nearly every stratum
    has one member -- see `_assign` and `strata_warnings`.
    """

    def __init__(self, control_n: int, target_n: int, strata_count: int, candidate_count: int):
        self.control_n = control_n
        self.target_n = target_n
        super().__init__(
            f"split produced КГ={control_n} / ЦГ={target_n} over {strata_count} strata for "
            f"{candidate_count} clients -- one group is empty, so the pilot cannot be measured. "
            "Select fewer grouping attributes (or coarser ones: ОКВЭД section instead of the full "
            "code, a bucketed money metric instead of the raw value) so that strata hold several "
            "clients each."
        )


def strata_warnings(
    strata: dict[tuple, list[str]], candidate_count: int, control_n: int, target_n: int,
    target_ratio: float, max_ratio_deviation: float,
) -> list[str]:
    """Why a split's group sizes should not be trusted, in plain language.

    The balance report says whether the *means* line up; it says nothing
    about the groups being the sizes that were asked for. A 47/3 split can
    pass an SMD check on one article and is still not an AB test.
    """
    warnings: list[str] = []
    singletons = sum(1 for members in strata.values() if len(members) == 1)
    if candidate_count and singletons / candidate_count > 0.5:
        warnings.append(
            f"{singletons} из {len(strata)} страт содержат одного клиента "
            f"({singletons / candidate_count:.0%} списка). Признаки разбиения слишком дробные: "
            "страта из одного человека не может быть разделена на КГ и ЦГ, и баланс внутри неё "
            "не проверяется. Возьмите меньше признаков или более крупные (раздел ОКВЭД вместо "
            "полного кода)."
        )
    total = control_n + target_n
    if total:
        share = target_n / total
        if abs(share - target_ratio) > max_ratio_deviation:
            warnings.append(
                f"фактическая доля ЦГ {share:.1%} вместо запрошенных {target_ratio:.0%} "
                f"(КГ={control_n}, ЦГ={target_n}). Группы разного размера сравнимы по средним, "
                "но мощность теста определяется меньшей из них."
            )
    return warnings


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
    seed_used = base_seed

    # Track the best attempt, not just the last one. Previously the loop
    # reassigned control/target every iteration and returned whatever the
    # final shuffle produced, so when no attempt met the threshold the
    # caller got an arbitrary split rather than the least-imbalanced one.
    # `None` rather than inf: an empty balance report scores inf (e.g. a
    # degenerate split where one group ends up empty, so no metric has
    # values on both sides). With inf as the initial value, `inf < inf` is
    # false and no candidate would ever be recorded, returning two empty
    # groups. The first attempt must always be kept.
    best_score: float | None = None

    while attempt < max(1, config.max_reshuffle_attempts):
        seed = base_seed + attempt
        candidate_control, candidate_target = _assign(strata, config.target_ratio, seed=seed)
        attempt += 1

        if not financial_values:
            control, target, seed_used = candidate_control, candidate_target, seed
            break

        candidate_report = _balance_report(
            candidate_control, candidate_target, financial_values, config.max_standardized_diff
        )
        score = _worst_smd(candidate_report)
        if best_score is None or score < best_score:
            best_score = score
            control, target, seed_used = candidate_control, candidate_target, seed
            balance_report = candidate_report

        if candidate_report and all(r["balanced"] == 1.0 for r in candidate_report.values()):
            balanced = True
            break
    else:
        balanced = False

    strata_summary = {
        " & ".join(key) if key else "(no grouping metrics)": {"total": len(members)}
        for key, members in strata.items()
    }

    if not control or not target:
        raise DegenerateSplitError(len(control), len(target), len(strata), len(inn_list))

    warnings = strata_warnings(
        strata, len(inn_list), len(control), len(target),
        config.target_ratio, config.max_ratio_deviation,
    )
    # A split whose groups are the wrong sizes is not "balanced", whatever
    # the means say -- reporting PASSED on a 47/3 split was how this went
    # unnoticed in the first place.
    if warnings:
        balanced = False

    return SplitResult(
        control=control,
        target=target,
        strata_summary=strata_summary,
        balance_report=balance_report,
        attempts_used=attempt,
        balanced=balanced,
        seed=seed_used,
        warnings=warnings,
    )
