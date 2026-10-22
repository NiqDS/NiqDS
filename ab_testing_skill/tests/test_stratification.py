"""The singleton-stratum defect, found by comparing the splitter against the
ЧОД matching notebook's cohort design.

Stratifying on four categorical attributes over a few hundred clients
leaves most strata holding one client, and a stratum of one cannot be
split. The old allocation sent every such client to control.
"""
from datetime import date, timedelta
from pathlib import Path

import pytest

from skill.config import SplitConfig
from skill.inn_utils import validate_file
from skill.metrics.runner import MetricRunner
from skill.splitter import DegenerateSplitError, _assign, _build_strata, split, strata_warnings

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_INN_FILE = ROOT / "sample_data" / "sample_inn_input.csv"


def _sample_inns() -> list[str]:
    return validate_file(SAMPLE_INN_FILE).valid_inns


def _values(metrics: list[str], inns: list[str], config=None) -> dict:
    from skill.config import default_config

    runner = MetricRunner((config or default_config()).metrics)
    return runner.run_many(metrics, inns, date.today())


# --- the defect itself -----------------------------------------------------

def test_singleton_strata_no_longer_all_land_in_control():
    """`round(1 * 0.5)` is 0 in Python, so each one-client stratum used to
    send its client to control -- deterministically, not randomly."""
    strata = {(f"s{i}",): [f"inn{i}"] for i in range(40)}
    control, target = _assign(strata, target_ratio=0.5, seed=42)
    assert len(control) + len(target) == 40
    assert abs(len(target) / 40 - 0.5) <= 0.05, (
        f"40 singleton strata split {len(control)}/{len(target)}; "
        "the remainder must carry between strata"
    )


def test_the_realised_ratio_holds_for_any_mix_of_stratum_sizes():
    strata = {}
    strata.update({(f"one{i}",): [f"a{i}"] for i in range(25)})
    strata.update({(f"two{i}",): [f"b{i}_1", f"b{i}_2"] for i in range(10)})
    strata.update({(f"three{i}",): [f"c{i}_1", f"c{i}_2", f"c{i}_3"] for i in range(5)})
    total = 25 + 20 + 15
    control, target = _assign(strata, target_ratio=0.5, seed=1)
    assert len(control) + len(target) == total
    assert abs(len(target) / total - 0.5) <= 0.05


@pytest.mark.parametrize("ratio", [0.2, 0.3, 0.5, 0.7])
def test_a_non_half_ratio_is_also_honoured_over_singletons(ratio):
    strata = {(f"s{i}",): [f"inn{i}"] for i in range(100)}
    _, target = _assign(strata, target_ratio=ratio, seed=7)
    assert abs(len(target) / 100 - ratio) <= 0.05


def test_the_spec_four_attributes_no_longer_produce_a_lopsided_split():
    """The reproduction: the four grouping attributes the spec itself names,
    on the bundled 50-client sample, used to give КГ=47 / ЦГ=3."""
    inns = _sample_inns()
    grouping = _values(["okved", "opf", "tb", "tenure"], inns)
    financial = _values(["chod"], inns)
    result = split(inns, grouping, financial, SplitConfig())
    assert len(result.control) + len(result.target) == len(inns)
    share = len(result.target) / len(inns)
    assert 0.45 <= share <= 0.55, f"КГ={len(result.control)} / ЦГ={len(result.target)}"


def test_a_continuous_metric_is_refused_as_a_stratum_key():
    """Money metrics are offered as grouping options in the form, and a raw
    rouble value is unique per client -- which used to give 50 strata of 1
    and an empty target group, reported as PASSED.

    It is no longer a question of recovering from that: an attribute whose
    cells would hold fewer than `min_clients_per_stratum` never becomes a
    stratum key at all. It is balanced on as a covariate instead, which is
    what the rerandomisation criterion is for.
    """
    inns = _sample_inns()
    result = split(inns, _values(["chod"], inns), _values(["chod"], inns), SplitConfig())
    assert result.strata_metrics == [], "a per-client value cannot be a stratum key"
    assert result.covariate_only_metrics == ["chod"], "but it must still be balanced on"
    assert len(result.strata_summary) == 1
    assert len(result.control) == len(result.target) == len(inns) // 2
    assert result.balanced is True
    assert result.warnings == []


# --- the guards ------------------------------------------------------------

def test_only_as_many_attributes_are_stratified_on_as_the_list_can_carry():
    """Four attributes over 50 clients would be 47 cells, i.e. no freedom for
    the search. Only the coarsest that fit the budget become strata; the
    rest are balanced on as covariates."""
    inns = _sample_inns()
    result = split(
        inns, _values(["okved", "opf", "tb", "tenure"], inns), _values(["chod"], inns), SplitConfig()
    )
    assert result.strata_metrics, "something should still be matched exactly"
    assert result.covariate_only_metrics, "and the rest handed to the criterion"
    assert set(result.strata_metrics) | set(result.covariate_only_metrics) == {
        "okved", "opf", "tb", "tenure"
    }, "no attribute may be dropped entirely"
    cells = len(result.strata_summary)
    assert cells <= len(inns) // SplitConfig().min_clients_per_stratum
    assert len(result.control) + len(result.target) == len(inns)


def test_an_imbalance_the_search_cannot_fix_is_reported_not_hidden():
    """50 clients over a dozen covariates cannot reach 0.1 on all of them.
    Saying so is the point -- the old code returned the best of 25 draws in
    silence."""
    inns = _sample_inns()
    result = split(
        inns, _values(["okved", "opf", "tb", "tenure"], inns), _values(["chod"], inns), SplitConfig()
    )
    if not result.balanced:
        assert any("баланс не достигнут" in w for w in result.warnings)
        assert any("сокращайте набор признаков" in w for w in result.warnings)


def test_a_coarse_stratification_still_passes_cleanly():
    """The guard must not cry wolf: one coarse attribute is a healthy split."""
    inns = _sample_inns()
    result = split(inns, _values(["okved"], inns), _values(["chod"], inns), SplitConfig())
    assert result.warnings == []
    assert result.balanced is True


def test_an_empty_group_is_refused_rather_than_returned():
    with pytest.raises(DegenerateSplitError) as exc_info:
        split(["1", "2", "3"], {}, {}, SplitConfig(target_ratio=0.0))
    assert "ЦГ=0" in str(exc_info.value)
    assert "grouping attributes" in str(exc_info.value)


def test_a_lopsided_ratio_is_flagged_even_without_singletons():
    warnings = strata_warnings(
        strata={("a",): ["1", "2"], ("b",): ["3", "4"]},
        candidate_count=4, control_n=3, target_n=1,
        target_ratio=0.5, max_ratio_deviation=0.05,
    )
    assert any("фактическая доля ЦГ" in w for w in warnings)


def test_reshuffling_can_actually_change_a_singleton_heavy_split():
    """Before, shuffling a one-element list was a no-op, so all 25 reshuffle
    attempts returned the identical split -- the retry loop could not help.
    Shuffling the stratum order makes the seed matter again."""
    strata = {(f"s{i}",): [f"inn{i}"] for i in range(30)}
    first = set(_assign(strata, 0.5, seed=1)[1])
    second = set(_assign(strata, 0.5, seed=2)[1])
    assert first != second


# --- it has to reach the people who get the files -------------------------

def test_the_warning_reaches_the_delivery_email(scratch_config, tmp_path):
    from skill.connectors.email_connector import LoggingEmailConnector
    from skill.models import PilotRequest
    from skill.pipeline import run_intake

    outbox = LoggingEmailConnector(tmp_path / "outbox")
    request = PilotRequest(
        pilot_name="singleton_pilot",
        valid_from=date.today(),
        valid_to=date.today() + timedelta(days=90),
        submitter_email="submitter@bank.internal",
        submitter_full_name="Submitter Name",
        recipient_emails=[],
        analyst_email="analyst@bank.internal",
        expected_effect_pct=5.0,
        recalculation_frequency="month",
        grouping_metrics=["okved", "opf", "tb", "tenure"],
        financial_effect_articles=["chod"],
    )
    result = run_intake(
        request, SAMPLE_INN_FILE, config=scratch_config, email_connector=outbox
    )
    assert result.split.warnings

    delivery = [e for e in outbox.sent if "Control/Target groups ready" in e.subject][0]
    assert "ВНИМАНИЕ по составу групп" in delivery.body

    package = [e for e in outbox.sent if "analytics package" in e.subject][0]
    assert "singletons:" in package.body
