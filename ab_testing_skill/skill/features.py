"""Derived features: what a client's history makes them comparable to.

Three jobs, all of them about turning raw metric values into something a
stratum key or a balance check can actually use.

**Trajectory cohorts.** Two clients with the same average ЧОД are not
comparable if one is growing and the other is collapsing -- and a check on
means will never say so, because the means match. The cohort rules here are
the ones from the ЧОД matching methodology (§4.2), which the analysts
arrived at independently and which separate the cases that behave
differently over a pilot.

**Trend in asinh space.** The methodology computes the trend as `L / F`, a
ratio of signed sums, which is why it needs the `F > 0 and L > 0` guard that
dumps otherwise ordinary clients into "Нерегулярные" on arithmetic rather
than on meaning. `asinh(L) - asinh(F)` is the same quantity for large
values (asinh is a log for anything well away from zero), is defined at
zero and for negatives, and is symmetric. ЧОД goes negative routinely, so
this is not a theoretical nicety.

**Bucketing.** A rouble value used as a stratum key gives one stratum per
client -- this is exactly how the splitter produced a 47/3 split, and it is
why the production notebook's stratification collapses into `rare_strats`.
Continuous metrics are bucketed here before they are allowed near a key,
and ОКВЭД is reduced to its 21 ОКВЭД2 sections rather than its hundreds of
raw codes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

__all__ = [
    "COHORTS",
    "OKVED2_SECTIONS",
    "asinh_trend",
    "bucket_values",
    "cohort_of",
    "cohorts_for",
    "concentration",
    "okved_section",
    "tenure_flag",
    "trend_for",
]

#: Scale of the asinh transform for money, in roubles. Below it the
#: transform is roughly linear, above it roughly logarithmic; 1000 puts the
#: knee where small change stops mattering for an ММБ client.
ASINH_SCALE = 1000.0

#: A month counts as "active" from this many roubles. Below it, rounding and
#: fee reversals dominate.
ACTIVE_MIN = 100.0

#: Growth/decline boundary: last half of the window against the first half.
TREND_RATIO = 1.2

GROWING = "Растущие"
STABLE = "Стабильные"
DECLINING = "Снижающиеся"
IRREGULAR = "Нерегулярные"
NO_VALUE = "Без ЧОД"

COHORTS = (GROWING, STABLE, DECLINING, IRREGULAR, NO_VALUE)

COHORT_RULES = {
    GROWING: "среднее за вторую половину окна >= первой половины × 1,2",
    STABLE: "среднее за вторую половину окна между первой ÷ 1,2 и × 1,2",
    DECLINING: "среднее за вторую половину окна <= первой половины ÷ 1,2",
    IRREGULAR: "активных месяцев меньше двух третей окна, либо половина окна <= 0",
    NO_VALUE: "во всех месяцах окна меньше 100 руб. по модулю",
}

#: ОКВЭД2 sections. A raw ОКВЭД code has hundreds of values and makes every
#: client their own stratum; the section is the level at which clients are
#: actually comparable.
OKVED2_SECTIONS: tuple[tuple[str, int, int, str], ...] = (
    ("A", 1, 3, "Сельское, лесное хоз-во, рыболовство"),
    ("B", 5, 9, "Добыча полезных ископаемых"),
    ("C", 10, 33, "Обрабатывающие производства"),
    ("D", 35, 35, "Электроэнергия, газ, пар"),
    ("E", 36, 39, "Водоснабжение, отходы"),
    ("F", 41, 43, "Строительство"),
    ("G", 45, 47, "Торговля, ремонт авто"),
    ("H", 49, 53, "Транспорт и хранение"),
    ("I", 55, 56, "Гостиницы и общепит"),
    ("J", 58, 63, "Информация и связь"),
    ("K", 64, 66, "Финансы и страхование"),
    ("L", 68, 68, "Операции с недвижимостью"),
    ("M", 69, 75, "Профессиональная, научная, техническая"),
    ("N", 77, 82, "Административная деятельность"),
    ("O", 84, 84, "Госуправление"),
    ("P", 85, 85, "Образование"),
    ("Q", 86, 88, "Здравоохранение и соцуслуги"),
    ("R", 90, 93, "Культура, спорт, досуг"),
    ("S", 94, 96, "Прочие услуги"),
    ("T", 97, 98, "Домашние хозяйства"),
    ("U", 99, 99, "Экстерриториальные организации"),
)

UNKNOWN = "нет данных"


def okved_section(code: Any) -> str:
    """'47.11' -> 'G. Торговля, ремонт авто'. Unparseable -> 'нет данных'."""
    if code is None:
        return UNKNOWN
    digits = ""
    for char in str(code).strip():
        if char.isdigit():
            digits += char
            if len(digits) == 2:
                break
        elif digits:
            break
    if not digits:
        return UNKNOWN
    number = int(digits)
    for letter, low, high, name in OKVED2_SECTIONS:
        if low <= number <= high:
            return f"{letter}. {name}"
    return UNKNOWN


def _clean(values: Sequence[float | None]) -> list[float]:
    return [float(v) for v in values if v is not None and not _is_nan(v)]


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def _halves(values: Sequence[float | None]) -> tuple[float, float]:
    """Mean of the first and of the last half of the window.

    Months with no row are skipped rather than read as zero: a client the
    mart had nothing for in March did not necessarily earn nothing.
    """
    n = len(values)
    half = max(n // 2, 1)
    first = _clean(values[:half])
    last = _clean(values[-half:])
    first_mean = sum(first) / len(first) if first else 0.0
    last_mean = sum(last) / len(last) if last else 0.0
    return first_mean, last_mean


def asinh_trend(values: Sequence[float | None], scale: float = ASINH_SCALE) -> float:
    """Trend of a window: `asinh(L/scale) - asinh(F/scale)`.

    Positive means growing. Roughly the log of the ratio of the two halves
    for anything well above `scale`, but defined at zero and for negative
    money, which a ratio is not.
    """
    first, last = _halves(values)
    return math.asinh(last / scale) - math.asinh(first / scale)


def cohort_of(
    values: Sequence[float | None],
    active_min: float = ACTIVE_MIN,
    trend_ratio: float = TREND_RATIO,
    scale: float = ASINH_SCALE,
) -> str:
    """Which trajectory cohort a client's window belongs to.

    Deliberately **not** the methodology's rule. That one classifies growth
    by `L / F` and therefore needs `F > 0 and L > 0`, which sends every
    loss-making client to "Нерегулярные" on arithmetic rather than on
    behaviour -- and loss-making ЧОД is routine. Classifying on the asinh
    trend removes the carve-out entirely: a client whose losses are steady
    is Стабильные, one whose losses are doubling is Снижающиеся, and both
    statements are the ones an analyst would make.

    Order matters: "no value" and "irregular" are decided first, so a
    client who earned nothing for four months and a lot in the fifth is
    irregular rather than spectacularly growing.

    A month the mart had no row for counts as inactive here. That is the
    conservative reading -- it may be a data gap rather than a quiet month,
    and either way the client's history is too thin to call a trend on.
    """
    present = [v for v in values if v is not None and not _is_nan(v)]
    if not present:
        return NO_VALUE
    if all(abs(v) < active_min for v in present):
        return NO_VALUE

    active = sum(1 for v in present if abs(v) >= active_min)
    if active * 3 < len(values) * 2:
        return IRREGULAR

    trend = asinh_trend(values, scale=scale)
    boundary = math.log(trend_ratio)
    if trend >= boundary:
        return GROWING
    if trend <= -boundary:
        return DECLINING
    return STABLE


def cohorts_for(matrix: dict[str, Sequence[float | None]]) -> dict[str, str]:
    return {inn: cohort_of(values) for inn, values in matrix.items()}


def trend_for(matrix: dict[str, Sequence[float | None]]) -> dict[str, float]:
    return {inn: asinh_trend(values) for inn, values in matrix.items()}


def tenure_flag(years: Any, new_below_years: float = 1.0) -> str:
    """Tenure as three states rather than a continuous number.

    A client who joined during the pre-period behaves differently from one
    who has been here for years, and the exact number of days is not what
    makes them comparable.
    """
    if years is None or _is_nan(years):
        return UNKNOWN
    try:
        value = float(years)
    except (TypeError, ValueError):
        return UNKNOWN
    if value < new_below_years:
        return "новый"
    if value < 3:
        return "до 3 лет"
    return "давний"


def bucket_values(
    values: dict[str, Any],
    buckets: int = 4,
    labels: Sequence[str] | None = None,
) -> dict[str, str]:
    """Quantile buckets of a continuous metric, as stratum-safe labels.

    Clients with no value get their own bucket rather than being dropped:
    missingness is a real property of a client, and the production notebook
    gets this right with its `miss_category`. Dropping it instead is how a
    difference in data coverage between the groups goes unnoticed.
    """
    numeric = {
        inn: float(v)
        for inn, v in values.items()
        if v is not None and not _is_nan(v) and isinstance(v, (int, float))
    }
    missing = {inn for inn in values if inn not in numeric}

    result = {inn: UNKNOWN for inn in missing}
    if not numeric:
        return result

    ordered = sorted(numeric.values())
    buckets = max(1, min(buckets, len(set(ordered))))
    if buckets == 1:
        for inn in numeric:
            result[inn] = "все"
        return result

    edges = [
        ordered[max(0, min(len(ordered) - 1, round(i * len(ordered) / buckets)))]
        for i in range(1, buckets)
    ]
    names = list(labels) if labels else [f"Q{i + 1}" for i in range(buckets)]
    for inn, value in numeric.items():
        index = sum(1 for edge in edges if value >= edge)
        result[inn] = names[min(index, len(names) - 1)]
    return result


#: Metric codes whose raw value needs a domain-specific coarsening rather
#: than generic quantile buckets.
SPECIAL_GROUPING = {"okved": okved_section, "tenure": tenure_flag}

COHORT_METRIC = "cohort"


def stratum_values(
    raw: dict[str, dict[str, Any]],
    value_types: dict[str, str],
    buckets: int = 4,
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Turns raw metric values into labels that are safe as stratum keys.

    This is the guard that was missing. A stratum key is only meaningful if
    several clients share it, so a continuous value can never be one: every
    client has their own, every stratum holds one person, and the split
    degenerates while reporting success. Here every numeric metric is
    bucketed by quantile before it can reach a key, ОКВЭД is reduced to its
    section and tenure to three states.

    Returns the labels and a note per metric saying what was done, so the
    setup package can show it rather than silently recoding the request.
    """
    prepared: dict[str, dict[str, str]] = {}
    notes: list[str] = []
    for code, values in raw.items():
        special = SPECIAL_GROUPING.get(code)
        if special is not None:
            prepared[code] = {inn: special(v) for inn, v in values.items()}
            distinct = len(set(prepared[code].values()))
            notes.append(f"{code}: огрублён до {distinct} значений")
            continue
        if value_types.get(code) == "categorical":
            prepared[code] = {
                inn: (UNKNOWN if v is None else str(v)) for inn, v in values.items()
            }
            continue
        prepared[code] = bucket_values(values, buckets=buckets)
        notes.append(f"{code}: непрерывная метрика разбита на {buckets} квантильные корзины")
    return prepared, notes


@dataclass
class Concentration:
    """How much of a group's total rides on its largest clients.

    A pilot where one client is 47% of the group's ЧОД cannot be balanced
    by any split, and its measured effect is that client's quarter rather
    than the treatment's. Worth knowing before the pilot runs, not after.
    """

    total: float
    top_share: float            # share held by the single largest client
    top_inn: str | None
    top5_share: float
    dominant: bool              # top client alone exceeds the threshold

    def describe(self) -> str:
        if self.top_inn is None:
            return "нет данных для оценки концентрации"
        return (
            f"крупнейший клиент даёт {self.top_share:.0%} суммы метрики "
            f"(ИНН {self.top_inn}), топ-5 — {self.top5_share:.0%}"
        )


def concentration(values: dict[str, Any], dominant_threshold: float = 0.25) -> Concentration:
    numeric = {
        inn: abs(float(v))
        for inn, v in values.items()
        if v is not None and not _is_nan(v) and isinstance(v, (int, float))
    }
    total = sum(numeric.values())
    if not numeric or total == 0:
        return Concentration(total=total, top_share=0.0, top_inn=None, top5_share=0.0,
                             dominant=False)
    ordered = sorted(numeric.items(), key=lambda kv: -kv[1])
    top_inn, top_value = ordered[0]
    top_share = top_value / total
    top5_share = sum(v for _, v in ordered[:5]) / total
    return Concentration(
        total=total,
        top_share=top_share,
        top_inn=top_inn,
        top5_share=top5_share,
        dominant=top_share >= dominant_threshold,
    )
