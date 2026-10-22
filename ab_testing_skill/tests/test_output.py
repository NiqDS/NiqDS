"""`--output text`: the same payloads, rendered for a person or an agent.

The JSON path is the CLI's contract, so the first thing these tests pin
down is that adding text rendering did not change it.
"""
import io
import json
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path

import pytest

import skill.cli as cli
from skill import output

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_INN_FILE = ROOT / "sample_data" / "sample_inn_input.csv"


def _write_request_json(path: Path, **overrides) -> Path:
    data = {
        "pilot_name": "output_pilot",
        "valid_from": date.today().isoformat(),
        "valid_to": (date.today() + timedelta(days=90)).isoformat(),
        "submitter_email": "submitter@bank.internal",
        "submitter_full_name": "Submitter Name",
        "recipient_emails": [],
        "analyst_email": "analyst@bank.internal",
        "expected_effect_pct": 5.0,
        "recalculation_frequency": "month",
        "grouping_metrics": ["okved"],
        "financial_effect_articles": ["chod"],
        "custom_metric_requests": [],
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _run(argv: list[str]) -> tuple[int, str]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        rc = cli.main(argv)
    return rc, buffer.getvalue()


# --- the JSON contract is untouched ---------------------------------------

def test_json_stays_the_default_and_is_unchanged_by_the_new_flag(monkeypatch):
    monkeypatch.delenv("AB_SKILL_OUTPUT", raising=False)
    _, implicit = _run(["metrics"])
    _, explicit = _run(["metrics", "--output", "json"])
    assert implicit == explicit
    json.loads(implicit)  # still exactly one parseable document


def test_text_mode_renders_the_same_payload_without_touching_the_command(monkeypatch):
    """The renderer is an adapter on the way out, so whatever `--output json`
    would have produced is what gets rendered."""
    monkeypatch.delenv("AB_SKILL_OUTPUT", raising=False)
    _, as_json = _run(["metrics", "--output", "json"])
    _, as_text = _run(["metrics", "--output", "text"])
    codes = [m["code"] for m in json.loads(as_json)]
    assert codes
    for code in codes:
        assert code in as_text
    with pytest.raises(json.JSONDecodeError):
        json.loads(as_text)


def test_the_flag_works_before_and_after_the_subcommand(monkeypatch):
    """A tool wrapper should not have to care which position it uses."""
    monkeypatch.delenv("AB_SKILL_OUTPUT", raising=False)
    _, after = _run(["metrics", "--output", "text"])
    _, before = _run(["--output", "text", "metrics"])
    assert after == before
    assert "Всего:" in after


def test_the_default_can_be_set_by_environment(monkeypatch):
    monkeypatch.setenv("AB_SKILL_OUTPUT", "text")
    _, out = _run(["metrics"])
    assert "Всего:" in out
    # an explicit flag still wins over the environment
    _, out = _run(["metrics", "--output", "json"])
    json.loads(out)


def test_exit_codes_are_unaffected_by_the_output_format(scratch_config, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "default_config", lambda: scratch_config)
    bad = tmp_path / "bad.csv"
    bad.write_text("inn\n12345\n", encoding="utf-8")
    request = _write_request_json(tmp_path / "request.json")
    for fmt in ("json", "text"):
        rc, _ = _run(["run", "--output", fmt, "--request", str(request), "--inn-file", str(bad)])
        assert rc == 1


# --- what the rendered output has to contain ------------------------------

def test_a_successful_run_reports_sizes_paths_and_a_next_step(
    scratch_config, tmp_path, monkeypatch
):
    monkeypatch.setattr(cli, "default_config", lambda: scratch_config)
    request = _write_request_json(tmp_path / "request.json", pilot_name="text_pilot")
    rc, out = _run(
        ["run", "--output", "text", "--request", str(request), "--inn-file", str(SAMPLE_INN_FILE)]
    )
    assert rc == 0
    assert "ГОТОВО" in out
    assert "Контрольная группа (КГ)" in out and "Целевая группа (ЦГ)" in out
    assert "control_group" in out and "target_group" in out
    assert "СЛЕДУЮЩИЙ ШАГ" in out
    assert "recalc --pilot-folder" in out, "the next command has to be spelled out"
    # the 50 INNs themselves must NOT be inlined -- that is the whole point
    inns = SAMPLE_INN_FILE.read_text(encoding="utf-8").splitlines()[1:]
    assert sum(1 for inn in inns if inn.strip() and inn.strip() in out) == 0


def test_a_rebase_pilot_says_so_in_the_rendered_output(scratch_config, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "default_config", lambda: scratch_config)
    request = _write_request_json(
        tmp_path / "request.json",
        pilot_name="cascade_text_pilot",
        split_method={
            "answers": {
                "entry_timing": "in_waves",
                "list_growth": "will_grow",
                "segment_drift": "stable",
                "attrition": "minimal",
                "treatment_levels": "single_treatment",
            },
            "recommended": "cascade_rebase",
            "chosen": "cascade_rebase",
            "confirmed": True,
            "override_reason": "",
        },
    )
    _, out = _run(
        ["run", "--output", "text", "--request", str(request), "--inn-file", str(SAMPLE_INN_FILE)]
    )
    assert "ТРЕБУЕТСЯ РЕБЕЙЗ" in out
    assert "НЕ окончательный состав групп" in out
    assert "REBASE_REQUIRED.md" in out


def test_a_validation_refusal_says_nothing_was_written(scratch_config, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "default_config", lambda: scratch_config)
    request = _write_request_json(tmp_path / "request.json", grouping_metrics=[])
    rc, out = _run(
        ["run", "--output", "text", "--request", str(request), "--inn-file", str(SAMPLE_INN_FILE)]
    )
    assert rc == 1
    assert "ОТКАЗ" in out
    assert "grouping_metrics" in out
    assert "не создавались" in out, "the user has to know there is nothing to clean up"


def test_both_documents_render_when_a_command_prints_two(
    scratch_config, tmp_path, monkeypatch
):
    """`run --drop-invalid-inns` prints the drop report, then the result."""
    monkeypatch.setattr(cli, "default_config", lambda: scratch_config)
    inn_file = tmp_path / "inns.csv"
    inn_file.write_text(
        SAMPLE_INN_FILE.read_text(encoding="utf-8").rstrip() + "\n12345\n", encoding="utf-8"
    )
    request = _write_request_json(tmp_path / "request.json", pilot_name="two_doc_pilot")
    rc, out = _run(
        [
            "run", "--output", "text", "--request", str(request),
            "--inn-file", str(inn_file), "--drop-invalid-inns",
        ]
    )
    assert rc == 0
    assert "отброшено строк" in out          # document 1
    assert "ГОТОВО: КГ и ЦГ сформированы" in out  # document 2


def test_prose_output_is_passed_through_not_swallowed():
    """advise-method without --json prints the outline, which is not JSON."""
    rc, out = _run(["advise-method", "--output", "text", "--describe", "cascade_rebase"])
    assert rc == 0
    assert "Каскадное разделение" in out
    assert "Как это будет работать" in out


# --- the renderer itself --------------------------------------------------

@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"status": "skipped", "reason": "RecalculationNotDueError", "detail": "x"}, "ПРОПУЩЕНО"),
        ({"status": "error", "error_type": "ValueError", "detail": "boom"}, "ОТКАЗ"),
        ({"status": "pilot_already_exists", "pilot_folder": "/p", "detail": "d"}, "--force"),
        ({"status": "no_valid_inns_remaining"}, "не осталось"),
        (
            {"status": "no_eligible_clients", "blocked": [
                {"inn": "1", "existing_pilot_name": "other",
                 "existing_valid_from": "a", "existing_valid_to": "b"}]},
            "уже в пилоте",
        ),
        ({"status": "ok", "as_of": "2026-01-01", "due_count": 0, "pilots": []}, "не требуется"),
    ],
)
def test_every_status_has_a_renderer(payload, expected):
    assert expected in output.render_document(payload)


def test_an_unknown_payload_is_still_printed_in_full():
    """A payload added later must degrade to readable, never to silence."""
    rendered = output.render_document(
        {"status": "something_new", "widget_count": 3, "nested": {"a": 1}}
    )
    assert "something_new" in rendered
    assert "widget_count" in rendered and "3" in rendered
    assert "nested" in rendered


def test_low_coverage_is_flagged_in_the_rendered_summary():
    rendered = output.render_document(
        {
            "status": "ok",
            "result": {
                "request": {"pilot_name": "p", "valid_from": "a", "valid_to": "b"},
                "split": {"control": ["1"], "target": ["2"], "balanced": True,
                          "attempts_used": 1, "seed": 42},
                "coverage": {"chod": 1, "okved": 2},
                "control_file": "c", "target_file": "t", "pilot_folder": "f",
            },
        }
    )
    assert "МАЛО!" in rendered, "a half-covered metric must not read like a full one"


def test_empty_output_renders_to_empty_not_to_an_error():
    assert output.render_stdout("") == ""
    assert output.render_stdout("   \n") == ""
