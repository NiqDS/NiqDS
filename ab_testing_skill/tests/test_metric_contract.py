"""The metric contract: flat, monthly, and the three generations of script."""
from datetime import date

import pytest

from skill.config import default_config
from skill.metrics.runner import MetricRunner, MetricSeries


def _runner(tmp_path, scripts: dict[str, str], manifest: list[dict]):
    import json

    folder = tmp_path / "bank"
    folder.mkdir(exist_ok=True)
    (folder / "__init__.py").write_text("", encoding="utf-8")
    for name, body in scripts.items():
        (folder / name).write_text(body, encoding="utf-8")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    config = default_config().metrics
    config.scripts_dir = folder
    config.manifest_path = path
    return MetricRunner(config)


def _entry(code, script, value_type="numeric"):
    return {"code": code, "label": code, "description": "", "value_type": value_type,
            "usable_as": ["financial_effect"], "script": script}


MONTHS = ["2026-01", "2026-02", "2026-03"]


# --- MetricSeries ----------------------------------------------------------

def test_a_flat_answer_is_carried_without_inventing_a_history():
    series = MetricSeries.from_script_output("chod", {"111": 100.0}, MONTHS)
    assert series.is_flat is True
    assert series.scalar() == {"111": 100.0}
    assert series.matrix() == {"111": [100.0, 100.0, 100.0]}


def test_a_monthly_answer_keeps_its_shape():
    raw = {"111": {"2026-01": 10.0, "2026-02": 20.0, "2026-03": 30.0}}
    series = MetricSeries.from_script_output("chod", raw, MONTHS)
    assert series.is_flat is False
    assert series.scalar() == {"111": 20.0}       # the window mean
    assert series.matrix()["111"] == [10.0, 20.0, 30.0]


def test_absent_is_not_zero():
    """A client the mart never returned and a client who earned nothing are
    different facts; collapsing both to None made a data-supply problem
    look like a business one."""
    raw = {"present": {"2026-01": 0.0}, "absent": None}
    series = MetricSeries.from_script_output("chod", raw, MONTHS)
    assert series.present() == {"present"}
    assert series.scalar()["present"] == 0.0
    assert "absent" not in series.scalar()


def test_a_month_with_no_row_is_none_in_the_matrix_not_zero():
    raw = {"111": {"2026-01": 10.0, "2026-03": 30.0}}
    series = MetricSeries.from_script_output("chod", raw, MONTHS)
    assert series.matrix()["111"] == [10.0, None, 30.0]


def test_months_outside_the_window_are_dropped():
    raw = {"111": {"2025-12": 1.0, "2026-01": 10.0}}
    series = MetricSeries.from_script_output("chod", raw, MONTHS)
    assert series.matrix()["111"] == [10.0, None, None]


def test_a_categorical_answer_takes_the_latest_value_not_a_mean():
    raw = {"111": {"2026-01": "G", "2026-03": "F"}}
    series = MetricSeries.from_script_output("okved", raw, MONTHS)
    assert series.scalar()["111"] == "F"


def test_a_script_returning_the_wrong_type_is_refused():
    with pytest.raises(TypeError) as exc_info:
        MetricSeries.from_script_output("chod", [1, 2, 3], MONTHS)
    assert "expected a dict" in str(exc_info.value)


# --- the three generations of script ---------------------------------------

LEGACY = "def run(inn_list, as_of_date, spark=None):\n    return {i: 1.0 for i in inn_list}\n"
FILTERED = ("def run(inn_list, as_of_date, spark=None, filters=None):\n"
            "    return {i: (2.0 if filters else 1.0) for i in inn_list}\n")
WINDOWED = ("def run(inn_list, as_of_date, spark=None, filters=None, months=None):\n"
            "    return {i: {m: float(n + 1) for n, m in enumerate(months or [])} for i in inn_list}\n")


def test_one_bank_can_hold_all_three_generations(tmp_path):
    runner = _runner(
        tmp_path,
        {"legacy.py": LEGACY, "filtered.py": FILTERED, "windowed.py": WINDOWED},
        [_entry("legacy", "legacy.py"), _entry("filtered", "filtered.py"),
         _entry("windowed", "windowed.py")],
    )
    assert runner.run("legacy", ["1"], date.today()) == {"1": 1.0}
    assert runner.run("filtered", ["1"], date.today()) == {"1": 1.0}
    windowed = runner.run_series("windowed", ["1"], date.today(), months=MONTHS)
    assert windowed.matrix()["1"] == [1.0, 2.0, 3.0]


def test_a_window_asked_of_a_script_that_cannot_take_one_is_not_faked(tmp_path):
    """A one-month answer presented as a six-month window looks valid and is
    wrong, so the flat answer is marked flat instead."""
    runner = _runner(tmp_path, {"legacy.py": LEGACY}, [_entry("legacy", "legacy.py")])
    series = runner.run_series("legacy", ["1"], date.today(), months=MONTHS)
    assert series.is_flat is True


def test_filters_asked_of_a_script_that_cannot_apply_them_is_an_error(tmp_path):
    runner = _runner(tmp_path, {"legacy.py": LEGACY}, [_entry("legacy", "legacy.py")])
    with pytest.raises(TypeError) as exc_info:
        runner.run("legacy", ["1"], date.today(), filters={"segment": "ММБ"})
    assert "silently return the wrong numbers" in str(exc_info.value)


def test_the_scalar_view_is_the_window_mean(tmp_path):
    runner = _runner(tmp_path, {"windowed.py": WINDOWED}, [_entry("windowed", "windowed.py")])
    assert runner.run("windowed", ["1"], date.today()) == {"1": 1.0}   # one-month default


def test_the_bundled_bank_is_calendar_anchored():
    """The same month must give the same number however it is asked for,
    or a per-period recalculation reads a different series each time."""
    runner = MetricRunner(default_config().metrics)
    inn = ["8319323530"]
    window = runner.run_series("chod", inn, date(2026, 6, 1),
                               months=["2026-04", "2026-05", "2026-06"])
    single = runner.run_series("chod", inn, date(2026, 5, 1), months=["2026-05"])
    assert window.by_month[inn[0]]["2026-05"] == single.by_month[inn[0]]["2026-05"]


def test_the_bundled_bank_produces_more_than_one_shape():
    """Cohorts need something to separate."""
    from skill.features import cohorts_for
    from skill.inn_utils import validate_file
    from pathlib import Path

    runner = MetricRunner(default_config().metrics)
    inns = validate_file(
        Path(__file__).resolve().parent.parent / "sample_data" / "sample_inn_input.csv"
    ).valid_inns
    months = [f"2026-{m:02d}" for m in range(1, 7)]
    series = runner.run_series("chod", inns, date(2026, 7, 1), months=months)
    assert len(set(cohorts_for(series.matrix()).values())) >= 2
