"""Central configuration for the AB-testing skill.

Every path/flag that a real deployment needs to change to point at Sber's
actual systems (registries, PySpark script bank, SMTP, Navigator) lives
here. Nothing else in the package should hardcode a path or a threshold.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class RegistryConfig:
    """Locations of the three prerequisite tables from the spec.

    Backed by CSV files by default (see skill/registries.py). Swap
    `CsvRegistry` for a DB-backed implementation without touching callers —
    every consumer only depends on the `Registry` protocol.

    Д12: these live under data/registry/ (gitignored), NOT sample_data/.
    They used to default into sample_data/, so an ordinary production run
    modified version-controlled files -- the auditor hit exactly that
    (`git status` showed a dirty involved_inns.csv after one CLI run), and
    so did this project during development. sample_data/ is now read-only
    reference data; anything a run writes goes under data/.
    """

    involved_inns_path: Path = PACKAGE_ROOT / "data" / "registry" / "involved_inns.csv"
    duplicates_path: Path = PACKAGE_ROOT / "data" / "registry" / "inn_duplicates.csv"
    overlap_path: Path = PACKAGE_ROOT / "data" / "registry" / "metric_overlap.csv"
    metric_requests_path: Path = PACKAGE_ROOT / "data" / "registry" / "metric_requests.csv"


@dataclass
class MetricScriptConfig:
    """Where the "bank of PySpark scripts" lives and how to run it.

    ASSUMPTION (spec did not define a script bank format): each metric is
    one module under `scripts_dir` exposing
        run(inn_list: list[str], as_of_date: date, spark=None) -> dict[str, float]
    In production, point `scripts_dir` at the real bank (same signature)
    and set `use_spark=True` so a live SparkSession is injected instead of
    the local pandas-free demo data in sample_data/attributes_reference.csv.
    """

    scripts_dir: Path = PACKAGE_ROOT / "metric_scripts"
    manifest_path: Path = PACKAGE_ROOT / "metric_scripts" / "manifest.json"
    # alias -> real table name, read via metric_scripts.subscriptions.get_subscription();
    # keeps real table names out of individual scripts. See that module's docstring.
    subscriptions_path: Path = PACKAGE_ROOT / "metric_scripts" / "subscriptions.json"
    use_spark: bool = os.environ.get("AB_SKILL_USE_SPARK", "false").lower() == "true"
    demo_reference_path: Path = PACKAGE_ROOT / "sample_data" / "attributes_reference.csv"


@dataclass
class SplitConfig:
    """Stratified split + financial balance-check tunables."""

    target_ratio: float = 0.5  # share assigned to Target group within each stratum
    random_seed: int | None = 42
    # After the stratified split, each financial metric's standardized mean
    # difference (SMD) between CG and TG must be <= this, or the splitter
    # reshuffles within strata and retries. 0.1 is the conventional balance
    # threshold. See splitter._balance_report for why SMD and not a relative
    # difference of means.
    max_standardized_diff: float = 0.10
    max_reshuffle_attempts: int = 25


@dataclass
class OverlapConfig:
    """How step 2's "already involved" check treats CG vs TG roles.

    ASSUMPTION (spec explicitly flagged this as "уточнить" / to be
    clarified): the spec's literal wording only worries about purity of an
    *already running* pilot when a client is pulled into a *new Target*
    group. Reading strictly, prior Control-group membership never blocks
    reuse (in either role), and prior Target-group membership only blocks
    reuse as Target in a pilot that measures an overlapping metric while
    still active (valid_to in the future). That is what `blocking_roles`
    and `require_metric_overlap` encode below. Flip them if the business
    clarifies stricter rules (e.g. any active TG membership blocks any
    reuse regardless of metric overlap).
    """

    blocking_roles: tuple[str, ...] = ("tg",)
    require_metric_overlap: bool = True


@dataclass
class MasterStatusConfig:
    """NEW, not in the original spec: a master current-status table per

    INN (Used / Unused / Used_as_cg), checked as its own step before the
    existing InvolvedInnsRegistry overlap check. ASSUMPTION: "Used" blocks
    reuse, "Used_as_cg" and "Unused" don't -- consistent with the existing
    CG-is-always-reusable assumption in OverlapConfig above. Change
    `blocking_statuses` if the business wants Used_as_cg to block too.
    """

    path: Path = PACKAGE_ROOT / "data" / "registry" / "inn_master_status.csv"
    blocking_statuses: tuple[str, ...] = ("Used",)


@dataclass
class NotificationConfig:
    dev_team_email: str = os.environ.get("AB_SKILL_DEV_TEAM_EMAIL", "dev-team@bank.internal")
    analytics_team_email: str = os.environ.get(
        "AB_SKILL_ANALYTICS_TEAM_EMAIL", "analytics-team@bank.internal"
    )


@dataclass
class PilotStorageConfig:
    pilots_root: Path = PACKAGE_ROOT / "data" / "pilots"
    navigator_dropzone: Path = PACKAGE_ROOT / "data" / "navigator_dropzone"
    # ASSUMPTION (spec: "формат полной перезаписи или дописывания новых
    # строк - уточнить"): default to appending a new block of rows per
    # report_date so the Navigator dashboard gets a genuine time series.
    # Set to "overwrite" to instead replace the sheet each recalculation.
    recalc_mode: str = os.environ.get("AB_SKILL_RECALC_MODE", "append")


@dataclass
class CalculationConfig:
    """Storage for the metrics-calculation product (web/metrics_calc.html).

    Separate root from the pilots tree: these are one-shot, read-only
    calculations, not pilots with a lifecycle to monitor.
    """

    results_root: Path = PACKAGE_ROOT / "data" / "calculations"


@dataclass
class SkillConfig:
    registry: RegistryConfig = field(default_factory=RegistryConfig)
    metrics: MetricScriptConfig = field(default_factory=MetricScriptConfig)
    split: SplitConfig = field(default_factory=SplitConfig)
    overlap: OverlapConfig = field(default_factory=OverlapConfig)
    master_status: MasterStatusConfig = field(default_factory=MasterStatusConfig)
    notify: NotificationConfig = field(default_factory=NotificationConfig)
    storage: PilotStorageConfig = field(default_factory=PilotStorageConfig)
    calculation: CalculationConfig = field(default_factory=CalculationConfig)


def default_config() -> SkillConfig:
    return SkillConfig()
