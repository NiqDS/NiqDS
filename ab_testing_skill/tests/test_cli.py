import csv
import json
from datetime import date, timedelta
from pathlib import Path

import skill.cli as cli
from skill.cli import _drop_invalid_inns

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_INN_FILE = ROOT / "sample_data" / "sample_inn_input.csv"


def _write_request_json(path: Path, **overrides) -> Path:
    data = {
        "pilot_name": "cli_test_pilot",
        "valid_from": date.today().isoformat(),
        "valid_to": (date.today() + timedelta(days=90)).isoformat(),
        "submitter_email": "submitter@bank.internal",
        "submitter_full_name": "Submitter Name",
        "recipient_emails": [],
        "analyst_email": "analyst@bank.internal",
        "expected_effect_pct": 5.0,
        "recalculation_frequency": "month",
        "grouping_metrics": [],
        "financial_effect_articles": [],
        "custom_metric_requests": [],
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _write_inn_file_with_bad_rows(path: Path) -> None:
    rows = SAMPLE_INN_FILE.read_text(encoding="utf-8").splitlines()
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
        writer = csv.writer(f)
        writer.writerow(["12345"])  # wrong length
        writer.writerow(["ABCDEFGHIJ"])  # non-digit
        writer.writerow(["1234567890"])  # fails FNS checksum


def test_drop_invalid_inns_writes_cleaned_file_and_reports_issues(tmp_path):
    inn_file = tmp_path / "inns.csv"
    _write_inn_file_with_bad_rows(inn_file)

    cleaned_path, result = _drop_invalid_inns(inn_file)

    assert cleaned_path == tmp_path / "inns_cleaned.csv"
    assert cleaned_path.exists()
    assert len(result.issues) == 3
    assert len(result.valid_inns) == 50

    cleaned_rows = cleaned_path.read_text(encoding="utf-8").splitlines()
    assert cleaned_rows[0] == "inn"
    assert len(cleaned_rows) == 51  # header + 50 valid INNs
    assert "12345" not in cleaned_rows
    assert "ABCDEFGHIJ" not in cleaned_rows
    assert "1234567890" not in cleaned_rows


def test_cmd_run_without_flag_still_rejects_on_invalid_inns(scratch_config, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "default_config", lambda: scratch_config)
    inn_file = tmp_path / "inns.csv"
    _write_inn_file_with_bad_rows(inn_file)
    request_path = _write_request_json(tmp_path / "request.json")

    rc = cli.main(["run", "--request", str(request_path), "--inn-file", str(inn_file)])

    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "rejected"
    assert len(out["issues"]) == 3


def test_cmd_run_with_drop_invalid_inns_flag_completes_the_split(scratch_config, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "default_config", lambda: scratch_config)
    inn_file = tmp_path / "inns.csv"
    _write_inn_file_with_bad_rows(inn_file)
    request_path = _write_request_json(tmp_path / "request.json")

    rc = cli.main(
        ["run", "--request", str(request_path), "--inn-file", str(inn_file), "--drop-invalid-inns"]
    )

    assert rc == 0
    stdout = capsys.readouterr().out
    # two JSON documents get printed back to back: the drop report, then the run result
    docs = []
    decoder = json.JSONDecoder()
    idx = 0
    text = stdout.strip()
    while idx < len(text):
        obj, end = decoder.raw_decode(text, idx)
        docs.append(obj)
        idx = end
        while idx < len(text) and text[idx].isspace():
            idx += 1
    assert docs[0]["status"] == "invalid_inns_dropped"
    assert docs[0]["dropped_count"] == 3
    assert docs[0]["remaining_count"] == 50
    assert docs[1]["status"] == "ok"
    split = docs[1]["result"]["split"]
    assert len(split["control"]) + len(split["target"]) == 50


def test_cmd_run_drop_invalid_inns_with_nothing_left_reports_clearly(
    scratch_config, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "default_config", lambda: scratch_config)
    inn_file = tmp_path / "all_bad.csv"
    inn_file.write_text("inn\n12345\nABCDEFGHIJ\n", encoding="utf-8")
    request_path = _write_request_json(tmp_path / "request.json")

    rc = cli.main(
        ["run", "--request", str(request_path), "--inn-file", str(inn_file), "--drop-invalid-inns"]
    )

    assert rc == 1
    stdout = capsys.readouterr().out
    assert "no_valid_inns_remaining" in stdout
