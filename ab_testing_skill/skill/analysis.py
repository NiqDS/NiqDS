"""Step 7 (NEW): how the pilot is actually going, read off its own history.

The pilot already builds a time series without anyone asking it to.
`financial_effect.xlsx` is written in append mode, one block of rows per
`report_date`, each row carrying a client, their group and the articles
measured that period. After three monthly recalculations that file is a
panel: every client, every period, both groups. This module is the layer
that reads it -- no new collection, no second query against the mart.

What it answers, in the order a person asks:

1. *Is the pilot working?* The difference-in-differences between the
   groups, with a confidence interval and two tests that fail in different
   ways (see below).
2. *Is it working for everyone, or for three clients?* Per-client change
   and the share of the effect carried by the largest contributors. On a
   list of a few hundred ММБ clients this is usually the whole story, and a
   mean alone hides it completely.
3. *Can I still trust the comparison?* The balance history from
   `homogeneity_checks.csv`, which says from which period the groups
   stopped being comparable -- not merely that they are not comparable now.

Two tests rather than one, deliberately. The t-test on mean change is
carried by the largest clients; the permutation test on group labels makes
no distributional assumption and survives a rerandomised assignment. When
they disagree that is information, not a problem: a significant mean with
an insignificant permutation result means the effect rides on a few big
clients, which is a sentence worth putting in the report.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .exporter import read_rows, resolve_export_path
from .statistics import (
    EffectEstimate,
    paired_effect,
    permutation_two_sample,
    sign_test,
    smd,
    welch_test,
)

__all__ = [
    "HOMOGENEITY_FILENAME",
    "PilotAnalysis",
    "PeriodPoint",
    "ClientTrend",
    "analyse_pilot",
    "NoHistoryError",
]

#: Written by monitoring on each recalculation, read here. The constant
#: lives with the reader so monitoring can import it without the two
#: modules importing each other.
HOMOGENEITY_FILENAME = "homogeneity_checks.csv"


class NoHistoryError(Exception):
    """There is nothing to analyse yet.

    Raised rather than returning an empty report: "the pilot shows no
    effect" and "the pilot has run once so far" look identical in a table
    of zeros, and only one of them is a finding.
    """


@dataclass
class PeriodPoint:
    """One `report_date`: where each group stood."""

    period: str
    control_n: int
    target_n: int
    control_mean: float
    target_mean: float
    control_total: float
    target_total: float

    @property
    def gap(self) -> float:
        return self.target_mean - self.control_mean

    @property
    def relative_gap(self) -> float | None:
        if abs(self.control_mean) < 1e-9:
            return None
        return self.gap / abs(self.control_mean)


@dataclass
class ClientTrend:
    """One client across the pilot."""

    inn: str
    group: str
    first: float
    last: float
    periods: int

    @property
    def delta(self) -> float:
        return self.last - self.first

    @property
    def relative(self) -> float | None:
        if abs(self.first) < 1e-9:
            return None
        return self.delta / abs(self.first)


@dataclass
class PilotAnalysis:
    pilot_name: str
    article: str
    periods: list[PeriodPoint]
    clients: list[ClientTrend]
    effect: EffectEstimate                 # DiD on per-client change
    effect_relative: float | None          # as a share of the control baseline
    permutation_p: float
    control_share_up: float
    target_share_up: float
    cumulative_effect: float               # roubles, over the whole pilot so far
    top_contributors: list[tuple[str, float]]
    effect_concentration: float            # share of the target delta from the top 3
    baseline_smd: float | None
    #: Paired analysis, when the split was made by matching clients into
    #: pairs (short lists -- see skill/matching.py). On a heavy-tailed
    #: metric this is where the power is: measured on 80 clients with a
    #: 30% effect, Welch finds it 37% of the time, the paired t 30%, and
    #: the paired sign test 83%. The mean-based tests drown in the tail --
    #: one client with a thousand times the median turnover decides the
    #: mean -- while the sign test only asks how often the treated client
    #: beat their own partner.
    paired: EffectEstimate | None = None
    paired_sign_p: float | None = None
    pairs_used: int = 0
    #: Pairs that lost a partner to dropout. They are excluded from the
    #: paired test, and on a short list that is worth stating: losing one
    #: client costs two observations.
    pairs_broken: int = 0
    comparability: list[dict[str, Any]] = field(default_factory=list)
    drifted_from: str | None = None
    dropouts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    articles: list[str] = field(default_factory=list)

    @property
    def baseline(self) -> PeriodPoint:
        return self.periods[0]

    @property
    def latest(self) -> PeriodPoint:
        return self.periods[-1]

    @property
    def verdict(self) -> str:
        """The one-line read, including the case where the two tests split."""
        if self.effect.n < 2:
            return "данных недостаточно для вывода"
        t_sig = self.effect.p_value == self.effect.p_value and self.effect.p_value < 0.05
        p_sig = self.permutation_p == self.permutation_p and self.permutation_p < 0.05
        direction = "положительный" if self.effect.mean > 0 else "отрицательный"
        if t_sig and p_sig:
            return f"эффект {direction} и значим по обоим тестам"
        if t_sig and not p_sig:
            return (
                f"эффект {direction} по средним, но перестановочный тест его не "
                "подтверждает — скорее всего, он держится на нескольких крупных клиентах"
            )
        if p_sig and not t_sig:
            return (
                f"эффект {direction} и подтверждается перестановочным тестом, хотя "
                "по средним незначим — похоже на небольшой эффект у многих клиентов"
            )
        if self.paired_sign_p is not None and self.paired_sign_p < 0.05:
            return (
                f"эффект {direction} по парам: клиент из ЦГ чаще обходит своего "
                "партнёра из КГ, чем наоборот (знаковый тест). По средним он "
                "незначим — на коротком списке с тяжёлым хвостом это обычная "
                "картина, и парный результат здесь надёжнее"
            )
        return "эффект статистически не подтверждён"

    def to_dict(self) -> dict:
        return {
            "pilot_name": self.pilot_name,
            "article": self.article,
            "articles": self.articles,
            "verdict": self.verdict,
            "periods": [
                {
                    "period": p.period,
                    "control_n": p.control_n,
                    "target_n": p.target_n,
                    "control_mean": p.control_mean,
                    "target_mean": p.target_mean,
                    "gap": p.gap,
                    "relative_gap": p.relative_gap,
                }
                for p in self.periods
            ],
            "effect": {
                "mean": self.effect.mean,
                "low": self.effect.low,
                "high": self.effect.high,
                "p_value": self.effect.p_value,
                "n": self.effect.n,
                "relative": self.effect_relative,
                "permutation_p": self.permutation_p,
            },
            "paired": (
                {
                    "pairs_used": self.pairs_used,
                    "pairs_broken": self.pairs_broken,
                    "mean": self.paired.mean,
                    "low": self.paired.low,
                    "high": self.paired.high,
                    "p_value": self.paired.p_value,
                    "sign_p": self.paired_sign_p,
                }
                if self.paired is not None else None
            ),
            "cumulative_effect": self.cumulative_effect,
            "share_up": {"control": self.control_share_up, "target": self.target_share_up},
            "concentration": {
                "top3_share": self.effect_concentration,
                "top_contributors": self.top_contributors,
            },
            "comparability": {
                "baseline_smd": self.baseline_smd,
                "drifted_from": self.drifted_from,
                "checks": self.comparability,
            },
            "dropouts": self.dropouts,
            "warnings": self.warnings,
        }


def _number(value: Any) -> float | None:
    """A value from the history as a float, or None if it is not one.

    The history is .xlsx when openpyxl is installed and .csv when it is
    not, and a CSV hands back strings. Without this every value failed an
    isinstance check and the whole analysis reported zeros -- a silent
    wrong answer on the fallback path, which is exactly the path a
    restricted environment uses.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if value != value else float(value)
    text = str(value).strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def analyse_pilot(pilot_folder: Path, article: str | None = None) -> PilotAnalysis:
    """Reads the pilot's accumulated history and works out how it is going."""
    pilot_folder = Path(pilot_folder)
    path = resolve_export_path(pilot_folder / "financial_effect")
    if not path.exists():
        raise NoHistoryError(
            f"{pilot_folder} has no financial_effect file yet -- run the intake, then "
            "`python -m skill.cli recalc` at least twice before there is a trend to read."
        )

    header, rows = read_rows(path)
    if not header or not rows:
        raise NoHistoryError(f"{path} is empty")

    meta_path = pilot_folder / "pilot_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    fixed = {"report_date", "codes", "group", "stat_significance"}
    articles = [c for c in header if c not in fixed]
    article = article or (articles[0] if articles else None)
    if article is None:
        raise NoHistoryError(f"{path} has no article columns to analyse")

    idx = {name: header.index(name) for name in header}
    by_client: dict[str, dict[str, float]] = {}
    group_of: dict[str, str] = {}
    periods: list[str] = []
    for row in rows:
        if not row:
            continue
        period = str(row[idx["report_date"]])
        inn = str(row[idx["codes"]])
        group = str(row[idx["group"]])
        value = row[idx[article]]
        if period not in periods:
            periods.append(period)
        group_of[inn] = group
        number = _number(value)
        if number is not None:
            by_client.setdefault(inn, {})[period] = number
    periods.sort()

    if len(periods) < 2:
        raise NoHistoryError(
            f"{path} holds only {len(periods)} period(s). A trend needs at least two: "
            "run `python -m skill.cli recalc` again next period."
        )

    points = [_period_point(p, by_client, group_of) for p in periods]
    trends = _client_trends(by_client, group_of, periods)

    control_deltas = [t.delta for t in trends if t.group == "cg"]
    target_deltas = [t.delta for t in trends if t.group == "tg"]
    effect = welch_test(control_deltas, target_deltas)
    permutation_p = permutation_two_sample(control_deltas, target_deltas, draws=5000)

    baseline = points[0]
    effect_relative = (
        effect.mean / abs(baseline.control_mean)
        if abs(baseline.control_mean) > 1e-9 and effect.mean == effect.mean
        else None
    )

    control_first = [by_client[t.inn][periods[0]] for t in trends
                     if t.group == "cg" and periods[0] in by_client.get(t.inn, {})]
    target_first = [by_client[t.inn][periods[0]] for t in trends
                    if t.group == "tg" and periods[0] in by_client.get(t.inn, {})]
    baseline_smd = smd(control_first, target_first) if control_first and target_first else None

    contributors = sorted(
        ((t.inn, t.delta) for t in trends if t.group == "tg"),
        key=lambda item: -abs(item[1]),
    )
    target_total_delta = sum(abs(d) for _, d in contributors)
    concentration = (
        sum(abs(d) for _, d in contributors[:3]) / target_total_delta
        if target_total_delta > 0 else 0.0
    )

    comparability, drifted_from = _comparability(pilot_folder)
    dropouts = _dropouts(by_client, group_of, periods)
    paired, paired_sign_p, pairs_used, pairs_broken = _paired_analysis(
        meta.get("pairs") or [], {t.inn: t.delta for t in trends}, group_of
    )

    analysis = PilotAnalysis(
        pilot_name=meta.get("pilot_name", pilot_folder.name),
        article=article,
        articles=articles,
        periods=points,
        clients=trends,
        effect=effect,
        effect_relative=effect_relative,
        permutation_p=permutation_p,
        control_share_up=_share_up(control_deltas),
        target_share_up=_share_up(target_deltas),
        cumulative_effect=_cumulative(points),
        top_contributors=contributors[:5],
        effect_concentration=concentration,
        baseline_smd=baseline_smd,
        paired=paired,
        paired_sign_p=paired_sign_p,
        pairs_used=pairs_used,
        pairs_broken=pairs_broken,
        comparability=comparability,
        drifted_from=drifted_from,
        dropouts=dropouts,
    )
    analysis.warnings = _warnings(analysis)
    return analysis


def _paired_analysis(
    pairs: list, deltas: dict[str, float], group_of: dict[str, str]
) -> tuple[EffectEstimate | None, float | None, int, int]:
    """The paired comparison, when the split was made by matching.

    Each pair contributes one number: the treated client's change minus
    their partner's. Two tests are run on those numbers and both are
    reported, because they fail in different directions. The t gives the
    size of the effect in roubles with a confidence interval, and is the
    one the business asks for; the sign test gives the significance and is
    the one to believe on a short list, because it cannot be moved by a
    single client with a thousand times the median turnover.

    A pair whose partner dropped out is skipped, not half-counted: the
    whole point of the pair is the comparison inside it.
    """
    if not pairs:
        return None, None, 0, 0
    differences: list[float] = []
    broken = 0
    for pair in pairs:
        if len(pair) != 2:
            continue
        first, second = str(pair[0]), str(pair[1])
        if first not in deltas or second not in deltas:
            broken += 1
            continue
        roles = {group_of.get(first), group_of.get(second)}
        if roles != {"cg", "tg"}:
            # Both ended up in the same group, which means the pair was not
            # the one this split actually used -- a rebase, or a hand-edited
            # group file. Counting it would invent a comparison.
            broken += 1
            continue
        treated = first if group_of.get(first) == "tg" else second
        partner = second if treated == first else first
        differences.append(deltas[treated] - deltas[partner])
    if len(differences) < 2:
        return None, None, 0, broken
    return (
        paired_effect(differences),
        sign_test(differences).p_value,
        len(differences),
        broken,
    )


def _period_point(period, by_client, group_of) -> PeriodPoint:
    control = [v[period] for inn, v in by_client.items()
               if group_of.get(inn) == "cg" and period in v]
    target = [v[period] for inn, v in by_client.items()
              if group_of.get(inn) == "tg" and period in v]
    return PeriodPoint(
        period=period,
        control_n=len(control),
        target_n=len(target),
        control_mean=sum(control) / len(control) if control else 0.0,
        target_mean=sum(target) / len(target) if target else 0.0,
        control_total=sum(control),
        target_total=sum(target),
    )


def _client_trends(by_client, group_of, periods) -> list[ClientTrend]:
    trends = []
    for inn, series in by_client.items():
        seen = [p for p in periods if p in series]
        if len(seen) < 2:
            continue
        trends.append(
            ClientTrend(
                inn=inn,
                group=group_of.get(inn, "unknown"),
                first=series[seen[0]],
                last=series[seen[-1]],
                periods=len(seen),
            )
        )
    return trends


def _share_up(deltas: list[float]) -> float:
    if not deltas:
        return float("nan")
    return sum(1 for d in deltas if d > 0) / len(deltas)


def _cumulative(points: list[PeriodPoint]) -> float:
    """Roubles the target group gained beyond the control group's path.

    Period by period rather than first-to-last: the two groups may both
    move, and what the pilot is credited with is the part of the target's
    movement the control did not share.
    """
    base = points[0]
    total = 0.0
    for point in points[1:]:
        control_change = point.control_mean - base.control_mean
        target_change = point.target_mean - base.target_mean
        total += (target_change - control_change) * point.target_n
    return total


def _comparability(pilot_folder: Path) -> tuple[list[dict[str, Any]], str | None]:
    path = Path(pilot_folder) / HOMOGENEITY_FILENAME
    if not path.exists():
        return [], None
    with open(path, newline="", encoding="utf-8") as f:
        checks = list(csv.DictReader(f))
    drifted = [c["report_date"] for c in checks if c.get("within_tolerance") == "no"]
    return checks, min(drifted) if drifted else None


def _dropouts(by_client, group_of, periods) -> dict[str, int]:
    """Clients present at the start and missing from the latest period.

    Counted per group because asymmetric attrition breaks the comparison on
    its own -- if the losers leave one group and stay in the other, the
    survivors look better without anything having worked.
    """
    first, last = periods[0], periods[-1]
    out = {"cg": 0, "tg": 0}
    for inn, series in by_client.items():
        if first in series and last not in series:
            group = group_of.get(inn)
            if group in out:
                out[group] += 1
    return out


def _warnings(analysis: PilotAnalysis) -> list[str]:
    warnings: list[str] = []

    if analysis.baseline_smd is not None and analysis.baseline_smd > 0.1:
        warnings.append(
            f"на старте группы уже расходились на {analysis.baseline_smd:.2f} SMD по «"
            f"{analysis.article}» — часть разницы «эффекта» может быть исходным перекосом, "
            "а не результатом пилота"
        )

    if analysis.drifted_from:
        warnings.append(
            f"сопоставимость групп нарушена с {analysis.drifted_from} — сравнение после "
            "этой даты менее надёжно, базу сравнения нужно пересчитать (ребейз)"
        )

    if analysis.effect_concentration > 0.5:
        names = ", ".join(inn for inn, _ in analysis.top_contributors[:3])
        warnings.append(
            f"{analysis.effect_concentration:.0%} изменения ЦГ приходится на трёх клиентов "
            f"({names}) — это их динамика, а не эффект на группе"
        )

    total = analysis.dropouts.get("cg", 0) + analysis.dropouts.get("tg", 0)
    if total:
        cg, tg = analysis.dropouts.get("cg", 0), analysis.dropouts.get("tg", 0)
        if abs(cg - tg) > max(2, 0.1 * max(cg, tg, 1)):
            warnings.append(
                f"разный отток: из КГ выбыло {cg} клиент(ов), из ЦГ {tg}. Асимметричное "
                "выбытие само по себе создаёт разницу между группами"
            )

    if len(analysis.periods) < 3:
        warnings.append(
            f"пока только {len(analysis.periods)} периода(ов) — тренд по двум точкам "
            "ненадёжен, выводы стоит делать с третьего пересчёта"
        )

    return warnings
