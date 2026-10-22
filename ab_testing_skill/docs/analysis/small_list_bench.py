"""Матчинг в пары против ререндомизации на коротких списках.

Вопрос, на который отвечает стенд: действительно ли на списке до 200
клиентов стоит сначала строить пары, а потом бросать монетку внутри пары,
вместо того чтобы разыгрывать стратифицированные назначения и выбирать
лучшее.

Меряем то, ради чего пилот затевается: насколько группы расходятся на
старте по деньгам и по составу. Плюс отдельно — что это даёт анализу:
парное сравнение снимает общую для партнёров часть дисперсии, и на
тяжёлом хвосте ЧОД это основная её часть.

Запуск:  python3 -I docs/analysis/small_list_bench.py
"""
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from skill.config import SplitConfig                              # noqa: E402
from skill.splitter import split                                  # noqa: E402
from skill.statistics import paired_effect, sign_test, welch_test  # noqa: E402

SIZES = (40, 80, 150, 200)
REPEATS = 60


def population(n: int, seed: int):
    """Синтетическая популяция ММБ: тяжёлый хвост, часть клиентов в убытке."""
    rng = random.Random(seed)
    inns = [f"{7000000000 + seed * 100000 + i}" for i in range(n)]
    chod, tb, industry, opf = {}, {}, {}, {}
    for inn in inns:
        value = rng.lognormvariate(10, 1.8)
        if rng.random() < 0.07:
            value = -value
        chod[inn] = value
        tb[inn] = f"ТБ-{rng.randrange(6)}"
        industry[inn] = f"IND{rng.randrange(8)}"
        opf[inn] = rng.choice(["ЮЛ", "ЮЛ", "ЮЛ", "ИП"])
    return inns, {"chod": chod}, {"tb": tb, "industry": industry, "opf": opf}


def smd(values, control, target) -> float:
    c = [values[i] for i in control]
    t = [values[i] for i in target]
    pooled = ((statistics.variance(c) + statistics.variance(t)) / 2) ** 0.5
    if pooled == 0:
        return 0.0
    return abs(statistics.mean(t) - statistics.mean(c)) / pooled


def composition_gap(attribute, control, target) -> float:
    """Худшее расхождение долей по уровням признака."""
    levels = set(attribute.values())
    worst = 0.0
    for level in levels:
        c = sum(1 for i in control if attribute[i] == level) / len(control)
        t = sum(1 for i in target if attribute[i] == level) / len(target)
        worst = max(worst, abs(c - t))
    return worst


def run(mode: str, inns, financial, grouping):
    config = SplitConfig(
        random_seed=42,
        max_reshuffle_attempts=1000,
        pair_small_lists=(mode == "pairs"),
    )
    started = time.time()
    result = split(inns, grouping, financial, config)
    return result, time.time() - started


def balance_table():
    print("=" * 92)
    print("СТАРТОВЫЙ ПЕРЕКОС: пары против ререндомизации")
    print("=" * 92)
    print(f"{'N':>5} {'ЧОД ререндом':>14} {'ЧОД пары':>11} {'состав ререндом':>17} "
          f"{'состав пары':>13} {'плотность пар':>15}")
    for n in SIZES:
        rows = {"plain": [], "pairs": []}
        comp = {"plain": [], "pairs": []}
        tightness = []
        for r in range(REPEATS):
            inns, financial, grouping = population(n, seed=400 + r)
            for mode in ("plain", "pairs"):
                result, _ = run(mode, inns, financial, grouping)
                rows[mode].append(smd(financial["chod"], result.control, result.target))
                comp[mode].append(max(
                    composition_gap(values, result.control, result.target)
                    for values in grouping.values()
                ))
                if mode == "pairs" and result.pairs:
                    tightness.append(result.worst_smd or 0.0)
        print(f"{n:>5} {statistics.median(rows['plain']):>14.4f} "
              f"{statistics.median(rows['pairs']):>11.4f} "
              f"{statistics.median(comp['plain']):>17.4f} "
              f"{statistics.median(comp['pairs']):>13.4f} "
              f"{statistics.median(tightness) if tightness else float('nan'):>15.4f}")
    print("\n  'состав' — худшее расхождение долей по уровням ТБ / отрасли / ОПФ.")
    print("  Медианы по 60 прогонам на размер.")


def power_table():
    """Что пары дают анализу — и что не дают.

    Три теста на одних и тех же данных: двухвыборочный Уэлч по группам,
    парный t по разностям внутри пар и парный тест знаков. Первая строка
    каждого размера — эффекта нет: там доля должна быть около 5%, иначе
    тест врёт.
    """
    print()
    print("=" * 92)
    print("АНАЛИЗ: что пары дают, а что нет")
    print("=" * 92)
    print(f"{'N':>5} {'эффект':>8} {'Уэлч':>8} {'парный t':>10} {'знаковый':>10}")
    for n in SIZES:
        for effect in (0.0, 0.3, 1.0):
            welch = paired = signs = 0
            for r in range(REPEATS):
                inns, financial, grouping = population(n, seed=900 + r)
                result, _ = run("pairs", inns, financial, grouping)
                if not result.pairs:
                    continue
                target_set = set(result.target)
                rng = random.Random(5000 + r)
                # Прирост за период: общий шум, умноженный на базу клиента,
                # плюс эффект у ЦГ. Это то, что меряет DiD в скилле.
                change = {
                    inn: financial["chod"][inn] * (
                        rng.gauss(0, 0.25) + (effect if inn in target_set else 0.0)
                    )
                    for inn in inns
                }
                if welch_test([change[i] for i in result.control],
                              [change[i] for i in result.target]).p_value < 0.05:
                    welch += 1
                diffs = []
                for a, b in result.pairs:
                    treated, partner = (a, b) if a in target_set else (b, a)
                    diffs.append(change[treated] - change[partner])
                if paired_effect(diffs).p_value < 0.05:
                    paired += 1
                if sign_test(diffs).p_value < 0.05:
                    signs += 1
            label = "нет" if effect == 0 else f"{effect:.0%}"
            print(f"{n:>5} {label:>8} {welch / REPEATS:>7.0%} {paired / REPEATS:>9.0%} "
                  f"{signs / REPEATS:>9.0%}")
    print("\n  Строка «нет» — ложные срабатывания, должно быть около 5%.")
    print("  Остальные — мощность: доля прогонов, где реальный эффект найден.")
    print()
    print("  Парный t почти не отличается от Уэлча: на лог-нормальном ЧОД оба")
    print("  тонут в хвосте — один клиент с оборотом в тысячу раз выше медианы")
    print("  определяет среднее. Знаковый тест по парам хвоста не видит вовсе:")
    print("  он спрашивает, чаще ли клиент из ЦГ обходит своего партнёра.")
    print("  Это и есть главный выигрыш пар на коротком списке — не точнее")
    print("  среднее, а появляется тест, который на таких данных работает.")


def cost_table():
    print()
    print("=" * 92)
    print("СТОИМОСТЬ")
    print("=" * 92)
    for n in (40, 100, 200, 400):
        inns, financial, grouping = population(n, seed=11)
        _, plain = run("plain", inns, financial, grouping)
        _, paired = run("pairs", inns, financial, grouping)
        note = "" if n <= 200 else "   <- выше порога, пары не строятся"
        print(f"  N={n:>4}: ререндомизация {plain:.2f} с, пары {paired:.2f} с{note}")


if __name__ == "__main__":
    balance_table()
    power_table()
    cost_table()
