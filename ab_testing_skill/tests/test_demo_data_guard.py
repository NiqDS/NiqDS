"""The demo-data-in-production guard.

Every script in `metric_scripts/` ships as a stub reading
`sample_data/attributes_reference.csv`. The pilot's strata and its entire
balance report are computed from whatever those return, so a production run
against an unported script produces a split over fabricated attributes and
an email saying the balance check PASSED. Two independent guards stop that;
these tests hold both of them shut.

Borrowed from the metrics-calculation fork's `fail_not_ported` /
`require_demo_mode`, which reached the same conclusion first: "тихие
демо-числа в боевой выгрузке хуже падения".
"""
from datetime import date
from pathlib import Path

import pytest

from metric_scripts._common import (
    DemoDataRequestedInProductionError,
    lookup_column,
    refuse_demo_reference_in_production,
)
from skill.config import default_config
from skill.metrics.runner import DemoDataInProductionError, MetricRunner

ROOT = Path(__file__).resolve().parent.parent
BUNDLED_STUBS = ("chod", "chep", "revenue", "sdo", "turnover", "okved", "opf", "tb", "tenure")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("AB_SKILL_USE_SPARK", raising=False)
    monkeypatch.delenv("AB_SKILL_ALLOW_DEMO_DATA", raising=False)


# --- the markers themselves ------------------------------------------------

@pytest.mark.parametrize("code", BUNDLED_STUBS)
def test_every_bundled_stub_declares_itself_a_stub(code):
    """Porting a script means deleting its DEMO_ONLY line. If a stub loses
    the marker without being ported, the runner's guard goes quiet."""
    runner = MetricRunner(default_config().metrics)
    module = runner._import_script(runner.manifest[code].script)
    assert getattr(module, "DEMO_ONLY", False) is True, (
        f"{code} reads the demo table but does not declare DEMO_ONLY"
    )


def test_a_script_that_does_not_read_the_demo_table_needs_no_marker():
    """The marker tracks demo data, not scripts in general -- filters.py and
    subscriptions.py are real code and must not be flagged."""
    for name in ("filters.py", "subscriptions.py"):
        text = (ROOT / "metric_scripts" / name).read_text(encoding="utf-8")
        assert "DEMO_ONLY" not in text
        assert "lookup_column" not in text


# --- net 1: the runner refuses to call a stub in production ---------------

def test_the_runner_refuses_a_stub_once_spark_is_on(monkeypatch):
    config = default_config().metrics
    monkeypatch.setattr(config, "use_spark", True)
    runner = MetricRunner(config)
    monkeypatch.setattr(
        "skill.metrics.runner.get_spark_session", lambda: object(), raising=True
    )
    with pytest.raises(DemoDataInProductionError) as exc_info:
        runner.run("chod", ["1111111111"], date.today())
    message = str(exc_info.value)
    assert "chod" in message
    assert "DEMO_ONLY" in message, "the message has to say how to fix it"
    assert "AB_SKILL_ALLOW_DEMO_DATA" in message, "and name the escape hatch"


def test_the_runner_still_runs_stubs_when_spark_is_off():
    """The demo path is how dry runs and this whole test suite work."""
    runner = MetricRunner(default_config().metrics)
    values = runner.run("chod", ["8319323530"], date.today())
    assert "8319323530" in values


def test_an_explicit_opt_in_allows_demo_numbers_with_spark_on(monkeypatch):
    config = default_config().metrics
    monkeypatch.setattr(config, "use_spark", True)
    monkeypatch.setenv("AB_SKILL_ALLOW_DEMO_DATA", "true")
    monkeypatch.setattr(
        "skill.metrics.runner.get_spark_session", lambda: object(), raising=True
    )
    runner = MetricRunner(config)
    assert runner.run("chod", ["8319323530"], date.today())


# --- net 2: reading the demo table refuses regardless of the marker ------

def test_reading_the_demo_table_refuses_in_production(monkeypatch):
    """Covers a new stub, or a half-ported script that still falls back to
    the demo table on some path -- the runner's marker check would miss it."""
    monkeypatch.setenv("AB_SKILL_USE_SPARK", "true")
    with pytest.raises(DemoDataRequestedInProductionError) as exc_info:
        lookup_column(["8319323530"], column="chod", cast=float)
    assert "attributes_reference.csv" in str(exc_info.value)


def test_the_two_guards_use_the_same_escape_hatch(monkeypatch):
    monkeypatch.setenv("AB_SKILL_USE_SPARK", "true")
    monkeypatch.setenv("AB_SKILL_ALLOW_DEMO_DATA", "true")
    refuse_demo_reference_in_production()  # must not raise
    assert lookup_column(["8319323530"], column="chod", cast=float)


@pytest.mark.parametrize("value", ["false", "", "0", "no", "TRUE_ISH"])
def test_only_a_literal_true_switches_production_mode_on(monkeypatch, value):
    """A typo in the env var must fail safe -- toward the demo path working,
    not toward production silently accepting demo numbers."""
    monkeypatch.setenv("AB_SKILL_USE_SPARK", value)
    refuse_demo_reference_in_production()


def test_production_mode_is_case_and_space_insensitive(monkeypatch):
    monkeypatch.setenv("AB_SKILL_USE_SPARK", "  TRUE ")
    with pytest.raises(DemoDataRequestedInProductionError):
        refuse_demo_reference_in_production()


# --- the realistic case: a half-ported script bank ------------------------

def test_a_partially_ported_bank_fails_on_the_unported_metric(monkeypatch, tmp_path):
    """The state a port is actually in: ЧОД is real, ОКВЭД is still demo.

    Without the guard the split runs on real money and fabricated industry
    codes, and nothing in the output says so.
    """
    # a distinct package name: `metric_scripts` is already imported from the
    # real bank, so a tmp dir of that name would not be importable
    scripts = tmp_path / "ported_bank"
    scripts.mkdir()
    (scripts / "__init__.py").write_text("", encoding="utf-8")
    # a ported metric: queries the mart, no marker
    (scripts / "chod_real.py").write_text(
        "def run(inn_list, as_of_date, spark=None, filters=None):\n"
        "    return {inn: 100.0 for inn in inn_list}\n",
        encoding="utf-8",
    )
    # an unported one: still the stub
    (scripts / "okved_stub.py").write_text(
        "DEMO_ONLY = True\n\n\n"
        "def run(inn_list, as_of_date, spark=None, filters=None):\n"
        "    return {inn: 'G' for inn in inn_list}\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '[{"code": "chod", "label": "x", "description": "d", "value_type": "money", '
        '"usable_as": ["financial_effect"], "script": "chod_real.py"},'
        '{"code": "okved", "label": "y", "description": "d", "value_type": "categorical", '
        '"usable_as": ["grouping"], "script": "okved_stub.py"}]',
        encoding="utf-8",
    )

    config = default_config().metrics
    monkeypatch.setattr(config, "scripts_dir", scripts)
    monkeypatch.setattr(config, "manifest_path", manifest)
    monkeypatch.setattr(config, "use_spark", True)
    monkeypatch.setattr(
        "skill.metrics.runner.get_spark_session", lambda: object(), raising=True
    )
    runner = MetricRunner(config)

    assert runner.run("chod", ["1111111111"], date.today()) == {"1111111111": 100.0}
    with pytest.raises(DemoDataInProductionError):
        runner.run("okved", ["1111111111"], date.today())


def test_run_intake_fails_loudly_rather_than_splitting_on_demo_data(
    scratch_config, tmp_path, monkeypatch
):
    """End to end: the whole pilot must stop, not produce a plausible split."""
    from datetime import timedelta

    from skill.connectors.email_connector import LoggingEmailConnector
    from skill.models import PilotRequest
    from skill.pipeline import run_intake

    monkeypatch.setattr(scratch_config.metrics, "use_spark", True)
    monkeypatch.setattr(
        "skill.metrics.runner.get_spark_session", lambda: object(), raising=True
    )
    request = PilotRequest(
        pilot_name="demo_guard_pilot",
        valid_from=date.today(),
        valid_to=date.today() + timedelta(days=90),
        submitter_email="submitter@bank.internal",
        submitter_full_name="Submitter Name",
        recipient_emails=[],
        analyst_email="analyst@bank.internal",
        expected_effect_pct=5.0,
        recalculation_frequency="month",
        grouping_metrics=["okved"],
        financial_effect_articles=["chod"],
    )
    with pytest.raises(DemoDataInProductionError):
        run_intake(
            request,
            ROOT / "sample_data" / "sample_inn_input.csv",
            config=scratch_config,
            email_connector=LoggingEmailConnector(tmp_path / "outbox"),
        )
