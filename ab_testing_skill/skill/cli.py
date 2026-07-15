"""Command-line entry point.

    python -m skill.cli run --request request.json --inn-file inns.csv
    python -m skill.cli recalc --pilot-folder data/pilots/<slug>
    python -m skill.cli metrics [--usable-as grouping|financial_effect]

`run` is what web/index.html's exported bundle is meant to be fed into;
`recalc` is what a scheduler calls on the configured cadence (spec step 6).
Both print a JSON result to stdout so a GigaCode tool wrapper can shell out
to this CLI and parse the response without needing a Python import.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import date
from pathlib import Path

from .config import default_config
from .metrics.runner import MetricRunner
from .models import PilotRequest
from .monitoring import run_recalculation
from .pipeline import IntakeRejected, NoEligibleClientsError, run_intake


def _json_default(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"not JSON serializable: {type(obj)}")


def _cmd_run(args: argparse.Namespace) -> int:
    request_data = json.loads(Path(args.request).read_text(encoding="utf-8"))
    request = PilotRequest.from_dict(request_data)
    config = default_config()
    try:
        result = run_intake(request, Path(args.inn_file), config=config)
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
    path = run_recalculation(Path(args.pilot_folder), config=config, as_of_date=as_of)
    print(json.dumps({"status": "ok", "financial_effect_file": str(path)}, indent=2))
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
    p_run.set_defaults(func=_cmd_run)

    p_recalc = sub.add_parser("recalc", help="Run one recalculation pass for an existing pilot")
    p_recalc.add_argument("--pilot-folder", required=True)
    p_recalc.add_argument("--as-of", help="YYYY-MM-DD, defaults to today")
    p_recalc.set_defaults(func=_cmd_recalc)

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
