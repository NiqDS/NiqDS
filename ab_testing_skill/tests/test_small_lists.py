"""Short lists: the covariate budget, and matched-pair randomisation.

Both exist for the same reason. Balance is rationed by how many clients
there are per covariate, and below a couple of hundred clients the ration
runs out -- our own head-to-head benchmark walked into it, with 200
clients balancing *worse* on money with attributes than without, because
thirty dummy columns were competing for the same 200 clients.

The two answers are complementary: spend the ration on what matters
(`covariate_budget`, `choose_covariates`), and construct a balanced
assignment instead of hoping to draw one (`skill/matching.py`).
"""
import random
import statistics
from datetime import date, timedelta
from pathlib import Path

import pytest

from skill.config import SplitConfig
from skill.matching import Pairing, assign_pairs, pair_clients
from skill.splitter import (
    choose_covariates,
    covariate_budget,
    design_matrix,
    dummy_levels,
    explained_share,
    precision_matrix,
    split,
)

ROOT = Path(__file__).resolve().parent.parent


def _population(n: int, seed: int = 1, levels: int = 6):
    rng = random.Random(seed)
    inns = [f"{7000000000 + i}" for i in range(n)]
    money = {inn: rng.lognormvariate(10, 1.5) for inn in inns}
    wide = {inn: f"w{rng.randrange(levels)}" for inn in inns}
    narrow = {inn: ("ЮЛ" if rng.random() < 0.75 else "ИП") for inn in inns}
    return inns, {"wide": wide, "narrow": narrow}, {"chod": money}


# --- the budget ------------------------------------------------------------

def test_a_short_list_can_balance_fewer_covariates():
    """The whole point: the ration shrinks as the list does."""
    small = covariate_budget(25, 25, 0.10, 1000)
    medium = covariate_budget(100, 100, 0.10, 1000)
    large = covariate_budget(1000, 1000, 0.10, 1000)
    assert small < medium < large
    assert small <= 6, f"fifty clients cannot balance {small} covariates"


def test_the_budget_matches_the_arithmetic_it_claims():
    """200 clients, 0.1 threshold, 1000 draws -> about ten covariates."""
    assert 8 <= covariate_budget(100, 100, 0.10, 1000) <= 12


def test_a_long_list_is_not_rationed():
    assert covariate_budget(1000, 1000, 0.10, 1000) > 100


def test_more_draws_buy_a_little_more_room():
    assert covariate_budget(100, 100, 0.10, 10_000) > covariate_budget(100, 100, 0.10, 100)


def test_a_looser_threshold_buys_room_too():
    assert covariate_budget(100, 100, 0.20, 1000) > covariate_budget(100, 100, 0.10, 1000)


def test_an_empty_group_has_no_budget():
    assert covariate_budget(0, 50, 0.10, 1000) == 0


# --- spending the budget ---------------------------------------------------

def test_an_attribute_is_coarsened_before_it_is_dropped():
    """Dropping leaves the composition unprotected while the money
    criterion pushes it around; one column still controls the big level."""
    inns, grouping, financial = _population(60, levels=8)
    allowance, dropped = choose_covariates(inns, grouping, financial, [], budget=3)
    assert dropped == [], "there was room for one column each"
    assert allowance["wide"] == 1, "coarsened to its largest level vs the rest"


def test_every_attribute_gets_one_column_before_any_gets_two():
    inns, grouping, financial = _population(400, levels=8)
    allowance, _ = choose_covariates(inns, grouping, financial, [], budget=4)
    assert min(allowance.values()) >= 1
    assert sum(allowance.values()) <= 3, "one column is reserved for the money"


def test_leftover_budget_widens_the_most_predictive_attribute():
    inns = [f"{7000000000 + i}" for i in range(400)]
    # "wide" explains the money; "noise" cuts across it. (A multiplier
    # coprime to 6 would only relabel the same partition, not change it.)
    wide = {inn: f"w{i % 6}" for i, inn in enumerate(inns)}
    noise = {inn: f"n{(i // 3) % 6}" for i, inn in enumerate(inns)}
    money = {inn: 1000.0 * (i % 6) + i * 0.001 for i, inn in enumerate(inns)}
    allowance, _ = choose_covariates(
        inns, {"wide": wide, "noise": noise}, {"chod": money}, [], budget=8
    )
    assert allowance["wide"] > allowance["noise"]


def test_what_cannot_be_afforded_at_all_is_dropped_and_named():
    inns = [f"{7000000000 + i}" for i in range(60)]
    grouping = {f"attr{a}": {inn: f"v{(i + a) % 5}" for i, inn in enumerate(inns)}
                for a in range(6)}
    financial = {"chod": {inn: float(i) for i, inn in enumerate(inns)}}
    allowance, dropped = choose_covariates(inns, grouping, financial, [], budget=3)
    assert dropped, "six attributes cannot fit in three columns"
    assert set(allowance) | set(dropped) == set(grouping)


def test_strata_attributes_are_free():
    """Their composition is fixed by the strata, so they start balanced."""
    inns, grouping, financial = _population(100)
    allowance, dropped = choose_covariates(
        inns, grouping, financial, strata_keys=["narrow"], budget=2
    )
    assert allowance["narrow"] is None, "full resolution, uncharged"
    assert dropped == []


def test_coarsening_actually_narrows_the_design():
    inns, grouping, financial = _population(200, levels=8)
    full, names_full, _ = design_matrix(inns, grouping, financial)
    thin, names_thin, _ = design_matrix(inns, grouping, financial, None, {"wide": 1, "narrow": 1})
    assert len(thin) < len(full)
    assert sum(1 for n in names_thin if n.startswith("wide=")) == 1


def test_coarsening_keeps_the_largest_level():
    inns = [f"{i}" for i in range(100)]
    values = {inn: ("big" if i < 60 else f"small{i % 7}") for i, inn in enumerate(inns)}
    levels, _rare, _ref = dummy_levels(inns, values, max_columns=1)
    assert levels == ["big"] or _ref == "big"


def test_explained_share_sees_a_real_relationship():
    inns = [f"{i}" for i in range(60)]
    attribute = {inn: ("A" if i < 30 else "B") for i, inn in enumerate(inns)}
    related = {inn: (100.0 if i < 30 else 900.0) for i, inn in enumerate(inns)}
    unrelated = {inn: float(i % 3) for i, inn in enumerate(inns)}
    assert explained_share(related, attribute, inns) > 0.9
    assert explained_share(unrelated, attribute, inns) < 0.2


def test_the_split_reports_its_budget_and_what_it_gave_up():
    inns = [f"{7000000000 + i}" for i in range(60)]
    grouping = {f"attr{a}": {inn: f"v{(i + a) % 5}" for i, inn in enumerate(inns)}
                for a in range(6)}
    financial = {"chod": {inn: float(i * i) for i, inn in enumerate(inns)}}
    result = split(inns, grouping, financial, SplitConfig())
    assert result.covariate_budget > 0
    assert result.dropped_metrics
    assert any("бюджет ковариат" in w for w in result.warnings)


# --- matched pairs ---------------------------------------------------------

def test_a_short_list_is_paired_before_it_is_randomised():
    inns, grouping, financial = _population(80)
    result = split(inns, grouping, financial, SplitConfig())
    assert result.method == "matched_pairs"
    assert len(result.pairs) == 40
    assert not result.unmatched


def test_a_long_list_is_not_paired():
    inns, grouping, financial = _population(400)
    result = split(inns, grouping, financial, SplitConfig())
    assert result.method == "rerandomisation"
    assert result.pairs == []


def test_pairing_can_be_switched_off():
    inns, grouping, financial = _population(80)
    result = split(inns, grouping, financial, SplitConfig(pair_small_lists=False))
    assert result.pairs == []


def test_an_uneven_allocation_is_not_paired():
    """A pair splits one and one; 70/30 cannot be built out of pairs."""
    inns, grouping, financial = _population(80)
    result = split(inns, grouping, financial, SplitConfig(target_ratio=0.7))
    assert result.pairs == []


def test_an_odd_list_leaves_exactly_one_client_unpaired():
    inns, grouping, financial = _population(51)
    matrix, _, _ = design_matrix(inns, grouping, financial)
    pairing = pair_clients(inns, matrix, precision_matrix(matrix))
    assert len(pairing.pairs) == 25
    assert len(pairing.unmatched) == 1
    control, target = assign_pairs(pairing, seed=3)
    assert abs(len(target) - len(control)) <= 1
    assert sorted(control + target) == sorted(inns)


def test_an_odd_list_still_splits_within_one_client():
    inns, grouping, financial = _population(51)
    result = split(inns, grouping, financial, SplitConfig())
    assert abs(len(result.target) - len(result.control)) <= 1


def test_pairs_are_dropped_when_they_cannot_meet_the_bar():
    """The fallback: if the pairing cannot clear the acceptance bar and a
    free search can, the free search wins and no pairs are reported."""
    inns = [f"{7000000000 + i}" for i in range(60)]
    grouping = {f"attr{a}": {inn: f"v{(i + a) % 5}" for i, inn in enumerate(inns)}
                for a in range(4)}
    financial = {"chod": {inn: float(i ** 3) for i, inn in enumerate(inns)}}
    result = split(inns, grouping, financial, SplitConfig())
    assert (result.method == "matched_pairs") == bool(result.pairs)
    assert sorted(result.control + result.target) == sorted(inns)


def test_every_client_lands_in_exactly_one_group():
    inns, grouping, financial = _population(75)
    result = split(inns, grouping, financial, SplitConfig())
    assert sorted(result.control + result.target) == sorted(inns)


def test_partners_end_up_on_opposite_sides():
    inns, grouping, financial = _population(60)
    result = split(inns, grouping, financial, SplitConfig())
    target = set(result.target)
    for first, second in result.pairs:
        assert (first in target) != (second in target), (first, second)


def test_pairs_are_closer_than_random_partners():
    inns, grouping, financial = _population(100)
    matrix, _, _ = design_matrix(inns, grouping, financial)
    pairing = pair_clients(inns, matrix, precision_matrix(matrix))
    assert pairing.mean_distance < pairing.baseline_distance
    assert pairing.tightness < 0.6


def test_pairing_beats_rerandomisation_on_money_balance():
    """Measured, not assumed: the median over twenty populations."""
    plain, paired = [], []
    for seed in range(20):
        inns, grouping, financial = _population(100, seed=seed)
        for config, bucket in (
            (SplitConfig(pair_small_lists=False, random_seed=7), plain),
            (SplitConfig(pair_small_lists=True, random_seed=7), paired),
        ):
            result = split(inns, grouping, financial, config)
            values = financial["chod"]
            c = [values[i] for i in result.control]
            t = [values[i] for i in result.target]
            pooled = ((statistics.variance(c) + statistics.variance(t)) / 2) ** 0.5
            bucket.append(abs(statistics.mean(t) - statistics.mean(c)) / pooled)
    assert statistics.median(paired) < statistics.median(plain)


def test_the_pairing_is_reproducible_but_the_coin_flips_are_not_fixed():
    inns, grouping, financial = _population(60)
    matrix, _, _ = design_matrix(inns, grouping, financial)
    first = pair_clients(inns, matrix, precision_matrix(matrix))
    second = pair_clients(inns, matrix, precision_matrix(matrix))
    assert first.pairs == second.pairs, "pairs do not depend on the seed"
    a = assign_pairs(first, seed=1)
    b = assign_pairs(first, seed=2)
    assert sorted(a[0]) != sorted(b[0]), "but the assignment inside them does"


def test_a_pairing_too_loose_to_be_worth_it_says_so():
    loose = Pairing(
        pairs=[("a", "b")], mean_distance=3.8, worst_distance=4.0, baseline_distance=4.0
    )
    assert loose.quality_warning() is not None
    tight = Pairing(
        pairs=[("a", "b")], mean_distance=0.4, worst_distance=0.5, baseline_distance=4.0
    )
    assert tight.quality_warning() is None


def test_identical_clients_pair_perfectly_without_dividing_by_zero():
    inns = [f"{i}" for i in range(20)]
    grouping = {"same": {inn: "X" for inn in inns}}
    financial = {"chod": {inn: 100.0 for inn in inns}}
    result = split(inns, grouping, financial, SplitConfig())
    assert len(result.control) == len(result.target) == 10


def test_two_clients_are_a_single_pair():
    inns = ["7000000001", "7000000002"]
    result = split(
        inns, {"opf": {inns[0]: "ЮЛ", inns[1]: "ИП"}},
        {"chod": {inns[0]: 10.0, inns[1]: 20.0}}, SplitConfig(),
    )
    assert len(result.control) == len(result.target) == 1


# --- the paired analysis ---------------------------------------------------

def test_the_pairs_reach_the_analysis(scratch_config, tmp_path):
    """Without them in pilot_meta.json the paired test cannot be run later."""
    import json

    from skill.connectors.email_connector import LoggingEmailConnector
    from skill.models import PilotRequest
    from skill.pipeline import run_intake

    request = PilotRequest(
        pilot_name="paired", valid_from=date.today(),
        valid_to=date.today() + timedelta(days=200),
        submitter_email="a@b.cc", submitter_full_name="N", recipient_emails=[],
        analyst_email="c@d.ee", expected_effect_pct=300.0,
        recalculation_frequency="month", grouping_metrics=["opf"],
        financial_effect_articles=["chod"],
    )
    result = run_intake(
        request, ROOT / "sample_data" / "sample_inn_input.csv", config=scratch_config,
        email_connector=LoggingEmailConnector(tmp_path / "mail"),
    )
    meta = json.loads((Path(result.pilot_folder) / "pilot_meta.json").read_text(encoding="utf-8"))
    assert meta["assignment"] == "matched_pairs"
    assert len(meta["pairs"]) == len(result.split.pairs) > 0


def test_a_broken_pair_is_excluded_not_half_counted():
    from skill.analysis import _paired_analysis

    deltas = {"a": 10.0, "b": 1.0, "c": 12.0, "d": 2.0, "e": 9.0}
    groups = {"a": "tg", "b": "cg", "c": "tg", "d": "cg", "e": "tg"}
    pairs = [["a", "b"], ["c", "d"], ["e", "gone"]]
    paired, sign_p, used, broken = _paired_analysis(pairs, deltas, groups)
    assert used == 2
    assert broken == 1
    assert paired.mean == pytest.approx(9.5)
    assert sign_p is not None


def test_two_clients_from_the_same_group_are_not_a_pair():
    """After a rebase the stored pairs may no longer straddle the groups."""
    from skill.analysis import _paired_analysis

    deltas = {"a": 10.0, "b": 1.0}
    groups = {"a": "tg", "b": "tg"}
    paired, _sign, used, broken = _paired_analysis([["a", "b"]], deltas, groups)
    assert used == 0 and broken == 1 and paired is None
