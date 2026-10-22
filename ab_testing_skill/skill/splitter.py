"""Step 4 of the spec: split the checked INN list into Control (КГ) and

Target (ЦГ) groups.

Per the clarified requirements: stratify on the chosen grouping metrics
(OKVED / OPF / TB / tenure bucket, or whichever subset the user picked in
step 3) and split *within each stratum* so both groups have the same
composition. Everything the strata could not match exactly -- the money
levels, their trends, the attributes too fine to stratify on -- is then
balanced by rerandomisation: draw an assignment, score the distance
between the group means, keep the best of `max_reshuffle_attempts` draws.

The pieces, each with its own reasoning at the definition:

* `choose_strata_keys` -- which attributes get exact strata and which are
  left to the criterion, because stratifying past one client per cell
  removes the freedom the search needs.
* `_assign` -- largest-remainder allocation inside each stratum, because
  rounding per stratum sends every singleton to the same group.
* `design_matrix` -- money, trends and dummy-coded levels as one
  standardised matrix, so a single threshold covers all of them.
* `precision_matrix` / `_draw_score` -- a Mahalanobis criterion, ranked
  lexicographically behind the per-covariate acceptance bar.
* `_column_floor` -- what a column could achieve at best, so an
  indivisible level is not reported as imbalance.
* `plan_allocation` (allocation.py) -- the CG/TG proportion, when it is
  chosen from the power of the list rather than fixed.
"""
from __future__ import annotations

import math
import random
import statistics
from typing import Any

from .config import SplitConfig
from .allocation import plan_allocation
from .features import asinh_trend, concentration
from .models import SplitResult

#: A categorical level smaller than this share of the list cannot be split
#: evenly, so it is merged into "прочие" for the balance criterion.
RARE_LEVEL_SHARE = 0.08
RARE_LEVEL = "прочие"

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
        # Bucketing is the caller's job now (features.stratum_values runs
        # before the split, so a continuous value can never reach a key).
        # Tenure arriving as a raw number means a direct caller skipped that
        # step, so it is still bucketed here rather than exploding the strata.
        value = bucket_tenure(raw) if metric == "tenure" and isinstance(raw, (int, float)) else raw
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


def _column_floor(column: list[float], n_control: int, n_target: int) -> float:
    """The smallest imbalance this column could possibly show.

    A binary column for a level holding an odd number of clients cannot be
    split evenly: one client has to land on one side, and that lands as a
    fixed standardised difference no assignment can remove. A level of five
    in a list of fifty is 0.133 SMD at best -- above the 0.1 convention
    before anything has gone wrong.

    Reporting that as imbalance would flag nearly every real pilot, and a
    warning that fires every time carries no information. So each column is
    judged against the better of the threshold and its own floor: a column
    is only unbalanced when it is worse than it had to be.

    Returns 0 for anything that is not a 0/1 column -- a continuous
    covariate has no such floor.
    """
    values = set(column)
    if not values <= {0.0, 1.0} or n_control == 0 or n_target == 0:
        return 0.0
    members = int(sum(column))
    n = n_control + n_target
    if members == 0 or members == n:
        return 0.0
    # best achievable: the odd one out sits on one side
    remainder = members % 2
    if remainder == 0:
        return 0.0
    share = members / n
    sd = math.sqrt(share * (1 - share))
    if sd == 0:
        return 0.0
    best_diff = abs(remainder / n_target) if n_target else 0.0
    return best_diff / sd


def choose_strata_keys(
    inn_list: list[str],
    grouping_values: dict[str, dict[str, Any]],
    min_per_cell: int,
) -> tuple[list[str], list[str]]:
    """Which attributes get exact strata, and which are only balanced on.

    Stratifying and rerandomising pull against each other. A stratum fixes
    the composition on its attributes exactly, which is strictly better --
    but it also removes freedom from the search, and with one client per
    cell there is no freedom left at all: every draw produces the same
    assignment and a thousand of them improve nothing. That is how 36 cells
    over 50 clients leaves the trend 0.28 SMD apart with the search unable
    to move it.

    So attributes are taken into the strata coarsest-first, only while the
    cells stay big enough to shuffle inside, and everything else becomes a
    covariate in the balance criterion instead. Nothing is dropped -- the
    criterion sees every attribute either way; the question is only which
    ones get matched exactly and which ones get optimised.

    This is the automatic form of "reduce the covariate set, don't buy a
    better search", which is the only thing that works on a short list.
    """
    budget = max(1, len(inn_list) // max(1, min_per_cell))
    by_width = sorted(
        grouping_values.items(),
        key=lambda item: len({str(v) for v in item[1].values()}),
    )
    chosen: list[str] = []
    cells = 1
    for code, values in by_width:
        width = max(1, len({str(v) for v in values.values()}))
        if cells * width <= budget:
            chosen.append(code)
            cells *= width
    return chosen, [code for code in grouping_values if code not in chosen]


def design_matrix(
    inn_list: list[str],
    grouping_values: dict[str, dict[str, Any]],
    financial_values: dict[str, dict[str, Any]],
    financial_matrix: dict[str, dict[str, list[float | None]]] | None = None,
) -> tuple[list[list[float]], list[str], list[list[float]]]:
    """Everything balance is judged on, as one standardised matrix.

    Numeric covariates go in directly; each categorical covariate goes in as
    one column per level (one-hot). Standardising each column means the
    criterion is in the same units as an SMD, so one threshold covers money
    in billions and a share of ЮЛ alike.

    Including the one-hot columns is not optional. A criterion over the
    numeric covariates alone optimises the money and lets the composition
    drift -- measured, it makes categorical balance slightly *worse* than a
    plain random split.
    """
    columns: list[list[float]] = []
    names: list[str] = []

    for code, values in sorted(financial_values.items()):
        columns.append([_as_float(values.get(inn)) for inn in inn_list])
        names.append(f"{code}:уровень")

    for code, matrix in sorted((financial_matrix or {}).items()):
        columns.append([asinh_trend(matrix.get(inn) or []) for inn in inn_list])
        names.append(f"{code}:тренд")

    for code, values in sorted(grouping_values.items()):
        counts: dict[str, int] = {}
        for inn in inn_list:
            counts[str(values.get(inn))] = counts.get(str(values.get(inn)), 0) + 1

        # Levels too small to split evenly are not scored. A level holding
        # three clients can only go 2/1, which is ~0.17 standardised whatever
        # the assignment -- scoring it would make every split on a long tail
        # of industries look broken while no draw could fix it. They merge
        # into "прочие" when together they are big enough, and otherwise fall
        # into the reference level. The strata still keep every level apart;
        # only the criterion stops chasing what it cannot move.
        floor = max(2, math.ceil(RARE_LEVEL_SHARE * len(inn_list)))
        common = sorted(level for level, n in counts.items() if n >= floor)
        rare = {level for level, n in counts.items() if n < floor}

        buckets = list(common)
        if rare and sum(counts[level] for level in rare) >= floor:
            buckets.append(RARE_LEVEL)

        # Dummy coding: k levels need k-1 columns. Including all k makes them
        # sum to one, so the criterion would count the same imbalance twice;
        # the dropped level is still controlled, implicitly, as the negative
        # sum of the others.
        if len(buckets) < 2:
            continue
        reference = min(buckets, key=lambda level: counts.get(level, 0))
        for level in buckets:
            if level == reference:
                continue
            columns.append([
                1.0 if (
                    str(values.get(inn)) == level
                    or (level == RARE_LEVEL and str(values.get(inn)) in rare)
                ) else 0.0
                for inn in inn_list
            ])
            names.append(f"{code}={level}")

    standardised: list[list[float]] = []
    kept: list[str] = []
    raw: list[list[float]] = []
    for column, name in zip(columns, names):
        mean = sum(column) / len(column) if column else 0.0
        variance = sum((v - mean) ** 2 for v in column) / len(column) if column else 0.0
        sd = math.sqrt(variance)
        if sd == 0:
            continue  # constant covariate: identical in any split, carries no information
        standardised.append([(v - mean) / sd for v in column])
        kept.append(name)
        raw.append(column)
    return standardised, kept, raw


def _effective_draws(config: SplitConfig, n_clients: int, n_covariates: int) -> int:
    """How many draws fit the work budget.

    Scoring a draw costs covariates x clients, so a fixed draw count is
    cheap on 200 clients and slow on 50,000. Cutting the count to fit a
    budget is the right trade: a large list reaches balance in far fewer
    draws, because the standard error of every covariate mean shrinks with n.
    """
    requested = max(1, config.max_reshuffle_attempts)
    per_draw = max(1, n_clients * max(1, n_covariates))
    affordable = max(1, config.max_search_cells // per_draw)
    return min(requested, affordable)


def _as_float(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return 0.0 if math.isnan(float(value)) else float(value)
    return 0.0


def _correlation(matrix: list[list[float]]) -> list[list[float]]:
    """Covariance of the design columns, which are already standardised.

    Mean 0 and sd 1 per column means the covariance matrix *is* the
    correlation matrix, so no centring is needed here.
    """
    k = len(matrix)
    n = len(matrix[0])
    cov = [[0.0] * k for _ in range(k)]
    for a in range(k):
        for b in range(a, k):
            value = sum(matrix[a][i] * matrix[b][i] for i in range(n)) / n
            cov[a][b] = value
            cov[b][a] = value
    return cov


def _invert(square: list[list[float]]) -> list[list[float]] | None:
    """Gauss-Jordan with partial pivoting. None when singular."""
    k = len(square)
    work = [row[:] + [1.0 if i == j else 0.0 for j in range(k)] for i, row in enumerate(square)]
    for col in range(k):
        pivot = max(range(col, k), key=lambda r: abs(work[r][col]))
        if abs(work[pivot][col]) < 1e-12:
            return None
        work[col], work[pivot] = work[pivot], work[col]
        scale = work[col][col]
        work[col] = [v / scale for v in work[col]]
        for row in range(k):
            if row != col and work[row][col] != 0.0:
                factor = work[row][col]
                work[row] = [v - factor * w for v, w in zip(work[row], work[col])]
    return [row[k:] for row in work]


def precision_matrix(matrix: list[list[float]]) -> list[list[float]] | None:
    """Inverse covariance of the design, for a true Mahalanobis criterion.

    Summing squared standardised differences treats the covariates as
    independent, and ours are plainly not: a money level and its own trend
    move together, and dummy columns of one attribute are negatively
    correlated by construction. The sum therefore counts one underlying
    imbalance several times and spends the search budget on whichever
    attribute happens to have the most levels.

    The inverse covariance fixes that -- it is the metric Morgan & Rubin
    rerandomise on, and it weights each direction by how much independent
    information it carries. Perfectly collinear columns make the matrix
    singular, so a ridge is added to the diagonal until it inverts; the
    ridge only matters for directions the data cannot distinguish anyway.
    Returns None if even a heavy ridge fails, and the caller falls back to
    the sum of squares (which is this criterion with an identity metric).
    """
    if not matrix or not matrix[0]:
        return None
    cov = _correlation(matrix)
    for ridge in (0.0, 1e-8, 1e-6, 1e-4, 1e-2, 1e-1):
        trial = [
            [value + (ridge if i == j else 0.0) for j, value in enumerate(row)]
            for i, row in enumerate(cov)
        ]
        inverse = _invert(trial)
        if inverse is not None and all(inverse[i][i] > 0 for i in range(len(inverse))):
            return inverse
    return None


def _draw_score(
    matrix: list[list[float]],
    control_idx: list[int],
    target_idx: list[int],
    precision: list[list[float]] | None,
    allowed: list[float] | None,
) -> tuple[float, float, float]:
    """(excess over the acceptance bar, criterion, worst difference).

    Three numbers because the search needs two keys, not one. Ranking draws
    by the criterion alone can return a draw that *fails* the per-covariate
    bar when a passing draw was already seen: the criterion is a sum over
    all directions, so it happily trades one covariate past the bar for
    small gains everywhere else. Measured at N=200, that turned a 0.133
    worst SMD at 25 draws into 0.171 at 200 -- more search, worse verdict.

    So draws are ordered lexicographically by `(excess, criterion)`:
    anything meeting the bar beats anything that does not, and among those
    that meet it the criterion decides. `excess` is measured against each
    column's own allowance -- the threshold or the column's achievable
    floor, whichever is larger -- so it is exactly the rule the final report
    applies, and the two can no longer disagree.
    """
    if not matrix or not control_idx or not target_idx:
        return float("inf"), float("inf"), float("inf")
    diffs: list[float] = []
    worst = 0.0
    excess = 0.0
    for index, column in enumerate(matrix):
        c_mean = sum(column[i] for i in control_idx) / len(control_idx)
        t_mean = sum(column[i] for i in target_idx) / len(target_idx)
        diff = t_mean - c_mean
        diffs.append(diff)
        worst = max(worst, abs(diff))
        if allowed is not None:
            excess = max(excess, abs(diff) - allowed[index])
    if precision is None:
        criterion = sum(d * d for d in diffs)
    else:
        n_control, n_target = len(control_idx), len(target_idx)
        scale = n_control * n_target / (n_control + n_target)
        criterion = scale * sum(
            diffs[a] * sum(row[b] * diffs[b] for b in range(len(diffs)))
            for a, row in enumerate(precision)
        )
    return max(0.0, excess), criterion, worst


def imbalance_score(
    matrix: list[list[float]],
    control_idx: list[int],
    target_idx: list[int],
    precision: list[list[float]] | None = None,
) -> tuple[float, float]:
    """(criterion to minimise, worst single standardised difference).

    The first number is what the search minimises -- it moves on every
    covariate at once, so improving the money cannot quietly cost the
    composition. With `precision` it is the Mahalanobis distance between the
    group means,

        M = (n_T * n_C / N) * d' * S^-1 * d,

    which is the Morgan & Rubin criterion; without it, the sum of squared
    differences, which is the same thing with an identity metric. The second
    number is what gets reported, because "the worst covariate is within
    0.1" is the sentence an analyst can act on.
    """
    _, criterion, worst = _draw_score(matrix, control_idx, target_idx, precision, None)
    return criterion, worst


def column_diffs(
    matrix: list[list[float]], control_idx: list[int], target_idx: list[int]
) -> list[float]:
    """Standardised mean difference per covariate, in matrix order."""
    out = []
    for column in matrix:
        c_mean = sum(column[i] for i in control_idx) / len(control_idx)
        t_mean = sum(column[i] for i in target_idx) / len(target_idx)
        out.append(abs(c_mean - t_mean))
    return out


def split(
    inn_list: list[str],
    grouping_values: dict[str, dict[str, Any]],
    financial_values: dict[str, dict[str, Any]],
    config: SplitConfig,
    financial_matrix: dict[str, dict[str, list[float | None]]] | None = None,
    seed_key: int | None = None,
) -> SplitResult:
    """Stratified assignment, then rerandomisation to pick the best draw.

    The loop was always a crude rerandomisation (Morgan & Rubin 2012): draw
    an assignment, score it, keep the best. Four things make it a principled
    one.

    *The criterion covers every covariate.* It used to be the worst SMD
    across the financial articles only, so the search was blind to the
    composition of the groups and to the trend. It is now a Mahalanobis
    distance between the group means over money levels, trends and dummy
    categorical levels, on a standardised design -- see `precision_matrix`
    for why the inverse covariance and not a plain sum of squares.

    *The number of draws is large.* Twenty-five draws of a cheap operation
    was leaving most of the available balance on the table; a thousand costs
    milliseconds.

    *The search minimises; it does not stop at the threshold.* It used to
    break out on the first draw whose worst covariate came in under
    `max_standardized_diff`, and with stratification that is usually draw
    one -- so a thousand draws and a single draw returned the identical
    split, measured. The threshold is an *acceptance* bar for the report,
    not a target for the search: below it, balance keeps buying precision
    in the final comparison, and a draw costs microseconds. The loop now
    spends its budget and keeps the minimum, stopping early only when the
    bar is already met and `search_patience` consecutive draws have failed
    to improve on it.

    One consequence worth stating, because it affects the analysis and not
    just the split: selecting the best of many draws is no longer simple
    randomisation, so a permutation test over the final groups is not exact.
    It errs on the safe side -- Morgan & Rubin show the Fisher test over the
    full permutation set is *conservative* on a rerandomised design -- so
    `skill/analysis.py` can keep using it, and `attempts_used` records how
    many draws the selection ran over.

    *The threshold is declared, and failure is reported.* Returning the best
    of N without saying whether it met the bar is how a split nobody could
    balance gets delivered as though it were fine. At N=200 over a dozen
    covariates no assignment reaches 0.1 -- that is missing information, not
    a weak search, and the result says so.
    """
    strata_keys, covariate_only = choose_strata_keys(
        inn_list, grouping_values, config.min_clients_per_stratum
    )
    strata = _build_strata(inn_list, {k: grouping_values[k] for k in strata_keys})

    # Proportion: fixed, or chosen from what the list can actually resolve.
    allocation = None
    target_ratio = config.target_ratio
    if target_ratio is None:
        allocation = plan_allocation(len(inn_list), mde_sigma=config.mde_sigma)
        target_ratio = allocation.treatment_share

    if config.random_seed is not None:
        base_seed = config.random_seed
    elif seed_key is not None:
        base_seed = seed_key          # derived from the pilot, see allocation.py
    else:
        base_seed = random.randint(0, 2**31)

    matrix, covariates, raw_columns = design_matrix(
        inn_list, grouping_values, financial_values, financial_matrix
    )
    position = {inn: i for i, inn in enumerate(inn_list)}

    control: list[str] = []
    target: list[str] = []
    balance_report: dict[str, dict[str, float]] = {}
    attempt = 0
    seed_used = base_seed
    best_key: tuple[float, float] | None = None
    best_score: float | None = None
    best_worst = float("inf")
    best_attempt = 0
    best_accepted = False
    ties = 0                       # draws that scored exactly the kept draw's key
    allowed: list[float] | None = None

    draws = _effective_draws(config, len(inn_list), len(matrix))
    # Building the precision matrix costs covariates^2 x clients once. On a
    # wide design over a long list that outweighs the search itself, and the
    # sum of squares is a serviceable fallback, so it is bought only inside
    # the same budget the draws are bought from.
    precision = None
    if matrix and len(matrix) ** 2 * len(inn_list) <= config.max_search_cells:
        precision = precision_matrix(matrix)

    while attempt < draws:
        seed = base_seed + attempt
        candidate_control, candidate_target = _assign(strata, target_ratio, seed=seed)
        attempt += 1

        if not matrix:
            control, target, seed_used = candidate_control, candidate_target, seed
            break

        if allowed is None:
            # Each column's own allowance, which the group sizes fix and the
            # draw does not: the threshold, or the column's achievable floor
            # where that is larger. Computed once off the first draw.
            allowed = [
                max(
                    config.max_standardized_diff,
                    _column_floor(raw, len(candidate_control), len(candidate_target)),
                )
                for raw in raw_columns
            ]

        excess, score, worst = _draw_score(
            matrix,
            [position[inn] for inn in candidate_control],
            [position[inn] for inn in candidate_target],
            precision,
            allowed,
        )
        key = (excess, score)
        if best_key is None or key < best_key:
            # Whatever was best before is strictly worse than this, so the
            # count of beaten draws stays derivable from the tie count alone.
            best_key, best_score, best_worst, best_attempt = key, score, worst, attempt
            best_accepted = excess <= 1e-9
            control, target, seed_used = candidate_control, candidate_target, seed
        elif key == best_key:
            ties += 1

        # Early stop only once the split is already acceptable: while it is
        # not, there is nothing to be patient about -- keep looking.
        if (
            config.search_patience
            and best_accepted
            and attempt - best_attempt >= config.search_patience
        ):
            break

    if control and target and financial_values:
        balance_report = _balance_report(
            control, target, financial_values, config.max_standardized_diff
        )

    balanced = True
    unbalanced: list[tuple[str, float, float]] = []
    if matrix and control and target:
        control_idx = [position[inn] for inn in control]
        target_idx = [position[inn] for inn in target]
        diffs = column_diffs(matrix, control_idx, target_idx)
        for name, raw_column, diff in zip(covariates, raw_columns, diffs):
            floor = _column_floor(raw_column, len(control), len(target))
            allowed = max(config.max_standardized_diff, floor)
            if diff > allowed + 1e-9:
                unbalanced.append((name, diff, allowed))
        balanced = not unbalanced

    strata_summary = {
        " & ".join(key) if key else "(no grouping metrics)": {"total": len(members)}
        for key, members in strata.items()
    }

    if not control or not target:
        raise DegenerateSplitError(len(control), len(target), len(strata), len(inn_list))

    warnings = strata_warnings(
        strata, len(inn_list), len(control), len(target),
        target_ratio, config.max_ratio_deviation,
    )
    if allocation is not None and allocation.underpowered:
        warnings.append(f"пропорция: {allocation.reason}")

    # The honest report when no assignment could meet the bar. At N=200 over
    # a dozen covariates the search plateaus well above 0.1 no matter how
    # many draws it is given -- that is a shortage of clients per covariate,
    # and saying so is more useful than returning the best of N in silence.
    if unbalanced:
        name, diff, allowed = max(unbalanced, key=lambda item: item[1] - item[2])
        warnings.append(
            f"баланс не достигнут за {attempt} розыгрыш(ей): худшая ковариата "
            f"«{name}» расходится на {diff:.3f} SMD при допустимых {allowed:.3f}"
            + (f" и ещё {len(unbalanced) - 1} ковариат(ы) вне допуска" if len(unbalanced) > 1 else "")
            + f". На списке из {len(inn_list)} клиентов и {len(covariates)} ковариат порог "
            "может быть недостижим в принципе — сокращайте набор признаков, а не "
            "увеличивайте число попыток."
        )

    concentration_warning = _concentration_warning(financial_values)
    if concentration_warning:
        warnings.append(concentration_warning)

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
        strata_metrics=strata_keys,
        covariate_only_metrics=covariate_only,
        allocation=allocation.describe() if allocation else "",
        covariates=covariates,
        worst_smd=None if best_worst == float("inf") else best_worst,
        best_attempt=best_attempt,
        criterion=best_score if best_score not in (None, float("inf")) else None,
        criterion_name="Махаланобис" if precision is not None else "сумма квадратов SMD",
        beaten_draws=max(0, attempt - 1 - ties),
        search_excess=best_key[0] if best_key else 0.0,
    )


def _concentration_warning(financial_values: dict[str, dict[str, Any]]) -> str | None:
    """One client carrying the group's total cannot be balanced away.

    Worth saying before the pilot runs: if a quarter of the metric sits on
    one client, the measured effect is that client's quarter rather than the
    treatment's, and no assignment of the rest changes it.
    """
    for code, values in sorted(financial_values.items()):
        stats = concentration(values)
        if stats.dominant:
            return (
                f"концентрация по «{code}»: {stats.describe()}. Ни одно разбиение этого "
                "списка не выровняет группы по такой метрике — эффект пилота будет "
                "определяться динамикой одного клиента. Рассмотрите исключение "
                "крупнейших клиентов из пилота либо отдельный разбор по ним."
            )
    return None
