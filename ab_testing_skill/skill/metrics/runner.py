"""Dispatches metric codes (from the intake form) to the script bank.

`MetricScriptConfig.scripts_dir` must be an importable Python package
(has `__init__.py`) -- the bundled `metric_scripts/` demo bank is one; a
production bank should be too, so its scripts can use ordinary relative
imports the same way `metric_scripts/_common.py` does.
"""
from __future__ import annotations

import importlib
import inspect
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from ..config import MetricScriptConfig


@dataclass
class MetricDefinition:
    code: str
    label: str
    description: str
    value_type: str  # "categorical" | "numeric"
    usable_as: list[str]  # any of "grouping", "financial_effect"
    script: str


def load_manifest(path: Path) -> dict[str, MetricDefinition]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {entry["code"]: MetricDefinition(**entry) for entry in raw}


def script_accepts_filters(run_fn) -> bool:
    """True if a metric script's run() can take the `filters` argument.

    Lets one script bank hold both filter-aware scripts and older ones
    that predate the argument, instead of forcing a big-bang migration.
    """
    try:
        signature = inspect.signature(run_fn)
    except (TypeError, ValueError):  # pragma: no cover - builtins/C callables
        return False
    if "filters" in signature.parameters:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values())


def get_spark_session():
    try:
        from pyspark.sql import SparkSession
    except ImportError as exc:
        raise RuntimeError(
            "MetricScriptConfig.use_spark=True but pyspark is not installed "
            "in this environment. Either `pip install pyspark` or set "
            "AB_SKILL_USE_SPARK=false to use the local/demo runner."
        ) from exc
    return SparkSession.builder.appName("ab-testing-skill").getOrCreate()


class MetricRunner:
    def __init__(self, config: MetricScriptConfig):
        self.config = config
        self.manifest = load_manifest(config.manifest_path)
        self._spark = None

    def available_metrics(self, usable_as: str | None = None) -> list[MetricDefinition]:
        defs = list(self.manifest.values())
        if usable_as:
            defs = [d for d in defs if usable_as in d.usable_as]
        return sorted(defs, key=lambda d: d.code)

    def _import_script(self, script_name: str):
        scripts_dir = self.config.scripts_dir.resolve()
        parent = str(scripts_dir.parent)
        if parent not in sys.path:
            sys.path.insert(0, parent)
        module_name = f"{scripts_dir.name}.{Path(script_name).stem}"
        return importlib.import_module(module_name)

    def run(
        self,
        metric_code: str,
        inn_list: list[str],
        as_of_date: date,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if metric_code not in self.manifest:
            raise KeyError(
                f"unknown metric '{metric_code}' -- not present in {self.config.manifest_path}. "
                "If this is a newly-requested metric, it must be added to the manifest and "
                "the script bank before it can be run (see skill/registries.py:MetricRequestsRegistry)."
            )
        definition = self.manifest[metric_code]
        module = self._import_script(definition.script)
        spark = None
        if self.config.use_spark:
            if self._spark is None:
                self._spark = get_spark_session()
            spark = self._spark
        if not hasattr(module, "run"):
            raise AttributeError(f"metric script {definition.script} has no run() function")

        # The script contract is run(inn_list, as_of_date, spark=None, filters=None),
        # but `filters` was added later, so scripts predating it are still supported:
        # they're called with the old 3-argument form. What is NOT allowed is silently
        # dropping requested filters -- that would return unfiltered numbers that look
        # perfectly valid, so it's a hard error instead.
        if script_accepts_filters(module.run):
            return module.run(inn_list, as_of_date, spark=spark, filters=filters)
        if filters:
            raise TypeError(
                f"metric script {definition.script} does not accept a `filters` argument, "
                f"but filters {sorted(filters)} were requested for metric '{metric_code}'. "
                "Add `filters: dict | None = None` to its run() signature and apply them "
                "inside the query -- running it unfiltered would silently return the wrong numbers."
            )
        return module.run(inn_list, as_of_date, spark=spark)

    def run_many(
        self,
        metric_codes: list[str],
        inn_list: list[str],
        as_of_date: date,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        return {
            code: self.run(code, inn_list, as_of_date, filters=self.filters_for(code, filters))
            for code in metric_codes
        }

    def filters_for(self, metric_code: str, filters: dict[str, Any] | None) -> dict[str, Any] | None:
        """Narrows a filter selection to the ones declared for this metric.

        A user can pick a filter that only applies to some of the selected
        metrics (e.g. a sub-segment filter that's meaningless for OKVED);
        each script only receives the subset relevant to it. A script bank
        with no filters.py gets the full selection passed through.
        """
        if not filters:
            return None
        try:
            module = self._import_script("filters.py")
        except ModuleNotFoundError:
            return dict(filters)
        applicable = module.filters_for_metric(metric_code)
        selected = {code: value for code, value in filters.items() if code in applicable}
        return selected or None
