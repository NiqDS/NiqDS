"""Command-line entry point.

    python -m skill.cli run --request request.json --inn-file inns.csv
    python -m skill.cli run --request request.json --inn-file inns.csv --drop-invalid-inns
    python -m skill.cli recalc --pilot-folder data/pilots/<slug>
    python -m skill.cli metrics [--usable-as grouping|financial_effect]

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
import csv
import dataclasses
import json
import sys
from datetime import date
from pathlib import Path

from .calc_pipeline import CalculationRejected, NoMetricsSelectedError, run_calculation
from .config import default_config
from .inn_utils import validate_file
from .metrics.runner import MetricRunner
from .models import CalculationRequest, PilotRequest
from .monitoring import AlreadyCalculatedError, RecalculationNotDueError, run_recalculation
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
    parser = argparse.ArgumentParser(prog="python -m skill.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run intake steps 1-5 for a new pilot request")
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

    p_recalc = sub.add_parser("recalc", help="Run one recalculation pass for an existing pilot")
    p_recalc.add_argument("--pilot-folder", required=True)
    p_recalc.add_argument("--as-of", help="YYYY-MM-DD, defaults to today")
    p_recalc.add_argument(
        "--force",
        action="store_true",
        help="Recalculate even if not due, or replace an already-calculated report_date.",
    )
    p_recalc.set_defaults(func=_cmd_recalc)

    p_calc = sub.add_parser(
        "calc", help="Calculate selected metrics for an uploaded ID list (.xlsx or .csv)"
    )
    p_calc.add_argument("--request", required=True, help="Path to calc request JSON (see web/metrics_calc.html)")
    p_calc.add_argument("--id-file", required=True, help="Path to the uploaded ID list (.xlsx or .csv)")
    p_calc.add_argument(
        "--drop-invalid-ids",
        action="store_true",
        help="Drop IDs that fail validation instead of rejecting the whole file.",
    )
    p_calc.set_defaults(func=_cmd_calc)

    p_filters = sub.add_parser("filters", help="List filters available from the script bank")
    p_filters.add_argument("--metric", help="Only filters that apply to this metric code")
    p_filters.set_defaults(func=_cmd_filters)

    p_metrics = sub.add_parser("metrics", help="List available metrics from the script bank catalog")
    p_metrics.add_argument("--usable-as", choices=["grouping", "financial_effect"], default=None)
    p_metrics.set_defaults(func=_cmd_metrics)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
