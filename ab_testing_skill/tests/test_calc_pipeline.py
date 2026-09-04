import csv
from datetime import date
from pathlib import Path

import pytest
from openpyxl import Workbook

from skill.calc_pipeline import CalculationRejected, NoMetricsSelectedError, run_calculation
from skill.connectors.email_connector import LoggingEmailConnector
from skill.exporter import read_rows
from skill.models import CalculationRequest

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_IDS = ROOT / "sample_data" / "sample_inn_input.csv"


def _sample_inns(limit: int = 20) -> list[str]:
    with open(SAMPLE_IDS, newline="", encoding="utf-8") as f:
        return [row["inn"] for row in csv.DictReader(f)][:limit]


def _xlsx_of(ids: list[str], path: Path, extra_rows: list = ()) -> Path:
    """Writes IDs the way Excel really stores them -- as numbers, not text."""
    wb = Workbook()
    ws = wb.active
    ws.append(["inn"])
    for inn in ids:
        ws.append([int(inn)])
    for row in extra_rows:
        ws.append([row])
    wb.save(path)
    return path


def _request(**overrides) -> CalculationRequest:
    defaults = dict(
        request_name="calc_test",
        submitter_email="submitter@bank.internal",
        submitter_full_name="Submitter Name",
        metrics=["tb", "chod"],
        filters={},
        as_of_date=date(2026, 9, 4),
    )
    defaults.update(overrides)
    return CalculationRequest(**defaults)


@pytest.fixture
def calc_config(scratch_config, tmp_path):
    scratch_config.calculation.results_root = tmp_path / "calculations"
    return scratch_config


def test_calculation_from_xlsx_writes_row_per_id(calc_config, tmp_path):
    ids = _sample_inns()
    id_file = _xlsx_of(ids, tmp_path / "ids.xlsx")

    result = run_calculation(_request(), id_file, config=calc_config)

    assert result.id_count == len(ids)
    header, rows = read_rows(Path(result.result_file))
    assert header == ["report_date", "codes", "chod", "tb"]
    # every submitted ID keeps a row, even ones with no value for a metric
    assert len(rows) == len(ids)
    assert [str(r[1]) for r in rows] == ids
    assert all(r[0] == "2026-09-04" for r in rows)


def test_calculation_reports_coverage_per_metric(calc_config, tmp_path):
    ids = _sample_inns()
    id_file = _xlsx_of(ids, tmp_path / "ids.xlsx")

    result = run_calculation(_request(), id_file, config=calc_config)

    assert set(result.coverage) == {"tb", "chod"}
    assert all(0 <= filled <= len(ids) for filled in result.coverage.values())


def test_filters_reduce_coverage_rather_than_being_ignored(calc_config, tmp_path):
    ids = _sample_inns()
    id_file = _xlsx_of(ids, tmp_path / "ids.xlsx")

    unfiltered = run_calculation(_request(), id_file, config=calc_config)
    filtered = run_calculation(
        _request(request_name="calc_filtered", filters={"segment": "ММБ"}),
        id_file,
        config=calc_config,
    )
    assert filtered.coverage["chod"] < unfiltered.coverage["chod"]


def test_invalid_ids_rejected_unless_dropping_is_requested(calc_config, tmp_path):
    id_file = _xlsx_of(_sample_inns(5), tmp_path / "ids.xlsx", extra_rows=["НЕВЕРНЫЙ"])

    with pytest.raises(CalculationRejected) as exc_info:
        run_calculation(_request(), id_file, config=calc_config)
    assert len(exc_info.value.issues) == 1

    result = run_calculation(_request(), id_file, config=calc_config, drop_invalid_ids=True)
    assert result.id_count == 5
    assert len(result.rejected_ids) == 1


def test_csv_input_still_works(calc_config):
    result = run_calculation(_request(), SAMPLE_IDS, config=calc_config)
    assert result.id_count == 50


def test_no_metrics_selected_is_rejected(calc_config, tmp_path):
    id_file = _xlsx_of(_sample_inns(3), tmp_path / "ids.xlsx")
    with pytest.raises(NoMetricsSelectedError):
        run_calculation(_request(metrics=[]), id_file, config=calc_config)


def test_unknown_metric_is_rejected_before_running(calc_config, tmp_path):
    id_file = _xlsx_of(_sample_inns(3), tmp_path / "ids.xlsx")
    with pytest.raises(KeyError, match="unknown metric"):
        run_calculation(_request(metrics=["tb", "not_a_metric"]), id_file, config=calc_config)


def test_bad_filter_is_rejected_before_running(calc_config, tmp_path):
    id_file = _xlsx_of(_sample_inns(3), tmp_path / "ids.xlsx")
    with pytest.raises(ValueError, match="outside its allowed set"):
        run_calculation(
            _request(filters={"segment": "Гигант"}), id_file, config=calc_config
        )


def test_result_is_emailed_with_coverage_summary(calc_config, tmp_path):
    id_file = _xlsx_of(_sample_inns(5), tmp_path / "ids.xlsx")
    outbox = LoggingEmailConnector(tmp_path / "outbox")

    result = run_calculation(_request(), id_file, config=calc_config, email_connector=outbox)

    assert len(outbox.sent) == 1
    message = outbox.sent[0]
    assert message.to == ["submitter@bank.internal"]
    assert [a.name for a in message.attachments] == [Path(result.result_file).name]
    assert "Заполненность" in message.body


def test_calculation_does_not_touch_the_pilot_registries(calc_config, tmp_path):
    """A calculation is read-only: it must never mark IDs as used, or the
    next pilot would find them blocked."""
    id_file = _xlsx_of(_sample_inns(5), tmp_path / "ids.xlsx")
    run_calculation(_request(), id_file, config=calc_config)

    for path in (
        calc_config.registry.involved_inns_path,
        calc_config.master_status.path,
        calc_config.registry.duplicates_path,
    ):
        assert not Path(path).exists(), f"{path} should not be created by a calculation"
