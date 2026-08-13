"""Concierge command-line runner.

Phase 0 delivery tool: point it at a folder of a real client's documents and get
the gap report and the client chase message — no web app, no login, no database
required. This is the manual-delivery workflow behind the concierge runbook
(docs/phase0/concierge-runbook.md).

Examples
--------
Run a real bundle from a folder:

    python -m app.cli run ./client-docs \
        --client "Bright Cafe Ltd" \
        --from 2026-01-01 --to 2026-03-31 \
        --accounts 12344471,99995555 \
        --out ./out

Run a shipped demo scenario (offline, no files needed):

    python -m app.cli demo BUNDLE-B-STATEMENTS

Everything runs on the offline `mock` backend by default; pass
--backend anthropic (with the SDK installed and a key in the env) for real
extraction.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from app.ingest.extract import extract_document
from app.ingest.loader import load_file
from app.models import Bundle
from app.report.chase import build_chase
from app.report.gaps import GapReport, build_gap_report
from app.rules import checks_temporal
from app.rules.engine import run_bundle, sort_flags
from app.scenarios import build_bundle as build_scenario_bundle

_LOADABLE = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".txt"}

# ANSI colours (disabled when not a TTY).
_C = {"block": "\033[31m", "warn": "\033[33m", "ok": "\033[32m",
      "dim": "\033[90m", "bold": "\033[1m", "reset": "\033[0m"}


def _paint(txt: str, key: str, colour: bool) -> str:
    if not colour:
        return txt
    return f"{_C[key]}{txt}{_C['reset']}"


def _gather_files(folder: Path) -> list[Path]:
    files = [p for p in sorted(folder.rglob("*")) if p.suffix.lower() in _LOADABLE and p.is_file()]
    return files


def _build_from_folder(args) -> Bundle:
    folder = Path(args.folder)
    if not folder.is_dir():
        sys.exit(f"error: {folder} is not a folder")
    files = _gather_files(folder)
    if not files:
        sys.exit(f"error: no loadable documents found in {folder}")

    print(_paint(f"Extracting {len(files)} document(s) with backend '{args.backend}'…", "dim", args.colour))
    documents = []
    for f in files:
        loaded = load_file(f)
        documents.append(extract_document(loaded, backend=args.backend))

    accounts = [a.strip() for a in (args.accounts or "").replace("\n", ",").split(",") if a.strip()]
    return Bundle(
        bundle_id=args.bundle_id or ("B-" + folder.name),
        client_name=args.client,
        declared_period_start=date.fromisoformat(args.date_from),
        declared_period_end=date.fromisoformat(args.date_to),
        expected_accounts=accounts,
        documents=documents,
    )


def _render_report_text(report: GapReport) -> str:
    lines = [f"# Gap report — {report.client_name} ({report.bundle_id})", "", report.summary, ""]
    for dr in report.documents:
        status = "PASS" if dr.passed else "BLOCK"
        lines.append(f"## {dr.source_file}  [{status}]")
        if not dr.flags:
            lines.append("  (clean)")
        for f in dr.flags:
            ev = f" — {f.evidence}" if f.evidence else ""
            lines.append(f"  [{f.severity}] {f.rule_id}{ev}")
            lines.append(f"      {f.message}")
        lines.append("")
    if report.bundle_flags:
        lines.append("## Bundle-level")
        for f in report.bundle_flags:
            ev = f" — {f.evidence}" if f.evidence else ""
            lines.append(f"  [{f.severity}] {f.rule_id}{ev}")
            lines.append(f"      {f.message}")
        lines.append("")
    return "\n".join(lines)


def _print_console(report: GapReport, colour: bool) -> None:
    print()
    print(_paint(report.summary, "bold", colour))
    print()
    for dr in report.documents:
        badge = _paint("PASS ", "ok", colour) if dr.passed else _paint("BLOCK", "block", colour)
        print(f"  {badge}  {dr.source_file}")
        for f in dr.flags:
            key = f.severity.lower() if f.severity.lower() in _C else "dim"
            tag = _paint(f"[{f.severity}]", key, colour)
            ev = _paint(f" {f.evidence}", "dim", colour) if f.evidence else ""
            print(f"         {tag} {f.rule_id}{ev}")
            print(_paint(f"           {f.message}", "dim", colour))
    if report.bundle_flags:
        print(f"\n  {_paint('Bundle-level', 'bold', colour)}")
        for f in report.bundle_flags:
            key = f.severity.lower() if f.severity.lower() in _C else "dim"
            tag = _paint(f"[{f.severity}]", key, colour)
            ev = _paint(f" {f.evidence}", "dim", colour) if f.evidence else ""
            print(f"         {tag} {f.rule_id}{ev}")
            print(_paint(f"           {f.message}", "dim", colour))
    print()


def _emit(bundle: Bundle, args) -> int:
    if args.today:
        checks_temporal.set_today(date.fromisoformat(args.today))
    flags = sort_flags(run_bundle(bundle))
    report = build_gap_report(bundle, flags)
    chase = build_chase(bundle, flags)

    _print_console(report, args.colour)

    if args.out:
        out = Path(args.out) / bundle.bundle_id
        out.mkdir(parents=True, exist_ok=True)
        (out / "gap-report.md").write_text(_render_report_text(report), encoding="utf-8")
        (out / "chase.txt").write_text(chase.text, encoding="utf-8")
        (out / "chase.html").write_text(chase.html, encoding="utf-8")
        print(_paint(f"Written gap-report.md, chase.txt, chase.html → {out}", "dim", args.colour))

    if args.save_db:
        from app import db

        db.init_db()
        db.save_bundle(bundle)
        print(_paint(f"Saved to app DB as {bundle.bundle_id} (view it in the web UI).", "dim", args.colour))

    # Non-zero exit if anything blocks — handy in scripts.
    return 1 if report.counts["block"] else 0


def main(argv: list[str] | None = None) -> int:
    # Shared options usable either before or after the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--backend", default="mock", help="LLM backend: mock (default), anthropic, openai")
    common.add_argument("--no-color", dest="colour", action="store_false", default=sys.stdout.isatty(),
                        help="disable coloured output")
    common.add_argument("--out", help="write gap-report.md + chase files under this folder")
    common.add_argument("--save-db", action="store_true", help="also save the bundle to the app DB")
    common.add_argument("--today", help="override 'today' (YYYY-MM-DD) for deterministic runs")

    parser = argparse.ArgumentParser(prog="intake-gate", description="Concierge intake runner.", parents=[common])
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="run a folder of client documents", parents=[common])
    run.add_argument("folder", help="folder containing the client's documents")
    run.add_argument("--client", required=True, help="client name")
    run.add_argument("--from", dest="date_from", required=True, help="declared period start (YYYY-MM-DD)")
    run.add_argument("--to", dest="date_to", required=True, help="declared period end (YYYY-MM-DD)")
    run.add_argument("--accounts", help="expected bank accounts, comma-separated")
    run.add_argument("--bundle-id", help="override the generated bundle id")

    dm = sub.add_parser("demo", help="run a shipped demo scenario (offline)", parents=[common])
    dm.add_argument("scenario", help="scenario id, e.g. BUNDLE-B-STATEMENTS")

    args = parser.parse_args(argv)

    if args.cmd == "run":
        bundle = _build_from_folder(args)
    else:
        bundle = build_scenario_bundle(args.scenario)
        # Demo scenarios are dated 2026; fix 'today' so they're reproducible.
        args.today = args.today or "2026-08-02"

    return _emit(bundle, args)


if __name__ == "__main__":
    raise SystemExit(main())
