"""Derived features: cohorts, trend, sections, bucketing, concentration."""
import pytest

from skill.features import (
    ASINH_SCALE,
    DECLINING,
    GROWING,
    IRREGULAR,
    NO_VALUE,
    STABLE,
    UNKNOWN,
    asinh_trend,
    bucket_values,
    cohort_of,
    concentration,
    okved_section,
    stratum_values,
    tenure_flag,
)

K = 1000.0  # realistic ЧОД is in the hundreds of thousands, not in units


# --- cohorts ---------------------------------------------------------------

@pytest.mark.parametrize(
    "name,values,expected",
    [
        ("doubling", [100 * K, 110 * K, 120 * K, 200 * K, 220 * K, 240 * K], GROWING),
        ("halving", [240 * K, 220 * K, 200 * K, 120 * K, 110 * K, 100 * K], DECLINING),
        ("flat", [100 * K, 105 * K, 98 * K, 102 * K, 99 * K, 101 * K], STABLE),
        ("mild +10%", [100 * K] * 3 + [110 * K] * 3, STABLE),
        ("two active months of six", [0, 0, 500 * K, 0, 0, 700 * K], IRREGULAR),
        ("all zero", [0, 0, 0, 0, 0, 0], NO_VALUE),
        ("under the activity floor", [50, 60, 40, 55, 45, 50], NO_VALUE),
    ],
)
def test_cohort_rules(name, values, expected):
    assert cohort_of(values) == expected, name


def test_a_steadily_loss_making_client_is_stable_not_irregular():
    """The methodology classifies growth by L/F and so needs F>0 and L>0,
    which sends every loss-making client to "Нерегулярные" on arithmetic
    rather than behaviour. Loss-making ЧОД is routine, and a client whose
    losses are steady is behaving stably."""
    assert cohort_of([-100 * K, -110 * K, -90 * K, -95 * K, -105 * K, -100 * K]) == STABLE


def test_doubling_losses_are_declining():
    assert cohort_of([-100 * K] * 3 + [-200 * K] * 3) == DECLINING


def test_a_client_crossing_from_loss_to_profit_is_growing():
    assert cohort_of([-100 * K, -80 * K, -50 * K, 50 * K, 100 * K, 150 * K]) == GROWING


def test_months_with_no_row_count_as_inactive():
    """None is "the mart had no row", which is too thin a history to call a
    trend on -- the conservative reading."""
    assert cohort_of([100 * K, None, 110 * K, None, 120 * K, None]) == IRREGULAR


def test_an_empty_window_has_no_cohort():
    assert cohort_of([]) == NO_VALUE
    assert cohort_of([None, None]) == NO_VALUE


# --- trend -----------------------------------------------------------------

def test_the_trend_is_the_log_ratio_for_values_above_the_scale():
    """asinh is a logarithm well away from zero, so a doubling reads ln 2."""
    import math

    trend = asinh_trend([100 * K] * 3 + [200 * K] * 3)
    assert abs(trend - math.log(2)) < 0.01


def test_the_trend_is_symmetric():
    up = asinh_trend([100 * K] * 3 + [200 * K] * 3)
    down = asinh_trend([200 * K] * 3 + [100 * K] * 3)
    assert abs(up + down) < 1e-9


def test_the_trend_is_defined_at_zero_and_for_negatives():
    """A ratio is not. This is the whole reason for the transform."""
    assert asinh_trend([0, 0, 0, 100 * K, 100 * K, 100 * K]) > 0
    assert asinh_trend([-100 * K] * 3 + [-200 * K] * 3) < 0
    assert asinh_trend([0, 0, 0, 0, 0, 0]) == 0.0


def test_sub_scale_movement_is_treated_as_noise():
    """Doubling from 100 to 200 roubles is not growth; the scale says so."""
    assert abs(asinh_trend([100, 100, 100, 200, 200, 200], scale=ASINH_SCALE)) < 0.2


# --- ОКВЭД -----------------------------------------------------------------

@pytest.mark.parametrize(
    "code,section",
    [
        ("47.11", "G"), ("01", "A"), ("99", "U"), ("68.2", "L"),
        ("85.41", "P"), ("10.71", "C"), ("41.20", "F"),
    ],
)
def test_okved_maps_to_its_section(code, section):
    assert okved_section(code).startswith(section + ". ")


@pytest.mark.parametrize("code", ["abc", "", None, "04", "34"])
def test_unmappable_okved_is_explicit(code):
    assert okved_section(code) == UNKNOWN


def test_sections_collapse_hundreds_of_codes_into_21():
    """The reason this exists: a raw code gives one stratum per client."""
    codes = [f"{major:02d}.{minor:02d}" for major in range(1, 100) for minor in range(1, 4)]
    assert len({okved_section(c) for c in codes} - {UNKNOWN}) <= 21


# --- bucketing -------------------------------------------------------------

def test_bucketing_spreads_clients_across_quantiles():
    values = {f"i{i}": float(i) for i in range(100)}
    buckets = bucket_values(values, 4)
    counts = {}
    for label in buckets.values():
        counts[label] = counts.get(label, 0) + 1
    assert len(counts) == 4
    assert all(20 <= n <= 30 for n in counts.values()), counts


def test_missing_values_get_their_own_bucket_not_a_drop():
    """Missingness is a property of a client; the production notebook gets
    this right with miss_category and the homogeneity check then throws it
    away. Keeping it means a coverage difference between groups is visible."""
    values = {"a": 1.0, "b": 2.0, "c": None}
    assert bucket_values(values, 2)["c"] == UNKNOWN


def test_bucketing_a_constant_does_not_crash():
    assert set(bucket_values({f"i{i}": 5.0 for i in range(10)}, 4).values()) == {"все"}


def test_bucketing_an_empty_input():
    assert bucket_values({}, 4) == {}


# --- stratum_values --------------------------------------------------------

def test_continuous_metrics_are_bucketed_before_becoming_keys():
    raw = {"chod": {f"i{i}": float(i * 1000) for i in range(40)}}
    prepared, notes = stratum_values(raw, {"chod": "numeric"})
    assert len(set(prepared["chod"].values())) <= 4, "a rouble value cannot be a key"
    assert any("корзин" in note for note in notes)


def test_categorical_metrics_pass_through():
    raw = {"opf": {"a": "ЮЛ", "b": "ИП", "c": None}}
    prepared, _ = stratum_values(raw, {"opf": "categorical"})
    assert prepared["opf"] == {"a": "ЮЛ", "b": "ИП", "c": UNKNOWN}


def test_okved_and_tenure_get_their_own_coarsening():
    raw = {"okved": {"a": "47.11", "b": "47.12"}, "tenure": {"a": 0.4, "b": 7.0}}
    prepared, _ = stratum_values(raw, {"okved": "categorical", "tenure": "numeric"})
    assert prepared["okved"]["a"] == prepared["okved"]["b"], "same section"
    assert prepared["tenure"]["a"] == "новый"
    assert prepared["tenure"]["b"] == "давний"


@pytest.mark.parametrize(
    "years,expected",
    [(0.2, "новый"), (0.99, "новый"), (1.0, "до 3 лет"), (2.9, "до 3 лет"),
     (3.0, "давний"), (12.0, "давний"), (None, UNKNOWN), ("nonsense", UNKNOWN)],
)
def test_tenure_flag(years, expected):
    assert tenure_flag(years) == expected


# --- concentration ---------------------------------------------------------

def test_concentration_finds_the_client_carrying_the_group():
    stats = concentration({"a": 470.0, "b": 100.0, "c": 100.0, "d": 330.0})
    assert stats.top_inn == "a"
    assert abs(stats.top_share - 0.47) < 0.01
    assert stats.dominant is True
    assert "47%" in stats.describe()


def test_an_evenly_spread_group_is_not_dominated():
    stats = concentration({f"i{i}": 100.0 for i in range(50)})
    assert stats.dominant is False
    assert abs(stats.top_share - 0.02) < 0.001


def test_concentration_uses_magnitude_so_a_large_loss_counts():
    stats = concentration({"a": -900.0, "b": 50.0, "c": 50.0})
    assert stats.top_inn == "a"
    assert stats.dominant is True


def test_concentration_of_nothing():
    assert concentration({}).dominant is False
    assert concentration({"a": None, "b": None}).top_inn is None
