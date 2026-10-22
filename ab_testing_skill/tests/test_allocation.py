"""Пропорция по мощности и seed от пилота.

Оба решения взяты из версии команды после прямого сравнения алгоритмов
(`docs/ab_split_benchmark_ru.md`), поэтому тесты проверяют и арифметику, и
то поведение, ради которого решения принимались.
"""
from datetime import date, timedelta
from pathlib import Path

import pytest

from skill.allocation import (
    ALLOCATION_LADDER,
    Allocation,
    effective_n,
    mde_for,
    plan_allocation,
    required_effective_n,
    seed_for_pilot,
)
from skill.config import SplitConfig
from skill.splitter import split

ROOT = Path(__file__).resolve().parent.parent


# --- арифметика мощности ---------------------------------------------------

def test_effective_n_is_the_total_for_an_even_split():
    assert effective_n(500, 500) == 1000.0


def test_an_uneven_split_costs_effective_size():
    """90/10 на 20 000 по мощности равно 50/50 на 7 200 — это и есть цена."""
    assert effective_n(18_000, 2_000) == pytest.approx(7200.0)


def test_an_empty_group_has_no_effective_size():
    assert effective_n(100, 0) == 0.0
    assert mde_for(100, 0) is None


def test_the_required_size_for_a_small_effect():
    """0,2σ при α=0,05 и мощности 80% требует n_eff ≈ 785."""
    assert required_effective_n(0.2) == pytest.approx(785, abs=1)


def test_a_bigger_effect_needs_fewer_clients():
    assert required_effective_n(0.4) < required_effective_n(0.2) < required_effective_n(0.1)


def test_mde_halves_when_the_effective_size_quadruples():
    assert mde_for(250, 250) == pytest.approx(2 * mde_for(1000, 1000), rel=1e-9)


def test_a_non_positive_effect_is_refused():
    with pytest.raises(ValueError):
        required_effective_n(0.0)


# --- лестница пропорций ----------------------------------------------------

def test_a_short_list_gets_an_even_split_and_says_it_is_underpowered():
    allocation = plan_allocation(200)
    assert allocation.treatment_share == pytest.approx(0.5)
    assert allocation.underpowered is True
    assert "не хватает" in allocation.reason


def test_the_share_grows_with_the_list():
    shares = [plan_allocation(n).treatment_share for n in (785, 1000, 2000, 5000)]
    assert shares == sorted(shares), shares
    # на 785 это 393/785 = 0,5006: округление вверх отдаёт лишнего клиента ЦГ
    assert shares[0] == pytest.approx(0.5, abs=0.002)
    assert shares[-1] == pytest.approx(0.9, abs=0.002)


def test_the_ladder_caps_at_ninety_ten():
    """Потолок не арифметический: контроль из 10% перестаёт выдерживать отток."""
    assert plan_allocation(1_000_000).treatment_share == pytest.approx(max(ALLOCATION_LADDER))


@pytest.mark.parametrize("total", [2, 7, 50, 189, 785, 1001, 9999])
def test_both_groups_always_get_someone(total):
    allocation = plan_allocation(total)
    assert allocation.n_treatment >= 1
    assert allocation.n_control >= 1
    assert allocation.n_treatment + allocation.n_control == total


def test_the_odd_client_goes_to_the_target_group():
    """На 189 клиентах банковское округление дало бы контроль больше целевой."""
    allocation = plan_allocation(189, mde_sigma=5.0)   # большой эффект -> высокая доля
    assert allocation.n_treatment >= allocation.n_control


def test_a_list_too_short_to_split_says_so():
    allocation = plan_allocation(1)
    assert allocation.underpowered is True
    assert "меньше двух" in allocation.reason


def test_the_chosen_share_actually_meets_the_requirement_when_it_can():
    for total in (800, 1500, 4000, 30_000):
        allocation = plan_allocation(total)
        if not allocation.underpowered:
            assert allocation.effective_n >= allocation.required_n


def test_a_negative_total_is_refused():
    with pytest.raises(ValueError):
        plan_allocation(-1)


# --- seed ------------------------------------------------------------------

def test_the_same_pilot_reproduces_its_split():
    """Повторный прогон не должен перекидывать клиентов между группами."""
    assert seed_for_pilot("rko_q4", date(2026, 11, 1)) == seed_for_pilot("rko_q4", date(2026, 11, 1))


def test_different_pilots_over_the_same_list_differ():
    a = seed_for_pilot("pilot_a", date(2026, 11, 1))
    b = seed_for_pilot("pilot_b", date(2026, 11, 1))
    assert a != b


def test_moving_the_start_date_changes_the_split():
    """Задокументированная обратная сторона: пилот уже идёт — дату не трогать."""
    a = seed_for_pilot("pilot", date(2026, 11, 1))
    b = seed_for_pilot("pilot", date(2026, 12, 1))
    assert a != b


# --- через сплиттер --------------------------------------------------------

def _population(n: int):
    inns = [f"{7000000000 + i}" for i in range(n)]
    return inns, {"opf": {inn: ("ЮЛ" if i % 4 else "ИП") for i, inn in enumerate(inns)}}, \
        {"chod": {inn: float((i * 37) % 997) * 1000 for i, inn in enumerate(inns)}}


def test_a_fixed_ratio_is_still_honoured():
    inns, grouping, financial = _population(400)
    result = split(inns, grouping, financial, SplitConfig(target_ratio=0.5))
    assert abs(len(result.target) / len(inns) - 0.5) <= 0.05
    assert result.allocation == "", "фиксированная пропорция ничего не подбирает"


def test_an_automatic_ratio_follows_the_ladder():
    inns, grouping, financial = _population(4000)
    result = split(inns, grouping, financial, SplitConfig(target_ratio=None))
    share = len(result.target) / len(inns)
    assert share > 0.6, f"на 4000 клиентах доля ЦГ должна вырасти, получили {share:.0%}"
    assert "эффективный объём" in result.allocation


def test_an_automatic_ratio_on_a_short_list_stays_even_and_warns():
    inns, grouping, financial = _population(150)
    result = split(inns, grouping, financial, SplitConfig(target_ratio=None))
    assert abs(len(result.target) / len(inns) - 0.5) <= 0.05
    assert any("пропорция" in w for w in result.warnings)


def test_the_seed_key_is_used_when_no_seed_is_configured():
    inns, grouping, financial = _population(300)
    config = SplitConfig(random_seed=None)
    first = split(inns, grouping, financial, config, seed_key=12345)
    second = split(inns, grouping, financial, config, seed_key=12345)
    other = split(inns, grouping, financial, config, seed_key=54321)
    assert sorted(first.target) == sorted(second.target)
    assert sorted(first.target) != sorted(other.target)


def test_an_explicit_seed_overrides_the_pilot_key():
    """Нужен другой состав при том же пилоте — задаётся явно."""
    inns, grouping, financial = _population(300)
    config = SplitConfig(random_seed=7)
    a = split(inns, grouping, financial, config, seed_key=111)
    b = split(inns, grouping, financial, config, seed_key=222)
    assert sorted(a.target) == sorted(b.target)


def test_the_pilot_name_reaches_the_seed_end_to_end(scratch_config, tmp_path):
    """Два пилота с одинаковым списком должны получить разные группы."""
    from skill.connectors.email_connector import LoggingEmailConnector
    from skill.models import PilotRequest
    from skill.pipeline import run_intake

    scratch_config.split.random_seed = None
    sample = ROOT / "sample_data" / "sample_inn_input.csv"

    def _run(name):
        request = PilotRequest(
            pilot_name=name, valid_from=date.today(),
            valid_to=date.today() + timedelta(days=200),
            submitter_email="a@b.cc", submitter_full_name="N", recipient_emails=[],
            analyst_email="c@d.ee", expected_effect_pct=300.0,
            recalculation_frequency="month", grouping_metrics=["opf"],
            financial_effect_articles=["chod"],
        )
        return run_intake(request, sample, config=scratch_config,
                          email_connector=LoggingEmailConnector(tmp_path / name))

    first = _run("pilot_one")
    scratch_config.registry.involved_inns_path.unlink(missing_ok=True)
    scratch_config.master_status.path.unlink(missing_ok=True)
    second = _run("pilot_two")
    assert sorted(first.split.target) != sorted(second.split.target)
