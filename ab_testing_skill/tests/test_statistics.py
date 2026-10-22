"""Statistics: the distributions, the tests, and the power calculation.

The distribution functions are hand-rolled -- the skill runs on the
standard library -- so the first job of this file is to pin them against
known values. They were checked against scipy during development to about
1e-14; scipy is not a dependency, so the constants below are the record of
that check.
"""
import math

import pytest

from skill.statistics import (
    minimum_detectable_effect,
    normal_cdf,
    paired_effect,
    permutation_pvalue,
    permutation_two_sample,
    sign_test,
    smd,
    student_t_cdf,
    t_critical,
    welch_test,
)


# --- distributions ---------------------------------------------------------

@pytest.mark.parametrize(
    "z,expected",
    [(0.0, 0.5), (1.0, 0.8413447461), (-1.0, 0.1586552539),
     (1.959963985, 0.975), (3.0, 0.9986501020)],
)
def test_normal_cdf(z, expected):
    assert abs(normal_cdf(z) - expected) < 1e-9


@pytest.mark.parametrize(
    "t,df,expected",
    [
        (0.0, 10, 0.5),
        (2.228138852, 10, 0.975),      # the 97.5th percentile at df=10
        (-2.228138852, 10, 0.025),
        (1.812461123, 10, 0.95),
        (12.70620474, 1, 0.975),       # Cauchy
        (1.959963985, 10_000_000, 0.975),  # converges on the normal
    ],
)
def test_student_t_cdf_matches_published_values(t, df, expected):
    assert abs(student_t_cdf(t, df) - expected) < 1e-6


@pytest.mark.parametrize(
    "df,alpha,expected",
    [(1, 0.05, 12.70620474), (10, 0.05, 2.228138852), (30, 0.05, 2.042272456),
     (10, 0.01, 3.169272673), (100, 0.05, 1.983971519)],
)
def test_t_critical_matches_published_values(df, alpha, expected):
    assert abs(t_critical(df, alpha) - expected) < 1e-6


def test_the_t_distribution_converges_on_the_normal():
    assert abs(t_critical(1_000_000, 0.05) - 1.959963985) < 1e-4


# --- SMD -------------------------------------------------------------------

def test_smd_is_zero_for_identical_groups():
    assert smd([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 0.0


def test_smd_is_one_standard_deviation_apart():
    control = [0.0, 1.0, 2.0, 3.0, 4.0]
    target = [v + math.sqrt(2.5) for v in control]   # shift by exactly 1 sd
    assert abs(smd(control, target) - 1.0) < 1e-9


def test_smd_cannot_be_flipped_by_a_negative_mean():
    """The defect this replaced: abs() in the numerator only, so a negative
    control mean made the ratio negative and it passed any threshold."""
    assert smd([-100.0, -110.0, -90.0], [800.0, 820.0, 780.0]) > 1.0


def test_smd_of_constants():
    assert smd([5.0] * 4, [5.0] * 4) == 0.0
    assert smd([5.0] * 4, [9.0] * 4) == float("inf")


# --- Welch and paired ------------------------------------------------------

def test_welch_recovers_a_known_difference():
    control = [10.0, 12.0, 11.0, 13.0, 9.0, 10.5, 11.5, 12.5]
    target = [v + 5.0 for v in control]
    estimate = welch_test(control, target)
    assert abs(estimate.mean - 5.0) < 1e-9
    assert estimate.low < 5.0 < estimate.high
    assert estimate.p_value < 0.001


def test_welch_on_identical_groups_finds_nothing():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    estimate = welch_test(values, values)
    assert estimate.mean == 0.0
    assert estimate.p_value > 0.99


def test_too_few_observations_is_not_an_answer():
    estimate = welch_test([1.0], [2.0])
    assert estimate.mean != estimate.mean   # NaN, not a confident zero


def test_paired_effect_matches_a_hand_computed_case():
    deltas = [2.0, 4.0, 6.0, 8.0, 10.0]           # mean 6, sd 3.1623, n 5
    estimate = paired_effect(deltas)
    assert abs(estimate.mean - 6.0) < 1e-9
    assert abs(estimate.std_error - 3.1622776601 / math.sqrt(5)) < 1e-9
    assert estimate.p_value < 0.02


# --- sign test -------------------------------------------------------------

@pytest.mark.parametrize(
    "positive,total,expected_p",
    [(5, 10, 1.0), (9, 10, 0.021484375), (10, 10, 0.001953125), (0, 10, 0.001953125)],
)
def test_sign_test_is_the_exact_binomial(positive, total, expected_p):
    deltas = [1.0] * positive + [-1.0] * (total - positive)
    assert abs(sign_test(deltas).p_value - expected_p) < 1e-9


def test_sign_test_ignores_magnitude():
    """The point of it: one enormous client cannot carry the result."""
    carried_by_one = [1000000.0] + [-1.0] * 9
    assert sign_test(carried_by_one).p_value < 0.03
    assert sign_test(carried_by_one).positive == 1


def test_ties_below_the_floor_are_dropped_not_counted():
    deltas = [0.1, -0.2, 5.0, 6.0, 7.0]
    result = sign_test(deltas, min_magnitude=1.0)
    assert result.total == 3
    assert result.positive == 3


def test_sign_test_with_nothing_to_test():
    assert sign_test([]).total == 0
    assert sign_test([0.1, 0.2]).p_value != sign_test([0.1, 0.2]).p_value  # NaN


# --- permutation -----------------------------------------------------------

def test_permutation_finds_a_real_shift():
    deltas = [5.0, 6.0, 4.0, 7.0, 5.5, 6.5, 5.0, 6.0, 4.5, 5.5] * 3
    assert permutation_pvalue(deltas, draws=2000) < 0.01


def test_permutation_finds_nothing_in_symmetric_noise():
    deltas = [1.0, -1.0, 2.0, -2.0, 3.0, -3.0, 0.5, -0.5] * 4
    assert permutation_pvalue(deltas, draws=2000) > 0.5


def test_permutation_is_never_exactly_zero():
    """An empirical p-value of 0 claims more than the draws can support."""
    deltas = [1000.0] * 40
    assert permutation_pvalue(deltas, draws=500) > 0


def test_permutation_is_reproducible():
    deltas = [3.0, -1.0, 4.0, -2.0, 5.0, 1.0, 2.0, -3.0]
    assert permutation_pvalue(deltas, draws=500) == permutation_pvalue(deltas, draws=500)


def test_two_sample_permutation_separates_shifted_groups():
    control = [10.0, 11.0, 9.0, 12.0, 10.5, 9.5, 11.5, 10.0] * 2
    target = [v + 8.0 for v in control]
    assert permutation_two_sample(control, target, draws=2000) < 0.01


def test_two_sample_permutation_on_the_same_distribution():
    control = [10.0, 11.0, 9.0, 12.0, 10.5, 9.5, 11.5, 10.0] * 2
    target = [11.0, 10.0, 12.0, 9.0, 9.5, 10.5, 10.0, 11.5] * 2
    assert permutation_two_sample(control, target, draws=2000) > 0.2


# --- minimum detectable effect --------------------------------------------

def test_a_small_pilot_cannot_resolve_a_small_effect():
    """The number the intake form collected and ignored for the whole
    project. 50 clients on a spread like ЧОД resolve tens of percent."""
    values = [100.0 * (1 + i % 7) for i in range(50)]
    mde = minimum_detectable_effect(values, n_per_group=25, requested_relative=0.05)
    assert mde.relative > 0.15
    assert mde.underpowered is True
    assert "различит эффект" in mde.describe()


def test_a_large_pilot_can():
    values = [100.0 * (1 + i % 7) for i in range(5000)]
    mde = minimum_detectable_effect(values, n_per_group=2500, requested_relative=0.15)
    assert mde.relative < 0.15
    assert mde.underpowered is False


def test_the_detectable_effect_shrinks_with_the_square_root_of_n():
    values = [100.0 * (1 + i % 7) for i in range(4000)]
    small = minimum_detectable_effect(values, n_per_group=100)
    large = minimum_detectable_effect(values, n_per_group=400)
    assert abs(small.absolute / large.absolute - 2.0) < 0.15


def test_a_baseline_near_zero_has_no_percentage():
    values = [1.0, -1.0, 2.0, -2.0] * 10
    mde = minimum_detectable_effect(values, n_per_group=20, requested_relative=0.1)
    assert mde.relative is None
    assert mde.underpowered is False      # nothing to compare against
    assert "в процентах не выражается" in mde.describe()


def test_mde_with_too_little_data():
    assert minimum_detectable_effect([1.0]).relative is None
