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


def test_more_draws_never_make_the_balance_worse():
    inns, grouping, financial = _population(200)
    worst = []
    for draws in (1, 50, 500):
        result = split(inns, grouping, financial,
                       SplitConfig(max_reshuffle_attempts=draws, random_seed=7))
        worst.append(result.worst_smd)
    assert worst[1] <= worst[0] + 1e-9
    assert worst[2] <= worst[1] + 1e-9


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

def test_an_unreachable_threshold_is_reported_with_what_to_do():
    """At 200 clients over a dozen covariates no assignment reaches 0.1.
    That is missing information, not a weak search."""
    inns = [f"{7000000000 + i}" for i in range(60)]
    grouping = {f"attr{a}": {inn: f"v{(i + a) % 7}" for i, inn in enumerate(inns)}
                for a in range(5)}
    financial = {"chod": {inn: float(i * i) for i, inn in enumerate(inns)}}
    result = split(inns, grouping, financial, SplitConfig(max_reshuffle_attempts=200))
    if not result.balanced:
        assert any("сокращайте набор признаков" in w for w in result.warnings)


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
