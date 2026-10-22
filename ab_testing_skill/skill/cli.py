"""Command-line entry point.

    python -m skill.cli run --request request.json --inn-file inns.csv
    python -m skill.cli run --request request.json --inn-file inns.csv --drop-invalid-inns
    python -m skill.cli recalc --pilot-folder data/pilots/<slug>
    python -m skill.cli metrics [--usable-as grouping|financial_effect]
    python -m skill.cli advise-method                    # interactive questionnaire
    python -m skill.cli advise-method --answers a.json --request request.json --json
    python -m skill.cli advise-method --describe cascade_rebase
    python -m skill.cli rebase-due                       # pilots owing a rebase today
    python -m skill.cli report --pilot-folder <папка> --text   # how the pilot is going

`run` is what web/index.html's exported bundle is meant to be fed into;
`recalc` is what a scheduler calls on the configured cadence (spec step 6).
Both print a JSON result to stdout so a GigaCode tool wrapper can shell out
to this CLI and parse the response without needing a Python import.

By default `run` still rejects the whole file if any INN fails step-1
validation (format/checksum) -- see IntakeRejected in pipeline.py and the
README's "Assumptions" section for why. `--drop-invalid-inns` opts into a
looser mode: bad rows are filtered out and the split runs on whatever
INNs remain, instead of failing the submission outright.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import dataclasses
import io
import json
import os
import sys
from datetime import date
from pathlib import Path

from .calc_pipeline import CalculationRejected, NoMetricsSelectedError, run_calculation
from .config import default_config
from . import method_advisor, output
from .analysis import NoHistoryError, analyse_pilot
from .report import render_text, write_excel, write_html
from .inn_utils import validate_file
from .metrics.runner import MetricRunner
from .models import CalculationRequest, PilotRequest
from .monitoring import AlreadyCalculatedError, RecalculationNotDueError, run_recalculation
from .registries import RebaseRemindersRegistry
from .pipeline import (
    IntakeRejected,
    NoEligibleClientsError,
    PilotAlreadyExistsError,
    run_intake,
)
from .validation import RequestValidationError


def _json_default(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"not JSON serializable: {type(obj)}")


def _drop_invalid_inns(inn_file: Path, strict_inn_checksum: bool = True):
    """Filters `inn_file` down to the INNs that pass step-1 validation

    (format + optionally the FNS checksum). Writes the survivors to a new
    file next to the original (`<stem>_cleaned.csv`) so the split can run
    on the INNs that remain, instead of `run_intake` rejecting the whole
    submission over a handful of bad rows. Returns (cleaned_path, result)
    where `result` is the full ValidationResult, still carrying which rows
    were dropped and why, so the caller can report it.
    """
    result = validate_file(inn_file, check_control_digits=strict_inn_checksum)
    cleaned_path = inn_file.with_name(f"{inn_file.stem}_cleaned{inn_file.suffix}")
    with open(cleaned_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["inn"])
        writer.writerows([[inn] for inn in result.valid_inns])
    return cleaned_path, result


def _cmd_run(args: argparse.Namespace) -> int:
    request_data = json.loads(Path(args.request).read_text(encoding="utf-8"))
    request = PilotRequest.from_dict(request_data)
    config = default_config()
    inn_file = Path(args.inn_file)

    if args.drop_invalid_inns:
        inn_file, validation = _drop_invalid_inns(inn_file)
        if validation.issues:
            print(
                json.dumps(
                    {
                        "status": "invalid_inns_dropped",
                        "dropped_count": len(validation.issues),
                        "remaining_count": len(validation.valid_inns),
                        "dropped": [dataclasses.asdict(i) for i in validation.issues],
                        "cleaned_file": str(inn_file),
                    },
                    default=_json_default,
                    ensure_ascii=False,
                    indent=2,
                )
            )
        if not validation.valid_inns:
            print(json.dumps({"status": "no_valid_inns_remaining"}, indent=2))
            return 1

    try:
        result = run_intake(request, inn_file, config=config, force=args.force)
    except RequestValidationError as exc:
        print(
            json.dumps(
                {
                    "status": "invalid_request",
                    "issues": [dataclasses.asdict(i) for i in exc.issues],
                },
                default=_json_default,
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    except PilotAlreadyExistsError as exc:
        print(
            json.dumps(
                {
                    "status": "pilot_already_exists",
                    "pilot_folder": exc.pilot_folder,
                    "detail": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    except IntakeRejected as exc:
        print(
            json.dumps(
                {"status": "rejected", "issues": [dataclasses.asdict(i) for i in exc.issues]},
                default=_json_default,
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    except NoEligibleClientsError as exc:
        print(
            json.dumps(
                {
                    "status": "no_eligible_clients",
                    "blocked": [dataclasses.asdict(b) for b in exc.blocked],
                },
                default=_json_default,
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    except Exception as exc:  # noqa: BLE001 - the CLI contract is "always JSON on stdout"
        print(
            json.dumps(
                {"status": "error", "error_type": type(exc).__name__, "detail": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(
        json.dumps(
            {"status": "ok", "result": dataclasses.asdict(result)},
            default=_json_default,
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_recalc(args: argparse.Namespace) -> int:
    config = default_config()
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    try:
        path = run_recalculation(
            Path(args.pilot_folder), config=config, as_of_date=as_of, force=args.force
        )
    except (RecalculationNotDueError, AlreadyCalculatedError) as exc:
        # Not an error for a scheduler firing more often than the pilot's
        # cadence -- the expected outcome is "nothing to do".
        print(
            json.dumps(
                {"status": "skipped", "reason": type(exc).__name__, "detail": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI contract is JSON on stdout
        print(
            json.dumps(
                {"status": "error", "error_type": type(exc).__name__, "detail": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(json.dumps({"status": "ok", "financial_effect_file": str(path)}, indent=2))
    return 0


def _cmd_calc(args: argparse.Namespace) -> int:
    """Metrics-calculation product: ID file + selected metrics -> Excel."""
    request_data = json.loads(Path(args.request).read_text(encoding="utf-8"))
    request = CalculationRequest.from_dict(request_data)
    config = default_config()
    try:
        result = run_calculation(
            request,
            Path(args.id_file),
            config=config,
            drop_invalid_ids=args.drop_invalid_ids,
        )
    except CalculationRejected as exc:
        print(
            json.dumps(
                {"status": "rejected", "issues": [dataclasses.asdict(i) for i in exc.issues]},
                default=_json_default,
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    except RequestValidationError as exc:
        print(
            json.dumps(
                {"status": "invalid_request", "issues": [dataclasses.asdict(i) for i in exc.issues]},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    except (NoMetricsSelectedError, KeyError, ValueError) as exc:
        print(json.dumps({"status": "error", "detail": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    print(
        json.dumps(
            {"status": "ok", "result": dataclasses.asdict(result)},
            default=_json_default,
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_advise_method(args: argparse.Namespace) -> int:
    """The split-method questionnaire: ask, recommend, show, confirm.

    Three shapes, because the caller might be a human at a terminal, a
    GigaCode agent holding a conversation, or the web form's exported JSON:

      --questions            -> the questions to ask, as JSON
      --describe <method>    -> that method's outline, for the confirm step
      --answers answers.json -> the recommendation + outline + the question
                                to put to the user
      (no flags)             -> interactive: asks the questions on stdin

    Nothing here writes anything. The decision only takes effect once it is
    recorded in request.json and `run` is called, which is what forces the
    user's confirmation to be explicit rather than implied by a dropdown.
    """
    if args.questions:
        print(json.dumps(method_advisor.questions(), ensure_ascii=False, indent=2))
        return 0

    if args.describe:
        recommendation = method_advisor.describe(args.describe)
        if recommendation is None:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "detail": f"unknown method {args.describe!r}; known: "
                        + ", ".join(sorted(method_advisor.methods())),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        if args.json:
            print(json.dumps(recommendation.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(recommendation.as_text())
        return 0

    iterations = args.iterations
    if args.request:
        request = PilotRequest.from_dict(
            json.loads(Path(args.request).read_text(encoding="utf-8"))
        )
        iterations = iterations or method_advisor.expected_iterations(
            request.valid_from, request.valid_to, request.recalculation_frequency
        )

    if args.answers:
        answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))
        answers = answers.get("answers", answers)
    else:
        answers = _ask_questionnaire_interactively()
        if answers is None:
            return 1

    try:
        recommendation = method_advisor.recommend(answers, iterations=iterations)
    except method_advisor.UnknownAnswerError as exc:
        print(json.dumps({"status": "error", "detail": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "status": "ok",
                    "answers": answers,
                    "recommendation": recommendation.to_dict(),
                    "record_into_request_json": {
                        "split_method": {
                            "answers": answers,
                            "recommended": recommendation.method,
                            "chosen": recommendation.method,
                            "confirmed": False,
                            "override_reason": "",
                        }
                    },
                    "next_step": (
                        "Прочитайте описание метода заказчику и спросите, похоже ли это на его "
                        "пилот. Если да -- confirmed: true. Если нет -- покажите альтернативу "
                        f"({recommendation.alternative}) через --describe, и при выборе укажите "
                        "chosen + override_reason."
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(recommendation.as_text())
    return 0


def _ask_questionnaire_interactively() -> dict[str, str] | None:
    answers: dict[str, str] = {}
    for question in method_advisor.questions():
        print()
        print(question["question"])
        print(f"  ({question['why']})")
        options = question["options"]
        for i, option in enumerate(options, 1):
            print(f"  {i}. {option['label']}")
        while True:
            raw = input("Ваш ответ (номер): ").strip()
            if not raw.isdigit() or not 1 <= int(raw) <= len(options):
                print(f"Введите число от 1 до {len(options)}.")
                continue
            answers[question["id"]] = options[int(raw) - 1]["id"]
            break
    print()
    return answers


def _cmd_rebase_due(args: argparse.Namespace) -> int:
    """Pilots owing a rebase + comparability re-check as of a given date.

    The note in each pilot folder tells whoever opens that folder; this
    answers the question no folder can -- "what is due right now".
    """
    config = default_config()
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    reminders = RebaseRemindersRegistry(config.registry.rebase_reminders_path)
    due = reminders.due_on(as_of)
    print(
        json.dumps(
            {
                "status": "ok",
                "as_of": as_of.isoformat(),
                "due_count": len(due),
                "pilots": [dataclasses.asdict(r) for r in due],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    """Rebuild the pilot's analysis from the history it has accumulated."""
    folder = Path(args.pilot_folder)
    try:
        analysis = analyse_pilot(folder, article=args.article)
    except NoHistoryError as exc:
        print(json.dumps({"status": "no_history", "detail": str(exc)},
                         ensure_ascii=False, indent=2))
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI contract is JSON on stdout
        print(json.dumps({"status": "error", "error_type": type(exc).__name__,
                          "detail": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    if args.text:
        print(render_text(analysis))
        return 0

    written = {"text": str(folder / "pilot_report.txt")}
    (folder / "pilot_report.txt").write_text(render_text(analysis), encoding="utf-8")
    if not args.no_files:
        written["excel"] = str(write_excel(analysis, folder))
        written["html"] = str(write_html(analysis, folder))
    print(
        json.dumps(
            {"status": "ok", "analysis": analysis.to_dict(), "files": written},
            default=_json_default, ensure_ascii=False, indent=2,
        )
    )
    return 0


def _cmd_filters(args: argparse.Namespace) -> int:
    config = default_config()
    runner = MetricRunner(config.metrics)
    try:
        filters_module = runner._import_script("filters.py")
    except ModuleNotFoundError:
        print(json.dumps({"status": "error", "detail": "this script bank has no filters.py"}, indent=2))
        return 1
    defs = (
        filters_module.filters_for_metric(args.metric)
        if args.metric
        else filters_module.list_filters()
    )
    print(
        json.dumps(
            [dataclasses.asdict(d) for d in defs.values()], ensure_ascii=False, indent=2
        )
    )
    return 0


def _cmd_metrics(args: argparse.Namespace) -> int:
    config = default_config()
    runner = MetricRunner(config.metrics)
    defs = runner.available_metrics(usable_as=args.usable_as)
    print(json.dumps([dataclasses.asdict(d) for d in defs], ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    # --output is declared once and attached to every subparser as well as the
    # top level, so both `cli --output text run ...` and `cli run --output text`
    # work -- an agent/tool wrapper should not have to care which. SUPPRESS so
    # the subparser's copy does not overwrite a value given before the
    # subcommand with its own default.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--output",
        choices=["json", "text"],
        default=argparse.SUPPRESS,
        help=(
            "json (default): one machine-readable document per command, the contract a "
            "tool wrapper parses. text: the same payload rendered for a person or for an "
            "agent to relay -- labelled facts, file paths instead of inlined lists, and "
            "an explicit next step. Set AB_SKILL_OUTPUT to change the default."
        ),
    )

    parser = argparse.ArgumentParser(prog="python -m skill.cli", parents=[common])
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser(
        "run", help="Run intake steps 1-5 for a new pilot request", parents=[common]
    )
    p_run.add_argument("--request", required=True, help="Path to request JSON (see web/index.html)")
    p_run.add_argument("--inn-file", required=True, help="Path to the submitted INN list CSV")
    p_run.add_argument(
        "--drop-invalid-inns",
        action="store_true",
        help=(
            "Drop INNs that fail step-1 validation (bad format/checksum) instead of "
            "rejecting the whole file, and run the split on the remaining valid INNs. "
            "Writes the filtered list to <inn-file stem>_cleaned.csv."
        ),
    )
    p_run.add_argument(
        "--force",
        action="store_true",
        help="Re-run a pilot whose folder already exists (otherwise refused, see Д3).",
    )
    p_run.set_defaults(func=_cmd_run)

    p_recalc = sub.add_parser(
        "recalc", help="Run one recalculation pass for an existing pilot", parents=[common]
    )
    p_recalc.add_argument("--pilot-folder", required=True)
    p_recalc.add_argument("--as-of", help="YYYY-MM-DD, defaults to today")
    p_recalc.add_argument(
        "--force",
        action="store_true",
        help="Recalculate even if not due, or replace an already-calculated report_date.",
    )
    p_recalc.set_defaults(func=_cmd_recalc)

    p_calc = sub.add_parser(
        "calc",
        help="Calculate selected metrics for an uploaded ID list (.xlsx or .csv)",
        parents=[common],
    )
    p_calc.add_argument("--request", required=True, help="Path to calc request JSON (see web/metrics_calc.html)")
    p_calc.add_argument("--id-file", required=True, help="Path to the uploaded ID list (.xlsx or .csv)")
    p_calc.add_argument(
        "--drop-invalid-ids",
        action="store_true",
        help="Drop IDs that fail validation instead of rejecting the whole file.",
    )
    p_calc.set_defaults(func=_cmd_calc)

    p_advise = sub.add_parser(
        "advise-method",
        help=(
            "Split-method questionnaire: decide whether this pilot needs a cascade "
            "split with resegmentation and a rebase, or a one-shot split"
        ),
        parents=[common],
    )
    p_advise.add_argument(
        "--questions", action="store_true", help="Print the questions as JSON and exit"
    )
    p_advise.add_argument(
        "--answers", help="Path to a JSON file of {question_id: option_id} (or a request.json)"
    )
    p_advise.add_argument(
        "--describe",
        help="Print one method's outline (for the confirmation step / after an override)",
    )
    p_advise.add_argument(
        "--request",
        help="Pilot request JSON -- the pilot's term and cadence are read from it so a long "
        "pilot triggers the comparability re-check without asking the user about it",
    )
    p_advise.add_argument(
        "--iterations",
        type=int,
        help="Override the computed number of recalculation periods",
    )
    p_advise.add_argument("--json", action="store_true", help="Machine-readable output")
    p_advise.set_defaults(func=_cmd_advise_method)

    p_due = sub.add_parser(
        "rebase-due",
        help="List pilots owing a rebase + comparability re-check",
        parents=[common],
    )
    p_due.add_argument("--as-of", help="YYYY-MM-DD, defaults to today")
    p_due.set_defaults(func=_cmd_rebase_due)

    p_report = sub.add_parser(
        "report",
        help="Analyse how a running pilot is going, from its accumulated history",
        parents=[common],
    )
    p_report.add_argument("--pilot-folder", required=True)
    p_report.add_argument("--article", help="Which financial article to analyse (default: the first)")
    p_report.add_argument("--text", action="store_true", help="Print the overview and write nothing")
    p_report.add_argument("--no-files", action="store_true", help="Skip the Excel and HTML renderings")
    p_report.set_defaults(func=_cmd_report)

    p_filters = sub.add_parser(
        "filters", help="List filters available from the script bank", parents=[common]
    )
    p_filters.add_argument("--metric", help="Only filters that apply to this metric code")
    p_filters.set_defaults(func=_cmd_filters)

    p_metrics = sub.add_parser(
        "metrics",
        help="List available metrics from the script bank catalog",
        parents=[common],
    )
    p_metrics.add_argument("--usable-as", choices=["grouping", "financial_effect"], default=None)
    p_metrics.set_defaults(func=_cmd_metrics)

    return parser


def _output_format(args: argparse.Namespace) -> str:
    """json unless asked otherwise, so the parseable contract is the default."""
    chosen = getattr(args, "output", None)
    if chosen:
        return chosen
    return os.environ.get("AB_SKILL_OUTPUT", "json").strip().lower() or "json"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if _output_format(args) == "json":
        return args.func(args)

    # Every command already prints a JSON document (that is the documented
    # contract), so text rendering is an adapter on the way out rather than a
    # second code path through each command: whatever `--output json` would
    # have produced is exactly what gets rendered, and a command added later
    # is covered without being touched.
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rc = args.func(args)
    sys.stdout.write(output.render_stdout(buffer.getvalue()))
    return rc


if __name__ == "__main__":
    sys.exit(main())
