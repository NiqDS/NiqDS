"""Step 6 of the spec: recurring recalculation of financial-effect articles

for an already-running pilot, keyed off the `recalculation_frequency`
captured at intake (day/week/month).

This module does not schedule itself -- call `run_recalculation()` from
whatever scheduler is available in the deployment (cron, Airflow, a
GigaCode-native scheduled tool). It's safe to call more often than the
configured frequency: each call just recalculates as-of today and appends
(or overwrites, per config) a new report_date block.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import SkillConfig, default_config
from .connectors.dashboard_connector import DashboardConnector, LocalDropzoneDashboardConnector
from .exporter import read_codes_file, read_rows, write_financial_effect_file
from .metrics.runner import MetricRunner

FREQUENCY_TO_TIMEDELTA = {
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
}


def load_pilot_meta(pilot_folder: Path) -> dict:
    meta_path = Path(pilot_folder) / "pilot_meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(
            f"{meta_path} not found -- was this folder created by pipeline.run_intake()?"
        )
    return json.loads(meta_path.read_text(encoding="utf-8"))


def is_due(pilot_folder: Path, as_of_date: date | None = None) -> bool:
    """True if enough time has passed since the last recorded report_date

    (or pilot creation) per the pilot's configured frequency. Optional
    convenience for schedulers that fire more often than every pilot's
    cadence and want to skip a no-op recalculation.
    """
    meta = load_pilot_meta(pilot_folder)
    as_of_date = as_of_date or date.today()
    financial_effect_path = _existing_financial_effect_path(Path(pilot_folder))
    last_date = meta.get("created_at")
    if financial_effect_path is not None:
        header, rows = read_rows(financial_effect_path)
        if header and rows:
            report_dates = [row[header.index("report_date")] for row in rows if row]
            if report_dates:
                last_date = max(report_dates)
    if last_date is None:
        return True
    last = datetime.strptime(last_date, "%Y-%m-%d").date()
    step = FREQUENCY_TO_TIMEDELTA.get(meta["recalculation_frequency"], timedelta(days=1))
    return as_of_date >= last + step


def _existing_financial_effect_path(pilot_folder: Path) -> Path | None:
    for suffix in (".xlsx", ".csv"):
        candidate = pilot_folder / f"financial_effect{suffix}"
        if candidate.exists():
            return candidate
    return None


class RecalculationNotDueError(Exception):
    """Called again before the pilot's cadence has elapsed (Д2).

    `is_due` existed but nothing called it, so a cron firing more often
    than a pilot's frequency appended a duplicate block of rows every time
    -- the auditor measured 200 rows all stamped with the same report_date
    after three same-day runs, which Navigator then charts as a 4x effect.
    """

    def __init__(self, pilot_folder: str, as_of_date: date, frequency: str):
        self.pilot_folder = pilot_folder
        super().__init__(
            f"recalculation for {pilot_folder} is not due on {as_of_date} "
            f"(frequency: {frequency}). Pass force=True (CLI: --force) to recalculate anyway."
        )


class AlreadyCalculatedError(Exception):
    """This report_date is already present in the financial-effect file.

    Appending it again would double-count that period in the dashboard.
    """

    def __init__(self, pilot_folder: str, as_of_date: date):
        self.pilot_folder = pilot_folder
        super().__init__(
            f"{pilot_folder} already has rows for report_date {as_of_date}. "
            "Appending would double-count this period. Pass force=True (CLI: --force) "
            "to replace that block instead."
        )


def _existing_report_dates(pilot_folder: Path) -> set[str]:
    path = _existing_financial_effect_path(pilot_folder)
    if path is None:
        return set()
    header, rows = read_rows(path)
    if not header or "report_date" not in header:
        return set()
    idx = header.index("report_date")
    return {str(row[idx]) for row in rows if row and row[idx] is not None}


def run_recalculation(
    pilot_folder: Path,
    config: SkillConfig | None = None,
    dashboard_connector: DashboardConnector | None = None,
    as_of_date: date | None = None,
    force: bool = False,
) -> Path:
    config = config or default_config()
    dashboard_connector = dashboard_connector or LocalDropzoneDashboardConnector(
        config.storage.navigator_dropzone
    )
    pilot_folder = Path(pilot_folder)
    meta = load_pilot_meta(pilot_folder)
    as_of_date = as_of_date or date.today()

    if not (meta["valid_from"] <= as_of_date.isoformat() <= meta["valid_to"]):
        raise ValueError(
            f"as_of_date {as_of_date} is outside the pilot's active window "
            f"({meta['valid_from']} .. {meta['valid_to']}) -- pilot may have ended"
        )

    # Д2: the schedule check now actually gates the run. A scheduler may
    # fire more often than any individual pilot's cadence -- that is exactly
    # the case `is_due` was written for -- so being called too early is
    # normal and must be a no-op, not a duplicate block of rows.
    if not force:
        if as_of_date.isoformat() in _existing_report_dates(pilot_folder):
            raise AlreadyCalculatedError(str(pilot_folder), as_of_date)
        if not is_due(pilot_folder, as_of_date=as_of_date):
            raise RecalculationNotDueError(
                str(pilot_folder), as_of_date, meta.get("recalculation_frequency", "?")
            )

    control = read_codes_file(pilot_folder / "control_group")
    target = read_codes_file(pilot_folder / "target_group")
    all_inns = control + target
    group_of = {inn: "cg" for inn in control}
    group_of.update({inn: "tg" for inn in target})

    runner = MetricRunner(config.metrics)
    financial_values = runner.run_many(meta["financial_effect_articles"], all_inns, as_of_date)

    path = write_financial_effect_file(
        pilot_folder, as_of_date, financial_values, group_of, mode=config.storage.recalc_mode
    )
    dashboard_connector.upload(meta["pilot_slug"], path)
    return path
