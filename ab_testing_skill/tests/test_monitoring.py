from datetime import date, timedelta
from pathlib import Path

import pytest

from skill.exporter import read_rows
from skill.models import PilotRequest
from skill.monitoring import is_due, run_recalculation
from skill.pipeline import run_intake

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_INN_FILE = ROOT / "sample_data" / "sample_inn_input.csv"


def _make_pilot(scratch_config):
    request = PilotRequest(
        pilot_name="monitoring_pilot",
        valid_from=date.today() - timedelta(days=1),
        valid_to=date.today() + timedelta(days=90),
        submitter_email="submitter@bank.internal",
        submitter_full_name="Submitter Name",
        recipient_emails=[],
        analyst_email="analyst@bank.internal",
        expected_effect_pct=5.0,
        recalculation_frequency="week",
        grouping_metrics=["okved"],
        financial_effect_articles=["chod", "revenue"],
    )
    return run_intake(request, SAMPLE_INN_FILE, config=scratch_config)


def test_recalculation_appends_new_report_date(scratch_config):
    result = _make_pilot(scratch_config)
    pilot_folder = Path(result.pilot_folder)

    _, rows_after_first = read_rows(Path(result.financial_effect_file))
    n_clients = len(rows_after_first)

    run_recalculation(pilot_folder, config=scratch_config, as_of_date=date.today() + timedelta(days=8))
    header, rows_after_second = read_rows(Path(result.financial_effect_file))

    assert header == ["report_date", "codes", "group", "chod", "revenue", "stat_significance"]
    assert len(rows_after_second) == n_clients * 2


def test_is_due_reflects_configured_frequency(scratch_config):
    result = _make_pilot(scratch_config)
    pilot_folder = Path(result.pilot_folder)

    assert is_due(pilot_folder, as_of_date=date.today()) is False
    assert is_due(pilot_folder, as_of_date=date.today() + timedelta(days=7)) is True


def test_recalculation_rejects_dates_outside_pilot_window(scratch_config):
    result = _make_pilot(scratch_config)
    pilot_folder = Path(result.pilot_folder)
    with pytest.raises(ValueError):
        run_recalculation(pilot_folder, config=scratch_config, as_of_date=date.today() + timedelta(days=365))
