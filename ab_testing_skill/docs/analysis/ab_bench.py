"""Head-to-head: их сплиттер (metric_calc_skill) против нашего (ab_testing_skill).

Судим ИХ метрикой качества, а не нашей: `balance_check` из их `ab_test.py`
считает перекос групп в сигмах по базовому замеру, и их же отчёт поднимает
тревогу, когда |delta_sigma| превышает MDE. Это честный критерий — он взят
из их кода, а не придуман под наш алгоритм.

Два режима, потому что сравнивать надо сопоставимое:

  A. Обе половинят список 50/50. Чистое качество балансировки, без влияния
     разной пропорции.
  B. Каждая работает в своём дефолте: у них ладдер 50/50…90/10 по мощности,
     у нас фиксированные 50/50. Это сравнение продуктовых решений, а не
     алгоритмов.
  C. Одинаковый вход: наш алгоритм без атрибутов, только ИНН + ЧОД/ЧЭП.

Их пакет в этот репозиторий не входит. Распакуйте архив `metric_calc_skill`
рядом и укажите путь к нему:

    AB_BENCH_THEIRS=/path/to/metric_calc_skill python3 -I docs/analysis/ab_bench.py
"""
import importlib
import math
import os
import random
import statistics
import sys
import time
from datetime import date
from pathlib import Path

OURS = Path(__file__).resolve().parent.parent.parent
THEIRS = Path(os.environ.get("AB_BENCH_THEIRS", OURS.parent / "metric_calc_skill"))

if not (THEIRS / "skill" / "ab_test.py").exists():
    raise SystemExit(
        f"Пакет команды не найден в {THEIRS}.\n"
        "Укажите путь к распакованному metric_calc_skill:\n"
        "  AB_BENCH_THEIRS=/path/to/metric_calc_skill python3 -I docs/analysis/ab_bench.py"
    )

sys.path.insert(0, str(THEIRS.parent))
sys.path.insert(0, str(OURS))

# Их `ab_test` импортирует соседний `.period`, поэтому грузится как часть
# своего пакета, а не файлом. Имя пакета берём с диска: архив могли
# распаковать под другим именем.
theirs = importlib.import_module(f"{THEIRS.name}.skill.ab_test")

from skill.config import SplitConfig                            # noqa: E402
from skill.splitter import split as our_split                   # noqa: E402

RNG = random.Random(20261022)


# --- синтетическая популяция ММБ -------------------------------------------

def population(n: int, seed: int):
    """Клиенты с ЧОД (лог-нормальный, тяжёлый хвост, часть в минусе) и атрибутами."""
    rng = random.Random(seed)
    inns, chod, chep, tb, industry, opf = [], {}, {}, {}, {}, {}
    for i in range(n):
        inn = f"{7000000000 + seed * 100000 + i}"
        inns.append(inn)
        value = rng.lognormvariate(10, 1.8)
        if rng.random() < 0.07:
            value = -value                      # убыточные клиенты — норма для ЧОД
        chod[inn] = value
        chep[inn] = value * rng.uniform(0.3, 0.9) + rng.gauss(0, 5000)
        tb[inn] = f"ТБ-{rng.randrange(12)}"
        industry[inn] = f"IND{rng.randrange(20)}"
        opf[inn] = rng.choice(["ЮЛ", "ЮЛ", "ЮЛ", "ИП"])
    return inns, {"chod": chod, "chep": chep}, {"tb": tb, "industry": industry, "opf": opf}


# --- их критерий качества ---------------------------------------------------

def their_skew(values, treatment, control) -> float:
    """|delta_sigma| из их balance_check — перекос групп в сигмах."""
    balance = theirs.balance_check(values, treatment, control)
    return abs(balance.delta_sigma) if balance.delta_sigma is not None else float("nan")


def worst_skew(financial, treatment, control) -> float:
    return max(their_skew(values, treatment, control) for values in financial.values())


# --- прогоны ----------------------------------------------------------------

def run_theirs(inns, allocation_mode: str, mde: float, seed_key: str):
    total = len(inns)
    if allocation_mode == "even":
        allocation = theirs.Allocation(
            total=total, n_treatment=total // 2, n_control=total - total // 2,
            treatment_share=0.5, mde=theirs.mde_for(total // 2, total - total // 2),
            target_mde=mde, alpha=0.05, power=0.8,
            effective_n=theirs.effective_n(total // 2, total - total // 2),
            required_n=theirs.required_effective_n(mde), underpowered=False, reason="",
        )
    else:
        allocation = theirs.plan_allocation(total, mde=mde)
    seed = theirs.default_seed(seed_key, date(2026, 11, 1))
    result = theirs.split_groups(inns, allocation, seed)
    return result.treatment, result.control, allocation


def run_ours(inns, financial, grouping, draws: int, ratio: float = 0.5):
    result = our_split(
        inns, grouping, financial,
        SplitConfig(target_ratio=ratio, max_reshuffle_attempts=draws, random_seed=42),
    )
    return result.target, result.control, result


# --- стенд ------------------------------------------------------------------

def mode_a(sizes, repeats):
    """Обе 50/50. Чистое качество балансировки."""
    print("=" * 94)
    print("РЕЖИМ A — обе половинят список 50/50. Критерий: |delta_sigma| из их balance_check")
    print("=" * 94)
    print(f"{'N':>6} {'их медиана':>12} {'их худш.':>10} {'наш медиана':>13} {'наш худш.':>11} "
          f"{'их>MDE':>9} {'наш>MDE':>9} {'выигрыш':>9}")
    for n in sizes:
        theirs_all, ours_all = [], []
        for r in range(repeats):
            inns, financial, grouping = population(n, seed=1000 + r)
            t_t, t_c, allocation = run_theirs(inns, "even", 0.2, f"test_{n}_{r}")
            theirs_all.append(worst_skew(financial, t_t, t_c))
            o_t, o_c, _ = run_ours(inns, financial, grouping, draws=1000)
            ours_all.append(worst_skew(financial, o_t, o_c))
        mde = theirs.mde_for(n // 2, n - n // 2) or float("inf")
        t_med, o_med = statistics.median(theirs_all), statistics.median(ours_all)
        t_bad = sum(1 for v in theirs_all if v > mde) / repeats
        o_bad = sum(1 for v in ours_all if v > mde) / repeats
        gain = t_med / o_med if o_med > 0 else float("inf")
        print(f"{n:>6} {t_med:>12.4f} {max(theirs_all):>10.4f} {o_med:>13.4f} "
              f"{max(ours_all):>11.4f} {t_bad:>8.0%} {o_bad:>8.0%} {gain:>8.1f}x")
    print("\n  'их>MDE' / 'наш>MDE' — доля прогонов, где стартовый перекос превысил MDE,")
    print("  то есть ровно тот случай, про который их отчёт говорит «эффект не отличить».")


def mode_b(sizes, repeats):
    """Каждая в своём дефолте."""
    print()
    print("=" * 94)
    print("РЕЖИМ B — каждая в своём дефолте (у них ладдер по мощности, у нас 50/50)")
    print("=" * 94)
    print(f"{'N':>6} {'их доля ЦГ':>12} {'их n_eff':>10} {'наш n_eff':>11} "
          f"{'их перекос':>12} {'наш перекос':>13} {'их MDE':>9} {'наш MDE':>9}")
    for n in sizes:
        t_sk, o_sk, shares, t_eff, o_eff = [], [], [], [], []
        for r in range(repeats):
            inns, financial, grouping = population(n, seed=2000 + r)
            t_t, t_c, allocation = run_theirs(inns, "ladder", 0.2, f"test_{n}_{r}")
            t_sk.append(worst_skew(financial, t_t, t_c))
            shares.append(allocation.treatment_share)
            t_eff.append(theirs.effective_n(len(t_t), len(t_c)))
            o_t, o_c, _ = run_ours(inns, financial, grouping, draws=1000)
            o_sk.append(worst_skew(financial, o_t, o_c))
            o_eff.append(theirs.effective_n(len(o_t), len(o_c)))
        t_mde = 2 * theirs._k_factor(0.05, 0.8) / math.sqrt(statistics.mean(t_eff))
        o_mde = 2 * theirs._k_factor(0.05, 0.8) / math.sqrt(statistics.mean(o_eff))
        print(f"{n:>6} {statistics.mean(shares):>11.0%} {statistics.mean(t_eff):>10.0f} "
              f"{statistics.mean(o_eff):>11.0f} {statistics.median(t_sk):>12.4f} "
              f"{statistics.median(o_sk):>13.4f} {t_mde:>9.3f} {o_mde:>9.3f}")
    print("\n  Неравное деление — осознанный их выбор: больше клиентов получают воздействие.")
    print("  Цена видна в n_eff и MDE: 90/10 на 20 000 по мощности равно 50/50 на 7 200.")


def determinism():
    print()
    print("=" * 94)
    print("ДЕТЕРМИНИЗМ И СТОИМОСТЬ")
    print("=" * 94)
    inns, financial, grouping = population(2000, seed=7)

    a = run_theirs(inns, "ladder", 0.2, "pilot")[0]
    b = run_theirs(inns, "ladder", 0.2, "pilot")[0]
    c = run_theirs(inns, "ladder", 0.2, "pilot_renamed")[0]
    print(f"  их:  повтор идентичен: {a == b} | переименование теста меняет состав: "
          f"{len(set(a) ^ set(c)) / len(a):.0%} клиентов")

    d = run_ours(inns, financial, grouping, draws=200)[0]
    e = run_ours(inns, financial, grouping, draws=200)[0]
    print(f"  наш: повтор идентичен: {sorted(d) == sorted(e)}")

    for draws in (1, 25, 200, 1000):
        started = time.time()
        t, c_, result = run_ours(inns, financial, grouping, draws=draws)
        elapsed = time.time() - started
        print(f"  наш: {draws:>5} розыгрышей -> перекос {worst_skew(financial, t, c_):.4f}, "
              f"{elapsed:.2f} с")
    started = time.time()
    run_theirs(inns, "ladder", 0.2, "pilot")
    print(f"  их:  одно разбиение           -> {time.time() - started:.4f} с")


def mode_c(sizes, repeats):
    """Самое честное сравнение: одинаковый вход — только список ИНН.

    Их возражение «признаков для стратов у нас нет, приносят столбец ИНН»
    справедливо для их сценария. Поэтому здесь наш алгоритм работает без
    атрибутов: он балансирует ровно по тому же ЧОД/ЧЭП, который они меряют
    базовым замером ПОСЛЕ разбиения. Вход одинаковый — разница только в том,
    используются эти данные до выбора разбиения или после.
    """
    print()
    print("=" * 94)
    print("РЕЖИМ C — одинаковый вход (только ИНН + ЧОД/ЧЭП). Без атрибутов у обоих")
    print("=" * 94)
    print(f"{'N':>6} {'MDE':>8} {'их медиана':>12} {'их худш.':>10} {'наш медиана':>13} "
          f"{'наш худш.':>11} {'их %MDE':>9} {'наш %MDE':>10}")
    for n in sizes:
        t_all, o_all = [], []
        for r in range(repeats):
            inns, financial, _ = population(n, seed=3000 + r)
            t_t, t_c, _ = run_theirs(inns, "even", 0.2, f"c_{n}_{r}")
            t_all.append(worst_skew(financial, t_t, t_c))
            # без grouping: только финансовые ковариаты, как у них на входе
            o_t, o_c, _ = run_ours(inns, financial, {}, draws=1000)
            o_all.append(worst_skew(financial, o_t, o_c))
        mde = theirs.mde_for(n // 2, n - n // 2) or float("inf")
        print(f"{n:>6} {mde:>8.3f} {statistics.median(t_all):>12.4f} {max(t_all):>10.4f} "
              f"{statistics.median(o_all):>13.4f} {max(o_all):>11.4f} "
              f"{max(t_all) / mde:>8.0%} {max(o_all) / mde:>9.0%}")
    print("\n  '%MDE' — какую долю детектируемого эффекта съедает стартовый перекос")
    print("  в худшем прогоне. Это и есть цена перекоса: он вычитается из того,")
    print("  что пилот вообще способен увидеть.")


def threshold_behaviour():
    """Почему число розыгрышей перестаёт влиять: цикл выходит по достижении порога."""
    print()
    print("=" * 94)
    print("ПОВЕДЕНИЕ ПОИСКА: наш цикл останавливается на пороге, а не минимизирует")
    print("=" * 94)
    inns, financial, grouping = population(2000, seed=7)
    for threshold in (0.10, 0.02, 0.005, 0.001):
        result = our_split(
            inns, grouping, financial,
            SplitConfig(max_reshuffle_attempts=2000, random_seed=42,
                        max_standardized_diff=threshold),
        )
        print(f"  порог {threshold:<6} -> розыгрышей {result.attempts_used:>5}, "
              f"worst_smd {result.worst_smd:.5f}, перекос по ЧОД "
              f"{worst_skew(financial, result.target, result.control):.5f}")
    print("\n  Отсюда и одинаковый результат при 1 и 1000 розыгрышах в прошлой таблице:")
    print("  порог 0.1 достигается на первом же розыгрыше, искать дальше незачем.")


if __name__ == "__main__":
    mode_a([200, 500, 2000], repeats=40)
    mode_c([200, 500, 2000], repeats=40)
    mode_b([200, 1000, 5000, 20000], repeats=15)
    threshold_behaviour()
    determinism()

