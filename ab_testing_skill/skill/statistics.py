"""Statistics for judging a pilot: effect, confidence, power.

Pure functions over plain lists, no numpy -- the skill runs on the standard
library so it can be dropped into a restricted environment without a wheel
build. The distributions it needs (Student t, normal, binomial) are
computed from `math` directly; scipy would be a heavier dependency than the
three functions justify.

Three decisions worth knowing about:

**Effect sizes, not p-values, decide balance.** A p-value answers "is there
evidence of a difference", and the answer depends on how many clients are
in the pilot: a fixed 0.10 standardised difference is flagged 9% of the
time at n=50 and 100% of the time at n=50,000. Measured, not asserted --
`docs/analysis/power_check.py`. So balance is judged by SMD against a
threshold, and the tests here are for the *effect*, where asking "is this
distinguishable from zero" is the right question.

**The sign test runs beside the t-test, not instead of it.** The t-test on
means is carried by the largest clients; the sign test only counts
directions, so it is immune to them. The pair of them is a diagnostic: t
significant while signs are not means the effect rides on a handful of big
clients, and signs significant while t is not means a broad small effect
the means lack the power to resolve.

**A rerandomised assignment needs randomisation inference.** Choosing the
most balanced of a thousand draws changes the reference distribution, so a
textbook t-test on the result is no longer exactly calibrated. The sign-flip
permutation test here makes no distributional assumption at all and is the
honest companion to the rerandomised split.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

__all__ = [
    "EffectEstimate",
    "minimum_detectable_effect",
    "normal_cdf",
    "paired_effect",
    "permutation_pvalue",
    "permutation_two_sample",
    "sign_test",
    "smd",
    "student_t_cdf",
    "t_critical",
    "welch_test",
]


def normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _log_beta(a: float, b: float) -> float:
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def _betacf(a: float, b: float, x: float, iterations: int = 200) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method)."""
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, iterations + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    return h


def _incomplete_beta(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.log(x) * a + math.log(1.0 - x) * b - _log_beta(a, b))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - math.exp(
        math.log(1.0 - x) * b + math.log(x) * a - _log_beta(b, a)
    ) * _betacf(b, a, 1.0 - x) / b


def student_t_cdf(t: float, df: float) -> float:
    """P(T <= t) for Student's t with `df` degrees of freedom."""
    if df <= 0:
        return float("nan")
    x = df / (df + t * t)
    tail = 0.5 * _incomplete_beta(df / 2.0, 0.5, x)
    return 1.0 - tail if t > 0 else tail


def t_critical(df: float, alpha: float = 0.05) -> float:
    """Two-sided critical value; bisection on the CDF, which is monotone."""
    if df <= 0:
        return float("nan")
    target = 1.0 - alpha / 2.0
    low, high = 0.0, 100.0
    for _ in range(200):
        mid = (low + high) / 2.0
        if student_t_cdf(mid, df) < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def smd(control: list[float], target: list[float]) -> float:
    """Standardised mean difference: the balance measure, free of n.

    Pooled standard deviation in the denominator, so the sign of the metric
    cannot flip the verdict -- which is what went wrong when this was a
    relative difference of means and ЧОД went negative.
    """
    control = [float(v) for v in control if v is not None]
    target = [float(v) for v in target if v is not None]
    if len(control) < 2 or len(target) < 2:
        return float("nan")
    c_var = _variance(control)
    t_var = _variance(target)
    pooled = math.sqrt((c_var + t_var) / 2.0)
    if pooled == 0:
        return 0.0 if _mean(control) == _mean(target) else float("inf")
    return abs(_mean(target) - _mean(control)) / pooled


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return sum((v - mean) ** 2 for v in values) / (len(values) - 1)


@dataclass
class EffectEstimate:
    n: int
    mean: float
    low: float
    high: float
    p_value: float
    std_error: float

    @property
    def significant(self) -> bool:
        return self.p_value < 0.05

    def describe(self, unit: str = "руб/мес") -> str:
        if self.n < 2:
            return "недостаточно наблюдений для оценки"
        return (
            f"{self.mean:+,.0f} {unit} "
            f"(ДИ 95%: {self.low:+,.0f} … {self.high:+,.0f}; p = {self.p_value:.4f})"
        ).replace(",", " ")


def welch_test(control: list[float], target: list[float], alpha: float = 0.05) -> EffectEstimate:
    """Difference of means with a Welch confidence interval.

    Welch rather than pooled: the two groups are not guaranteed equal
    variance, and assuming it is free to avoid.
    """
    control = [float(v) for v in control if v is not None]
    target = [float(v) for v in target if v is not None]
    n_c, n_t = len(control), len(target)
    if n_c < 2 or n_t < 2:
        return EffectEstimate(min(n_c, n_t), float("nan"), float("nan"), float("nan"),
                              float("nan"), float("nan"))
    diff = _mean(target) - _mean(control)
    var_c, var_t = _variance(control), _variance(target)
    se = math.sqrt(var_c / n_c + var_t / n_t)
    if se == 0:
        return EffectEstimate(min(n_c, n_t), diff, diff, diff, float("nan"), 0.0)
    df_num = (var_c / n_c + var_t / n_t) ** 2
    df_den = (var_c / n_c) ** 2 / (n_c - 1) + (var_t / n_t) ** 2 / (n_t - 1)
    df = df_num / df_den if df_den > 0 else min(n_c, n_t) - 1
    q = t_critical(df, alpha)
    t_stat = diff / se
    p = 2.0 * (1.0 - student_t_cdf(abs(t_stat), df))
    return EffectEstimate(min(n_c, n_t), diff, diff - q * se, diff + q * se, p, se)


def paired_effect(deltas: list[float], alpha: float = 0.05) -> EffectEstimate:
    """One-sample t on per-client differences (the DiD effect per client)."""
    values = [float(v) for v in deltas if v is not None and not math.isnan(float(v))]
    n = len(values)
    if n < 2:
        return EffectEstimate(n, float("nan"), float("nan"), float("nan"), float("nan"),
                              float("nan"))
    mean = _mean(values)
    se = math.sqrt(_variance(values) / n)
    if se == 0:
        return EffectEstimate(n, mean, mean, mean, float("nan"), 0.0)
    df = n - 1
    q = t_critical(df, alpha)
    p = 2.0 * (1.0 - student_t_cdf(abs(mean / se), df))
    return EffectEstimate(n, mean, mean - q * se, mean + q * se, p, se)


def _binomial_tail(k: int, n: int, p: float = 0.5) -> float:
    """P(X <= k) for Binomial(n, p), summed exactly."""
    total = 0.0
    for i in range(0, k + 1):
        total += math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i))
    return min(total, 1.0)


@dataclass
class SignTest:
    positive: int
    total: int
    p_value: float

    @property
    def share(self) -> float:
        return self.positive / self.total if self.total else float("nan")

    def describe(self) -> str:
        if not self.total:
            return "нет наблюдений для теста знаков"
        return f"{self.share:.0%} клиентов в плюс ({self.positive} из {self.total}), p = {self.p_value:.4f}"


def sign_test(deltas: list[float], min_magnitude: float = 1.0) -> SignTest:
    """Exact two-sided binomial test on the direction of each client's change.

    Ignores magnitude entirely, which is the point: it cannot be carried by
    a handful of large clients the way a mean can. Changes below
    `min_magnitude` are dropped as ties rather than counted as a direction.
    """
    values = [
        float(v) for v in deltas
        if v is not None and not math.isnan(float(v)) and abs(float(v)) >= min_magnitude
    ]
    n = len(values)
    positive = sum(1 for v in values if v > 0)
    if n == 0:
        return SignTest(0, 0, float("nan"))
    k = min(positive, n - positive)
    p = min(1.0, 2.0 * _binomial_tail(k, n))
    return SignTest(positive, n, p)


def permutation_pvalue(
    deltas: list[float], draws: int = 10000, seed: int = 42
) -> float:
    """Sign-flip permutation test on per-client effects.

    Under the sharp null -- the treatment did nothing to anybody -- which
    group a pair's label was on is arbitrary, so each client's effect is
    equally likely to carry either sign. Flipping signs at random and
    counting how often the mean comes out as extreme as the observed one
    gives an exact p-value with no distributional assumption.

    This is the companion the rerandomised split needs: choosing the most
    balanced of a thousand draws changes the reference distribution a
    t-test assumes, and this test does not assume one.
    """
    values = [float(v) for v in deltas if v is not None and not math.isnan(float(v))]
    n = len(values)
    if n < 2:
        return float("nan")
    observed = abs(_mean(values))
    rng = random.Random(seed)
    at_least_as_extreme = 0
    for _ in range(draws):
        total = 0.0
        for value in values:
            total += value if rng.random() < 0.5 else -value
        if abs(total / n) >= observed - 1e-12:
            at_least_as_extreme += 1
    # +1 in both parts: the observed assignment is itself one of the
    # permutations, and a p-value of exactly zero is never honest
    return (at_least_as_extreme + 1) / (draws + 1)


def permutation_two_sample(
    control: list[float], target: list[float], draws: int = 10000, seed: int = 42
) -> float:
    """Permutation test on group labels, for unpaired groups.

    The companion to `permutation_pvalue` when there are no pairs: under the
    null that the treatment did nothing, which group a client's number was
    labelled with is arbitrary, so the labels are reshuffled and the
    difference of means recomputed. Makes no distributional assumption,
    which matters after a rerandomised assignment.
    """
    control = [float(v) for v in control if v is not None and not math.isnan(float(v))]
    target = [float(v) for v in target if v is not None and not math.isnan(float(v))]
    if len(control) < 2 or len(target) < 2:
        return float("nan")
    observed = abs(_mean(target) - _mean(control))
    pool = control + target
    n_c = len(control)
    rng = random.Random(seed)
    extreme = 0
    for _ in range(draws):
        shuffled = pool[:]
        rng.shuffle(shuffled)
        diff = abs(_mean(shuffled[n_c:]) - _mean(shuffled[:n_c]))
        if diff >= observed - 1e-12:
            extreme += 1
    return (extreme + 1) / (draws + 1)


@dataclass
class DetectableEffect:
    """What size of effect this pilot could actually resolve."""

    n_per_group: int
    baseline: float
    absolute: float          # in the metric's own units
    relative: float | None   # as a share of the baseline, when that is meaningful
    requested: float | None  # the effect the submitter said they expect
    power: float
    alpha: float

    @property
    def underpowered(self) -> bool:
        return (
            self.requested is not None
            and self.relative is not None
            and self.requested < self.relative
        )

    def describe(self) -> str:
        if self.relative is None:
            return (
                f"различимый эффект ≈ {self.absolute:,.0f} в единицах метрики "
                f"(база близка к нулю, в процентах не выражается)".replace(",", " ")
            )
        text = (
            f"пилот из {self.n_per_group} клиентов в группе различит эффект "
            f"примерно от {self.relative:.0%} при мощности {self.power:.0%}"
        )
        if self.requested is not None:
            text += f"; заявлено {self.requested:.0%}"
        return text


def minimum_detectable_effect(
    values: list[float],
    n_per_group: int | None = None,
    requested_relative: float | None = None,
    alpha: float = 0.05,
    power: float = 0.8,
) -> DetectableEffect:
    """The smallest effect this pilot has a real chance of seeing.

        MDE = (t_{1-α/2} + t_{power}) · SD · sqrt(2/n) ,  as a share of the mean

    The number the intake form has been collecting and ignoring. A pilot of
    fifty clients on a metric that varies as much as ЧОД cannot resolve a
    5% effect however long it runs -- and that is knowable before the pilot
    starts, from the spread of the pre-period alone, rather than a year
    later from a confidence interval spanning zero.
    """
    clean = [float(v) for v in values if v is not None and not math.isnan(float(v))]
    n_per_group = n_per_group or max(1, len(clean) // 2)
    if len(clean) < 2 or n_per_group < 2:
        return DetectableEffect(n_per_group, float("nan"), float("nan"), None,
                                requested_relative, power, alpha)
    sd = math.sqrt(_variance(clean))
    baseline = _mean(clean)
    df = 2 * n_per_group - 2
    # t at the power quantile is a one-sided critical value
    t_alpha = t_critical(df, alpha)
    t_power = t_critical(df, 2 * (1 - power))
    absolute = (t_alpha + t_power) * sd * math.sqrt(2.0 / n_per_group)
    relative = absolute / abs(baseline) if abs(baseline) > 1e-9 else None
    return DetectableEffect(
        n_per_group=n_per_group,
        baseline=baseline,
        absolute=absolute,
        relative=relative,
        requested=requested_relative,
        power=power,
        alpha=alpha,
    )
