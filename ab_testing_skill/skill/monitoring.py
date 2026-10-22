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

import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import SkillConfig, default_config
from .connectors.dashboard_connector import DashboardConnector, LocalDropzoneDashboardConnector
from .exporter import read_codes_file, read_rows, write_financial_effect_file
from .analysis import HOMOGENEITY_FILENAME, NoHistoryError
from .metrics.runner import MetricRunner
from .splitter import _balance_report

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
    # The month being reported on, named explicitly. Asking for the scalar
    # view here measured "whatever the script returns for today" -- which for
    # a mart query happens to be the right month, but for anything else is
    # whatever it feels like, and in the bundled demo bank it was a constant.
    # Every block then held identical numbers and the pilot showed a flat
    # line forever. The period is part of the question, so it is asked.
    period = f"{as_of_date.year:04d}-{as_of_date.month:02d}"
    series = runner.run_many_series(
        meta["financial_effect_articles"], all_inns, as_of_date, months=[period]
    )
    financial_values = {code: value.scalar() for code, value in series.items()}

    path = write_financial_effect_file(
        pilot_folder, as_of_date, financial_values, group_of, mode=config.storage.recalc_mode
    )

    # The comparability re-check the cascade/monitored methods promise. Runs
    # on the metric values this pass already computed, so it costs nothing
    # extra -- and it has to run here, because a one-off check at intake says
    # nothing about whether the groups are still comparable six periods in.
    if meta.get("homogeneity_recheck_required"):
        run_homogeneity_check(
            pilot_folder,
            control=control,
            target=target,
            financial_values=financial_values,
            as_of_date=as_of_date,
            max_standardized_diff=config.split.max_standardized_diff,
        )

    # The report is rebuilt on every pass, so the link an analyst keeps open
    # always shows the latest state. Needs two periods to say anything, so
    # the first recalculation quietly produces nothing.
    try:
        build_reports(pilot_folder)
    except NoHistoryError:
        pass

    dashboard_connector.upload(meta["pilot_slug"], path)
    return path


def build_reports(pilot_folder: Path) -> dict[str, Path]:
    """Analysis + all three renderings, written into the pilot folder."""
    from .analysis import analyse_pilot
    from .report import render_text, write_excel, write_html

    analysis = analyse_pilot(pilot_folder)
    text_path = Path(pilot_folder) / "pilot_report.txt"
    text_path.write_text(render_text(analysis), encoding="utf-8")
    return {
        "text": text_path,
        "excel": write_excel(analysis, pilot_folder),
        "html": write_html(analysis, pilot_folder),
    }


def run_homogeneity_check(
    pilot_folder: Path,
    control: list[str],
    target: list[str],
    financial_values: dict[str, dict],
    as_of_date: date,
    max_standardized_diff: float,
) -> dict[str, dict[str, float]]:
    """Re-checks CG/TG comparability on the membership that exists today.

    Appends one row per financial article per report_date to
    `homogeneity_checks.csv` in the pilot folder, so the analyst can see
    *from which period* the comparison stopped being reliable rather than
    only that it is unreliable now.

    Deliberately does not re-split anything. Once a client in the target
    group has had the treatment, moving them to control to restore balance
    would contaminate the control group -- the rebase is a recalculation of
    the comparison baseline, not a reassignment of clients. That
    distinction is the whole reason the questionnaire exists.
    """
    report = _balance_report(control, target, financial_values, max_standardized_diff)
    path = Path(pilot_folder) / HOMOGENEITY_FILENAME
    header = [
        "report_date",
        "article",
        "control_n",
        "target_n",
        "control_mean",
        "target_mean",
        "smd",
        "threshold",
        "within_tolerance",
        "action",
    ]
    is_new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(header)
        for article, stats in sorted(report.items()):
            within = stats["balanced"] == 1.0
            writer.writerow(
                [
                    as_of_date.isoformat(),
                    article,
                    int(stats["control_n"]),
                    int(stats["target_n"]),
                    f"{stats['control_mean']:.4f}",
                    f"{stats['target_mean']:.4f}",
                    f"{stats['smd']:.4f}",
                    max_standardized_diff,
                    "yes" if within else "no",
                    "" if within else "REBASE: пересчитать базу сравнения с этой даты",
                ]
            )
    return report


def latest_homogeneity_check(pilot_folder: Path) -> dict | None:
    """The most recent check's rows, for a caller that needs to report it.

    `run_recalculation` keeps returning the financial-effect path (callers
    and schedulers depend on that), so the check is read back from disk
    rather than threaded through its return type.
    """
    path = Path(pilot_folder) / HOMOGENEITY_FILENAME
    if not path.exists():
        return None
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    last_date = max(row["report_date"] for row in rows)
    latest = [row for row in rows if row["report_date"] == last_date]
    drifted = [row["article"] for row in latest if row["within_tolerance"] == "no"]
    return {
        "report_date": last_date,
        "articles": latest,
        "drifted_articles": drifted,
        "rebase_needed": bool(drifted),
    }
