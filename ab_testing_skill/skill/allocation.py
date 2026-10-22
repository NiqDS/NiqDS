"""Пропорция ЦГ/КГ и seed разбиения.

Оба решения взяты из версии команды (`metric_calc_skill/skill/ab_test.py`)
после прямого сравнения алгоритмов — см. `docs/ab_split_benchmark_ru.md`.
Там они сделаны лучше, чем у нас, и причины стоит записать.

**Пропорция по мощности.** Мы всегда делили 50/50. Это максимум мощности
при фиксированном N, но не всегда то, что нужно бизнесу: при достаточно
большом списке можно отдать под воздействие 70-90% клиентов, всё ещё
сохранив способность увидеть эффект. Мощность зависит не от N, а от
`1/n_цг + 1/n_кг`; удобная форма этой величины — «эффективный объём»

    n_eff = 4·n_цг·n_кг/N          MDE = 2K/√n_eff,  K = z_{1-α/2} + z_мощн.

Отсюда прямое правило: взять максимальную долю ЦГ из лестницы, при которой
n_eff ещё не меньше требуемого. Потолок 90/10 — не формула, а то, что
контроль из 10% перестаёт выдерживать отток внутри пилота.

**Seed от имени пилота и даты старта.** У нас он был константой из конфига,
то есть два разных пилота с одинаковым списком получали одинаковое
разбиение, а случайный seed перекидывал бы клиентов между группами при
повторном прогоне — после того, как файл дополнили или отчёт потеряли.
Привязка к имени и дате решает оба: повтор даёт то же разбиение, разные
пилоты — разные.

Обратная сторона, которую надо знать: **переименовали пилот или сдвинули
дату старта — получили другой состав групп.** Измерено: 29% клиентов
меняют группу. Если пилот уже идёт, эти два поля трогать нельзя; нужен
другой состав — задавайте `random_seed` явно.
"""
from __future__ import annotations

import math
import zlib
from dataclasses import dataclass
from datetime import date
from statistics import NormalDist

__all__ = [
    "ALLOCATION_LADDER",
    "Allocation",
    "effective_n",
    "mde_for",
    "plan_allocation",
    "required_effective_n",
    "seed_for_pilot",
]

#: Доли ЦГ, из которых выбирается пропорция. Стандартный набор; потолок
#: 90/10 упирается не в арифметику, а в устойчивость контроля к оттоку.
ALLOCATION_LADDER = (0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90)

DEFAULT_MDE_SIGMA = 0.2   # эффект в долях стандартного отклонения (Cohen's d)
DEFAULT_ALPHA = 0.05
DEFAULT_POWER = 0.8


def _k_factor(alpha: float = DEFAULT_ALPHA, power: float = DEFAULT_POWER) -> float:
    normal = NormalDist()
    return normal.inv_cdf(1 - alpha / 2) + normal.inv_cdf(power)


def effective_n(n_treatment: int, n_control: int) -> float:
    """`n_eff = 4·n_цг·n_кг/N` — деление, приведённое к шкале «как 50/50».

    90/10 на 20 000 клиентах по мощности равно 50/50 на 7 200. Без этой
    величины неравное деление выглядит бесплатным, а оно не бесплатное.
    """
    total = n_treatment + n_control
    if total == 0 or n_treatment == 0 or n_control == 0:
        return 0.0
    return 4.0 * n_treatment * n_control / total


def required_effective_n(
    mde_sigma: float = DEFAULT_MDE_SIGMA,
    alpha: float = DEFAULT_ALPHA,
    power: float = DEFAULT_POWER,
) -> float:
    """Какой n_eff нужен, чтобы увидеть эффект в `mde_sigma` сигм (0,2σ → ≈785)."""
    if mde_sigma <= 0:
        raise ValueError(f"mde_sigma={mde_sigma}: ожидается положительное число")
    k = _k_factor(alpha, power)
    return 4.0 * k * k / (mde_sigma * mde_sigma)


def mde_for(
    n_treatment: int, n_control: int,
    alpha: float = DEFAULT_ALPHA, power: float = DEFAULT_POWER,
) -> float | None:
    """Минимально детектируемый эффект в сигмах при таком делении."""
    n_eff = effective_n(n_treatment, n_control)
    if n_eff <= 0:
        return None
    return 2.0 * _k_factor(alpha, power) / math.sqrt(n_eff)


@dataclass(frozen=True)
class Allocation:
    total: int
    n_treatment: int
    n_control: int
    treatment_share: float
    effective_n: float
    required_n: float
    mde: float | None
    underpowered: bool
    reason: str

    def describe(self) -> str:
        if self.total < 2:
            return self.reason
        text = (
            f"ЦГ {self.n_treatment} / КГ {self.n_control} "
            f"({self.treatment_share:.0%} / {1 - self.treatment_share:.0%}), "
            f"эффективный объём {self.effective_n:.0f}"
        )
        if self.mde is not None:
            text += f", различимый эффект от {self.mde:.2f}σ"
        if self.underpowered:
            text += f". {self.reason}"
        return text


def plan_allocation(
    total: int,
    mde_sigma: float = DEFAULT_MDE_SIGMA,
    alpha: float = DEFAULT_ALPHA,
    power: float = DEFAULT_POWER,
) -> Allocation:
    """Максимальная доля ЦГ, при которой тест ещё видит эффект `mde_sigma`.

    Не проходит даже 50/50 — делим пополам и говорим об этом прямо: при
    фиксированном размере выборки равное деление даёт максимум мощности, а
    молча отдать «красивое» разбиение на 50 клиентах было бы хуже всего.
    """
    if total < 0:
        raise ValueError(f"total={total}: ожидается неотрицательное число")

    required = required_effective_n(mde_sigma, alpha, power)

    if total < 2:
        return Allocation(
            total=total, n_treatment=total, n_control=0,
            treatment_share=1.0 if total else 0.0,
            effective_n=0.0, required_n=required, mde=None, underpowered=True,
            reason="клиентов меньше двух — разбивать нечего",
        )

    share = ALLOCATION_LADDER[0]
    for candidate in ALLOCATION_LADDER:
        if 4.0 * candidate * (1.0 - candidate) * total >= required:
            share = candidate

    # Округление вверх, а не банковское round(): на 189 клиентах round(94.5)
    # дал бы 94 в ЦГ и 95 в КГ, и «контроль больше целевой» пришлось бы
    # объяснять. Лишний клиент достаётся ЦГ — воздействие и есть цель.
    n_treatment = int(total * share + 0.5)
    n_treatment = max(1, min(total - 1, n_treatment))
    n_control = total - n_treatment
    n_eff = effective_n(n_treatment, n_control)
    underpowered = n_eff < required

    reason = ""
    if underpowered:
        shortfall = required / max(4.0 * 0.25, 1e-9)
        reason = (
            f"на эффект {mde_sigma:g}σ выборки не хватает (нужен эффективный объём "
            f"{required:.0f}, есть {n_eff:.0f}; это примерно {shortfall:.0f} клиентов "
            "при делении пополам) — делим 50/50, это максимум мощности"
        )
    return Allocation(
        total=total, n_treatment=n_treatment, n_control=n_control,
        treatment_share=n_treatment / total, effective_n=n_eff,
        required_n=required, mde=mde_for(n_treatment, n_control, alpha, power),
        underpowered=underpowered, reason=reason,
    )


def seed_for_pilot(pilot_name: str, valid_from: date) -> int:
    """Детерминированный seed из имени пилота и даты старта.

    Повторный прогон того же пилота даёт то же разбиение; разные пилоты с
    одним и тем же списком клиентов — разные. См. предупреждение в
    docstring модуля про переименование.
    """
    key = f"{pilot_name}|{valid_from.isoformat()}".encode("utf-8")
    return zlib.crc32(key)
