"""One test per defect raised in the external MVP audit.

Each test reproduces the auditor's own scenario as closely as the public
API allows and asserts the corrected behaviour, so a future refactor that
reintroduces the defect fails here with the defect's own ID in the name.
Defect IDs (Д1..Д16) match the audit report.
"""
from datetime import date, timedelta
from pathlib import Path

import pytest

from skill.config import default_config
from skill.connectors.email_connector import LoggingEmailConnector, OutgoingEmail
from skill.exporter import read_rows, resolve_export_path, write_financial_effect_file, write_group_file
from skill.inn_utils import validate_inn
from skill.models import PilotRequest
from skill.monitoring import AlreadyCalculatedError, RecalculationNotDueError, run_recalculation
from skill.pipeline import PilotAlreadyExistsError, run_intake
from skill.registries import (
    DuplicatesRegistry,
    InvolvedInnRecord,
    InvolvedInnsRegistry,
    OverlapRegistry,
    check_and_register,
)
from skill.splitter import _balance_report
from skill.validation import RequestValidationError

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_INN_FILE = ROOT / "sample_data" / "sample_inn_input.csv"


def _request(**overrides):
    defaults = dict(
        pilot_name="regression_pilot",
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
    defaults.update(overrides)
    return PilotRequest(**defaults)


# --- Д1: negative means made every split look balanced ----------------------

def test_d1_negative_control_mean_no_longer_passes_the_balance_check():
    """Auditor's case: ЧОД negative in CG, hugely different in TG.

    The old `abs(c_mean - t_mean) / c_mean` put abs() in the numerator only,
    so a negative control mean produced a negative ratio that satisfied
    `<= 0.1` no matter how far apart the groups were.
    """
    control = ["c1", "c2", "c3", "c4"]
    target = ["t1", "t2", "t3", "t4"]
    values = {
        "chod": {
            "c1": -100.0, "c2": -110.0, "c3": -90.0, "c4": -100.0,
            "t1": 800.0, "t2": 820.0, "t3": 780.0, "t4": 800.0,
        }
    }
    report = _balance_report(control, target, values, max_standardized_diff=0.10)
    assert report["chod"]["control_mean"] < 0
    assert report["chod"]["smd"] > 0.10
    assert report["chod"]["balanced"] == 0.0


def test_d1_genuinely_similar_groups_still_pass():
    control = ["c1", "c2", "c3", "c4"]
    target = ["t1", "t2", "t3", "t4"]
    values = {
        "chod": {
            "c1": -100.0, "c2": -110.0, "c3": -90.0, "c4": -100.0,
            "t1": -101.0, "t2": -109.0, "t3": -91.0, "t4": -99.0,
        }
    }
    report = _balance_report(control, target, values, max_standardized_diff=0.10)
    assert report["chod"]["balanced"] == 1.0


# --- Д2: a scheduler firing early duplicated the whole block ----------------

def test_d2_same_day_recalculation_does_not_duplicate_rows(scratch_config, tmp_path):
    result = run_intake(
        _request(pilot_name="d2_pilot"),
        SAMPLE_INN_FILE,
        config=scratch_config,
        email_connector=LoggingEmailConnector(tmp_path / "outbox"),
    )
    folder = Path(result.pilot_folder)
    path = resolve_export_path(folder / "financial_effect")
    _, rows_after_intake = read_rows(path)

    # the auditor ran the recalculation three times in one day and got the
    # same block appended each time (50 rows -> 200)
    for _ in range(3):
        with pytest.raises((AlreadyCalculatedError, RecalculationNotDueError)):
            run_recalculation(folder, config=scratch_config)

    _, rows_now = read_rows(path)
    assert len(rows_now) == len(rows_after_intake)


def test_d2_force_still_allows_a_deliberate_recalculation(scratch_config, tmp_path):
    result = run_intake(
        _request(pilot_name="d2_force_pilot"),
        SAMPLE_INN_FILE,
        config=scratch_config,
        email_connector=LoggingEmailConnector(tmp_path / "outbox"),
    )
    run_recalculation(Path(result.pilot_folder), config=scratch_config, force=True)


# --- Д3: re-running an existing pilot silently overwrote it ----------------

def test_d3_rerunning_the_same_pilot_name_is_refused(scratch_config, tmp_path):
    run_intake(
        _request(pilot_name="d3_pilot"),
        SAMPLE_INN_FILE,
        config=scratch_config,
        email_connector=LoggingEmailConnector(tmp_path / "outbox"),
    )
    with pytest.raises(PilotAlreadyExistsError):
        run_intake(
            _request(pilot_name="d3_pilot"),
            SAMPLE_INN_FILE,
            config=scratch_config,
            email_connector=LoggingEmailConnector(tmp_path / "outbox2"),
        )


# --- Д4: an empty metric selection produced an unusable pilot --------------

def test_d4_request_without_metrics_is_rejected_before_any_side_effect(scratch_config, tmp_path):
    with pytest.raises(RequestValidationError) as exc_info:
        run_intake(
            _request(pilot_name="d4_pilot", grouping_metrics=[], financial_effect_articles=[]),
            SAMPLE_INN_FILE,
            config=scratch_config,
            email_connector=LoggingEmailConnector(tmp_path / "outbox"),
        )
    assert exc_info.value.issues
    # nothing was written and nobody was emailed
    assert not (scratch_config.storage.pilots_root / "d4_pilot").exists()
    assert not scratch_config.registry.involved_inns_path.exists()


# --- Д9: a pilot starting next year blocked candidates today ---------------

def test_d9_membership_starting_in_the_future_does_not_block_a_pilot_today(tmp_path):
    involved = InvolvedInnsRegistry(tmp_path / "involved.csv")
    duplicates = DuplicatesRegistry(tmp_path / "dup.csv")
    overlap = OverlapRegistry(tmp_path / "overlap.csv")

    future_start = date.today() + timedelta(days=180)
    involved.append(InvolvedInnRecord(
        no=0, inn="2222222222", role="tg", pilot_name="next_year_pilot",
        valid_from=future_start.isoformat(),
        valid_to=(future_start + timedelta(days=90)).isoformat(),
        email_submitter="someone@bank.internal", report_date=date.today().isoformat(),
    ))

    available, blocked = check_and_register(
        ["2222222222"],
        _request(valid_from=date.today(), valid_to=date.today() + timedelta(days=30)),
        involved, duplicates, overlap,
        blocking_roles=("tg",), require_metric_overlap=True,
    )
    assert available == ["2222222222"]
    assert blocked == []


# --- Д10: the web form re-encoded cp1251 uploads through UTF-8 -------------

def test_d10_web_form_hands_over_the_uploaded_bytes_unchanged():
    """The generated form must not round-trip the ID file through a string.

    Reading a cp1251 CSV with `readAsText(file, 'utf-8')` and re-downloading
    the decoded string replaced every Cyrillic byte with U+FFFD, so the
    `ИНН` header no longer matched and the agent rejected the whole file.
    """
    for name in ("index.html", "_template.html"):
        source = (ROOT / "web" / name).read_text(encoding="utf-8")
        assert "readAsArrayBuffer" in source
        assert "windows-1251" in source, "cp1251 fallback missing from the preview decoder"
        assert "readAsText" not in source


# --- Д11: Excel dropped leading zeros from INNs ----------------------------

def test_d11_length_error_explains_the_dropped_leading_zero():
    issue = validate_inn("790112872")  # 9 digits: 0790112872 with the zero eaten
    assert issue is not None
    assert "Excel" in issue.reason and "0790112872" in issue.reason


def test_d11_numeric_excel_cell_missing_its_leading_zero_is_recovered(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from skill.inn_utils import validate_file

    padded = "0790112872"
    assert validate_inn(padded) is None, "fixture INN must be a valid one"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["inn"])
    ws.append([int(padded)])  # exactly what Excel stores for an all-digit cell
    path = tmp_path / "inns.xlsx"
    wb.save(path)

    result = validate_file(path)
    assert result.valid_inns == [padded]
    assert result.issues == []


def test_d11_exported_codes_column_is_text_formatted(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = write_group_file(tmp_path, "control_group", ["0790112872", "2222222222"])
    if path.suffix != ".xlsx":
        pytest.skip("csv fallback in use")
    ws = openpyxl.load_workbook(path).active
    assert [c.number_format for (c,) in ws.iter_rows(min_row=2, min_col=1, max_col=1)] == ["@", "@"]


# --- Д12: registries were written into the checked-in sample_data/ ---------

def test_d12_default_registry_paths_are_outside_sample_data():
    cfg = default_config()
    for path in (
        cfg.registry.involved_inns_path,
        cfg.registry.duplicates_path,
        cfg.registry.overlap_path,
        cfg.registry.metric_requests_path,
        cfg.master_status.path,
    ):
        assert "sample_data" not in path.parts, f"{path} would overwrite bundled reference data"


# --- Д13: a crafted ID ran as a formula when the export was opened --------

def test_d13_formula_like_values_are_neutralised_and_round_trip(tmp_path):
    payload = '=cmd|\'/c calc\'!A1'
    path = write_group_file(tmp_path, "control_group", [payload, "2222222222"])

    header, rows = read_rows(path)
    assert header == ["codes"]
    # escaped on disk...
    raw = path.read_bytes()
    assert b"'=cmd" in raw or payload.encode() not in raw
    # ...and unescaped again on read, so append mode stays lossless
    assert [row[0] for row in rows] == [payload, "2222222222"]


def test_d13_ordinary_values_are_untouched(tmp_path):
    values = {"chod": {"1111111111": -250.5}}
    path = write_financial_effect_file(
        tmp_path, date(2026, 1, 1), values, {"1111111111": "cg"}, mode="append"
    )
    _, rows = read_rows(path)
    assert rows[0][1] == "1111111111"
    assert float(rows[0][3]) == -250.5


# --- Д14: a pilot could end up with both a .csv and an .xlsx export --------

def test_d14_an_existing_export_keeps_its_extension(tmp_path):
    (tmp_path / "financial_effect.csv").write_text("report_date,codes\n", encoding="utf-8")
    assert resolve_export_path(tmp_path / "financial_effect").suffix == ".csv"


# --- Д15: nothing said how complete the metric data actually was ----------

def test_d15_intake_reports_per_metric_coverage(scratch_config, tmp_path):
    outbox = LoggingEmailConnector(tmp_path / "outbox")
    result = run_intake(
        _request(pilot_name="d15_pilot", grouping_metrics=["okved"], financial_effect_articles=["chod"]),
        SAMPLE_INN_FILE,
        config=scratch_config,
        email_connector=outbox,
    )
    candidate_count = len(result.split.control) + len(result.split.target)
    assert set(result.coverage) == {"okved", "chod"}
    for filled in result.coverage.values():
        assert 0 <= filled <= candidate_count

    analytics = [e for e in outbox.sent if scratch_config.notify.analytics_team_email in e.to]
    assert "Заполненность" in analytics[0].body or "coverage" in analytics[0].body.lower()


# --- Д16: the second run overwrote the first run's outbox files ------------

def test_d16_two_runs_into_one_outbox_keep_both_messages(tmp_path):
    outbox_dir = tmp_path / "outbox"
    for _ in range(2):
        connector = LoggingEmailConnector(outbox_dir)
        connector.send(OutgoingEmail(to=["a@bank.internal"], subject="Пилот", body="x"))

    assert len(list(outbox_dir.glob("*.eml.txt"))) == 2
