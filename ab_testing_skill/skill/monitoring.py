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


def run_recalculation(
    pilot_folder: Path,
    config: SkillConfig | None = None,
    dashboard_connector: DashboardConnector | None = None,
    as_of_date: date | None = None,
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
