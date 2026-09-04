from datetime import date

import pytest

from metric_scripts.filters import (
    filters_for_metric,
    get_filter,
    list_filters,
    validate_selection,
)
from skill.config import default_config
from skill.metrics.runner import MetricRunner, script_accepts_filters


def test_list_filters_excludes_comment_key():
    filters = list_filters()
    assert filters
    assert "_comment" not in filters
    for definition in filters.values():
        assert definition.label
        assert definition.type in ("categorical", "numeric", "date")


def test_get_filter_unknown_code_lists_known_ones():
    with pytest.raises(KeyError) as exc_info:
        get_filter("definitely_not_a_filter")
    assert "definitely_not_a_filter" in str(exc_info.value)


def test_filters_for_metric_respects_applies_to():
    # sub_segment is declared only for the financial metrics
    assert "sub_segment" in filters_for_metric("chod")
    assert "sub_segment" not in filters_for_metric("okved")
    # segment uses the "*" wildcard, so it applies everywhere
    assert "segment" in filters_for_metric("okved")


def test_validate_selection_rejects_unknown_filter():
    with pytest.raises(KeyError):
        validate_selection({"nope": "x"}, ["chod"])


def test_validate_selection_rejects_value_outside_allowed_set():
    with pytest.raises(ValueError, match="outside its allowed set"):
        validate_selection({"segment": "Гигант"}, ["chod"])


def test_validate_selection_rejects_non_numeric_for_numeric_filter():
    with pytest.raises(ValueError, match="expects a number"):
        validate_selection({"reporting_year": "2026"}, ["chod"])


def test_validate_selection_rejects_filter_irrelevant_to_chosen_metrics():
    with pytest.raises(ValueError, match="does not apply"):
        validate_selection({"sub_segment": "Микро"}, ["okved"])


def test_validate_selection_accepts_a_good_selection():
    validate_selection({"segment": "ММБ", "sub_segment": ["Микро", "Малые"]}, ["chod", "okved"])


def test_runner_narrows_filters_per_metric():
    runner = MetricRunner(default_config().metrics)
    selection = {"segment": "ММБ", "sub_segment": "Микро"}
    assert runner.filters_for("okved", selection) == {"segment": "ММБ"}
    assert runner.filters_for("chod", selection) == selection
    assert runner.filters_for("chod", None) is None


def test_bundled_scripts_accept_filters_and_apply_them():
    runner = MetricRunner(default_config().metrics)
    module = runner._import_script("chod.py")
    assert script_accepts_filters(module.run)

    # a filter that excludes everything must zero out the results rather than
    # being ignored -- silently unfiltered numbers are the failure mode here
    inns = ["8319323530", "1346564387", "3319561976"]
    unfiltered = runner.run("chod", inns, date.today())
    excluded = runner.run("chod", inns, date.today(), filters={"segment": "Крупный", "sub_segment": "Средние"})
    assert any(v is not None for v in unfiltered.values())
    assert all(v is None for v in excluded.values())


def test_requesting_filters_a_script_cannot_apply_raises(tmp_path):
    """A script bank predating the filters argument must fail loudly rather
    than quietly returning unfiltered numbers."""
    scripts_dir = tmp_path / "legacy_bank"
    scripts_dir.mkdir()
    (scripts_dir / "__init__.py").write_text("", encoding="utf-8")
    (scripts_dir / "legacy.py").write_text(
        "def run(inn_list, as_of_date, spark=None):\n"
        "    return {inn: 1.0 for inn in inn_list}\n",
        encoding="utf-8",
    )
    (scripts_dir / "manifest.json").write_text(
        '[{"code": "legacy", "label": "Legacy", "description": "d",'
        ' "value_type": "numeric", "usable_as": ["grouping"], "script": "legacy.py"}]',
        encoding="utf-8",
    )

    config = default_config().metrics
    config.scripts_dir = scripts_dir
    config.manifest_path = scripts_dir / "manifest.json"
    runner = MetricRunner(config)

    # without filters the old signature still works
    assert runner.run("legacy", ["111"], date.today()) == {"111": 1.0}
    with pytest.raises(TypeError, match="does not accept a `filters` argument"):
        runner.run("legacy", ["111"], date.today(), filters={"segment": "ММБ"})
