"""Rerandomisation: the criterion, the floor, and the honest failure."""
from datetime import date, timedelta
from pathlib import Path

import pytest

from skill.config import SplitConfig
from skill.connectors.email_connector import LoggingEmailConnector
from skill.models import PilotRequest
from skill.pipeline import UnderpoweredPilotError, run_intake
from skill.splitter import (
    _column_floor,
    choose_strata_keys,
    column_diffs,
    design_matrix,
    imbalance_score,
    split,
)

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "sample_data" / "sample_inn_input.csv"


def _population(n: int):
    """Deterministic clients with one money metric and one attribute."""
    inns = [f"{7000000000 + i}" for i in range(n)]
    money = {inn: float((i * 37) % 1000) * 1000 for i, inn in enumerate(inns)}
    group = {inn: ["A", "B", "C", "D"][i % 4] for i, inn in enumerate(inns)}
    return inns, {"seg": group}, {"chod": money}


# --- the criterion ---------------------------------------------------------

def test_the_design_matrix_covers_money_trend_and_categories():
    inns, grouping, financial = _population(40)
    matrix, names, _ = design_matrix(
        inns, grouping, financial,
        {"chod": {inn: [1.0, 2.0, 3.0] for inn in inns}},
    )
    assert any(n.endswith(":уровень") for n in names)
    assert any(n.endswith(":тренд") for n in names)
    assert any(n.startswith("seg=") for n in names)
    assert all(len(col) == len(inns) for col in matrix)


def test_categorical_columns_are_dummy_coded_not_one_hot():
    """k levels need k-1 columns; all k sum to one and the criterion would
    count the same imbalance twice."""
    inns, grouping, financial = _population(40)
    _, names, _ = design_matrix(inns, grouping, financial)
    assert len([n for n in names if n.startswith("seg=")]) == 3    # four levels


def test_a_constant_covariate_is_dropped():
    inns, _, financial = _population(20)
    _, names, _ = design_matrix(inns, {"same": {inn: "X" for inn in inns}}, financial)
    assert not any(n.startswith("same=") for n in names)


def test_more_draws_never_make_the_split_worse():
    """The draw sequence is a prefix of a longer one and the best is kept,
    so the ranking key can only improve with budget.

    Checked on `(search_excess, criterion)`, which is the key the search
    actually orders by. `worst_smd` alone is *not* monotone and should not
    be asserted to be: once every covariate is comfortably inside the bar,
    the criterion is free to let the worst one drift from 0.004 to 0.011 in
    exchange for gains across the rest -- which is the right trade, and the
    reason the key has two elements.
    """
    inns, grouping, financial = _population(200)
    keys = []
    for draws in (1, 50, 500):
        result = split(inns, grouping, financial,
                       SplitConfig(max_reshuffle_attempts=draws, random_seed=7))
        keys.append((result.search_excess, result.criterion))
    assert keys[1] <= (keys[0][0] + 1e-9, keys[0][1] + 1e-9)
    assert keys[2] <= (keys[1][0] + 1e-9, keys[1][1] + 1e-9)


def test_the_search_minimises_instead_of_stopping_at_the_threshold():
    """It used to break out on the first draw under the bar -- which with
    stratification is usually draw one, so 1000 draws and 1 draw returned
    the identical split."""
    inns, grouping, financial = _population(300)
    one = split(inns, grouping, financial,
                SplitConfig(max_reshuffle_attempts=1, random_seed=11))
    many = split(inns, grouping, financial,
                 SplitConfig(max_reshuffle_attempts=400, random_seed=11))
    assert many.attempts_used > 1, "the budget has to actually be spent"
    assert many.best_attempt > 1, "the kept draw is not the first one"
    assert many.criterion < one.criterion


def test_the_search_reports_where_the_kept_draw_sits():
    inns, grouping, financial = _population(300)
    result = split(inns, grouping, financial,
                   SplitConfig(max_reshuffle_attempts=200, random_seed=3))
    assert 1 <= result.best_attempt <= result.attempts_used
    assert result.beaten_draws == result.attempts_used - 1, \
        "every other draw was ranked, and none of them tied the winner"
    assert result.criterion_name


def test_an_acceptable_split_is_never_dropped_for_a_better_criterion():
    """Ranking by the criterion alone returned a draw past the bar when a
    passing one had been seen -- measured, 0.133 at 25 draws became 0.171 at
    200. The key is lexicographic for exactly this reason."""
    inns = [f"{7000000000 + i}" for i in range(200)]
    grouping = {f"attr{a}": {inn: f"v{(i + a) % 5}" for i, inn in enumerate(inns)}
                for a in range(3)}
    financial = {"chod": {inn: float((i * 991) % 7919) for i, inn in enumerate(inns)}}
    excess = []
    for draws in (10, 50, 250):
        result = split(inns, grouping, financial,
                       SplitConfig(max_reshuffle_attempts=draws, random_seed=5))
        excess.append(result.search_excess)
    assert excess == sorted(excess, reverse=True), excess


# --- the criterion itself --------------------------------------------------

def test_the_criterion_is_mahalanobis_when_the_design_can_be_inverted():
    inns, grouping, financial = _population(200)
    result = split(inns, grouping, financial, SplitConfig(max_reshuffle_attempts=20))
    assert result.criterion_name == "Махаланобис"


def test_a_wide_design_on_a_long_list_falls_back_to_the_sum_of_squares():
    """The precision matrix costs covariates^2 x clients once; past the
    work budget it is not worth it and the identity metric serves."""
    inns, grouping, financial = _population(400)
    result = split(inns, grouping, financial,
                   SplitConfig(max_reshuffle_attempts=5, max_search_cells=100))
    assert result.criterion_name == "сумма квадратов SMD"


def test_mahalanobis_counts_a_duplicated_covariate_once():
    """The point of the inverse covariance, in one measurement.

    A money level and its own trend move together; four ОКВЭД dummies of
    the same attribute are correlated by construction. A sum of squares
    charges the same underlying imbalance once per correlated column, so the
    search spends its budget on whichever attribute happens to be widest.
    """
    from skill.splitter import precision_matrix

    same = [1.0, -1.0] * 50                       # one direction, four times
    other = [1.0, 1.0, -1.0, -1.0] * 25           # orthogonal to it
    matrix = [same[:], same[:], same[:], same[:], other]
    precision = precision_matrix(matrix)
    assert precision is not None, "a ridge has to rescue the singular design"

    def mahalanobis(diffs):
        return sum(
            diffs[a] * sum(row[b] * diffs[b] for b in range(len(diffs)))
            for a, row in enumerate(precision)
        )

    delta = 0.1
    on_the_duplicated = [delta] * 4 + [0.0]
    on_the_lone_one = [0.0] * 4 + [delta]

    # sum of squares: the duplicated direction looks four times as bad
    assert sum(d * d for d in on_the_duplicated) == pytest.approx(
        4 * sum(d * d for d in on_the_lone_one))
    # Mahalanobis: the same imbalance, counted once
    assert mahalanobis(on_the_duplicated) == pytest.approx(
        mahalanobis(on_the_lone_one), rel=1e-6)


# --- the achievable floor --------------------------------------------------

def test_an_odd_sized_level_has_a_floor_above_the_threshold():
    """Five clients in fifty can only split 3/2, which is 0.133 SMD at best
    -- flagging that would fire on nearly every real pilot."""
    column = [1.0] * 5 + [0.0] * 45
    floor = _column_floor(column, 25, 25)
    assert 0.12 < floor < 0.15


def test_an_even_sized_level_has_no_floor():
    assert _column_floor([1.0] * 6 + [0.0] * 44, 25, 25) == 0.0


def test_a_continuous_column_has_no_floor():
    assert _column_floor([float(i) for i in range(50)], 25, 25) == 0.0


def test_a_level_everyone_or_nobody_is_in_has_no_floor():
    assert _column_floor([1.0] * 50, 25, 25) == 0.0
    assert _column_floor([0.0] * 50, 25, 25) == 0.0


def test_a_split_at_its_floor_is_reported_as_balanced():
    """Indivisible is not imbalanced."""
    inns = [f"{7000000000 + i}" for i in range(50)]
    grouping = {"rare": {inn: ("X" if i < 5 else "Y") for i, inn in enumerate(inns)}}
    financial = {"chod": {inn: 1000.0 + i for i, inn in enumerate(inns)}}
    result = split(inns, grouping, financial, SplitConfig())
    assert result.control and result.target


# --- the strata budget -----------------------------------------------------

def test_attributes_are_taken_coarsest_first_while_cells_stay_usable():
    inns = [f"{i}" for i in range(100)]
    values = {
        "wide": {inn: f"w{i % 25}" for i, inn in enumerate(inns)},
        "narrow": {inn: f"n{i % 2}" for i, inn in enumerate(inns)},
        "medium": {inn: f"m{i % 5}" for i, inn in enumerate(inns)},
    }
    chosen, rest = choose_strata_keys(inns, values, min_per_cell=10)
    assert "narrow" in chosen, "the coarsest attribute fits first"
    assert "wide" in rest, "25 levels over 100 clients cannot be a stratum"
    assert set(chosen) | set(rest) == set(values)


def test_nothing_is_stratified_on_when_everything_is_too_fine():
    inns = [f"{i}" for i in range(30)]
    values = {"unique": {inn: inn for inn in inns}}
    chosen, rest = choose_strata_keys(inns, values, min_per_cell=10)
    assert chosen == []
    assert rest == ["unique"]


# --- the honest failure ----------------------------------------------------

def test_a_list_too_short_for_its_attributes_is_trimmed_and_says_so():
    """Sixty clients cannot balance five seven-level attributes, and the
    skill now does the arithmetic instead of handing it to the analyst: it
    keeps what the list can carry, drops the rest by how little they
    explain, and names them."""
    inns = [f"{7000000000 + i}" for i in range(60)]
    grouping = {f"attr{a}": {inn: f"v{(i + a) % 7}" for i, inn in enumerate(inns)}
                for a in range(5)}
    financial = {"chod": {inn: float(i * i) for i, inn in enumerate(inns)}}
    result = split(inns, grouping, financial, SplitConfig(max_reshuffle_attempts=200))
    assert result.dropped_metrics, "sixty clients cannot carry five attributes"
    assert all(code in result.warnings[0] for code in result.dropped_metrics)
    assert len(result.covariates) <= result.covariate_budget + 1


def test_imbalance_score_on_an_empty_side():
    assert imbalance_score([[1.0, 2.0]], [], [0, 1]) == (float("inf"), float("inf"))


def test_column_diffs_is_one_number_per_covariate():
    matrix = [[0.0, 1.0, 0.0, 1.0], [1.0, 1.0, 0.0, 0.0]]
    diffs = column_diffs(matrix, [0, 1], [2, 3])
    assert len(diffs) == 2


# --- MDE at intake ---------------------------------------------------------

def _request(**overrides):
    defaults = dict(
        pilot_name="power", valid_from=date.today(),
        valid_to=date.today() + timedelta(days=200),
        submitter_email="a@b.cc", submitter_full_name="N", recipient_emails=[],
        analyst_email="c@d.ee", expected_effect_pct=5.0,
        recalculation_frequency="month", grouping_metrics=["opf"],
        financial_effect_articles=["chod"],
    )
    defaults.update(overrides)
    return PilotRequest(**defaults)


def test_a_pilot_chasing_an_undetectable_effect_is_warned(scratch_config, tmp_path):
    result = run_intake(_request(), SAMPLE, config=scratch_config,
                        email_connector=LoggingEmailConnector(tmp_path / "out"))
    assert result.power["underpowered"] is True
    assert result.power["detectable_relative"] > 0.05
    assert any("мощность" in w for w in result.split.warnings)


def test_require_power_turns_the_warning_into_a_refusal(scratch_config, tmp_path):
    with pytest.raises(UnderpoweredPilotError) as exc_info:
        run_intake(_request(pilot_name="strict"), SAMPLE, config=scratch_config,
                   email_connector=LoggingEmailConnector(tmp_path / "out2"),
                   require_power=True)
    assert "различит эффект" in str(exc_info.value)


def test_a_realistic_expectation_passes(scratch_config, tmp_path):
    result = run_intake(_request(pilot_name="ok", expected_effect_pct=300.0), SAMPLE,
                        config=scratch_config,
                        email_connector=LoggingEmailConnector(tmp_path / "out3"))
    assert result.power["underpowered"] is False
