"""Dispatches metric codes (from the intake form) to the script bank.

`MetricScriptConfig.scripts_dir` must be an importable Python package
(has `__init__.py`) -- the bundled `metric_scripts/` demo bank is one; a
production bank should be too, so its scripts can use ordinary relative
imports the same way `metric_scripts/_common.py` does.
"""
from __future__ import annotations

import importlib
import os
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
    return script_accepts(run_fn, "filters")


def script_accepts(run_fn, name: str) -> bool:
    try:
        signature = inspect.signature(run_fn)
    except (TypeError, ValueError):  # pragma: no cover - builtins/C callables
        return False
    if name in signature.parameters:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values())


@dataclass
class MetricSeries:
    """A metric's answer as a monthly series, plus who the source knew about.

    The distinction this type exists for: **absent is not zero.** A client
    with no row in the mart and a client whose income was zero are different
    facts, and collapsing both to `None` (which is what the skill used to do)
    makes a data-supply problem look like a business one. Here, a client the
    source never returned has no entry in `by_month` at all; a client it
    returned with nothing earned has `0.0`.

    `coverage` counts the first kind, so "ran fine, every column blank" stops
    being a silent success.
    """

    code: str
    months: list[str]
    by_month: dict[str, dict[str, Any]]
    #: True when the script returned one number per client rather than a
    #: series. The value is carried on the last month of the window and
    #: `matrix()` repeats it -- a flat answer has no history, and inventing
    #: a trend from it would be worse than having none.
    is_flat: bool = False

    @staticmethod
    def from_script_output(code: str, raw: Any, months: list[str]) -> "MetricSeries":
        if not isinstance(raw, dict):
            raise TypeError(
                f"metric '{code}' returned {type(raw).__name__}, expected a dict of "
                "{инн: значение} or {инн: {месяц: значение}}"
            )
        by_month: dict[str, dict[str, Any]] = {}
        flat = True
        for inn, value in raw.items():
            if isinstance(value, dict):
                flat = False
                # keep only months we asked for; a script returning extra
                # months is not an error, but they are not part of the window
                kept = {m: v for m, v in value.items() if m in months}
                if kept:
                    by_month[str(inn)] = kept
            elif value is not None:
                by_month[str(inn)] = {months[-1]: value}
            # value is None -> the source did not know this client: no entry
        return MetricSeries(code=code, months=list(months), by_month=by_month, is_flat=flat)

    def present(self) -> set[str]:
        """Clients the source actually returned something for."""
        return set(self.by_month)

    def scalar(self, how: str = "mean") -> dict[str, Any]:
        """One value per client: the mean over the window for numbers, the
        latest known value for anything else (an attribute like ОКВЭД does
        not average)."""
        result: dict[str, Any] = {}
        for inn, series in self.by_month.items():
            values = [series[m] for m in self.months if m in series and series[m] is not None]
            if not values:
                result[inn] = None
                continue
            if how == "last" or not all(isinstance(v, (int, float)) for v in values):
                result[inn] = values[-1]
            else:
                result[inn] = sum(values) / len(values)
        return result

    def matrix(self) -> dict[str, list[float | None]]:
        """Per client, one entry per month of the window, in order.

        Months the source had no row for come back as None rather than 0.0,
        for the same reason `present()` exists.
        """
        out: dict[str, list[float | None]] = {}
        for inn, series in self.by_month.items():
            if self.is_flat:
                value = series.get(self.months[-1])
                out[inn] = [value] * len(self.months)
            else:
                out[inn] = [series.get(m) for m in self.months]
        return out


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


class DemoDataInProductionError(RuntimeError):
    """A metric that still returns bundled demo numbers was run for real.

    Every script in `metric_scripts/` ships as a stub reading
    `sample_data/attributes_reference.csv`. They are fine for a dry run and
    they are how the test suite works -- but the pilot's strata and its
    whole balance report are computed from whatever these return, so a
    production run against an unported script produces a split over
    fabricated attributes, a balance report over fabricated ЧОД, and an
    email saying the check PASSED. Nothing downstream can tell the
    difference, which makes a loud failure strictly better than a result.

    This is the failure mode most likely to bite a partially-ported script
    bank -- the realistic state, since the metrics get ported one at a
    time: ЧОД comes back real while ОКВЭД is still demo, and the split
    looks entirely plausible.

    Porting a script means querying the real mart and deleting its
    `DEMO_ONLY = True` marker. For a deliberate dry run with Spark
    switched on, set AB_SKILL_ALLOW_DEMO_DATA=true.
    """


def refuse_demo_script_in_production(
    metric_code: str, script_name: str, module, config: MetricScriptConfig
) -> None:
    if not config.use_spark:
        return
    if not getattr(module, "DEMO_ONLY", False):
        return
    if os.environ.get("AB_SKILL_ALLOW_DEMO_DATA", "false").strip().lower() == "true":
        return
    raise DemoDataInProductionError(
        f"metric '{metric_code}' ({script_name}) is still the bundled demo stub: it reads "
        "sample_data/attributes_reference.csv and ignores the SparkSession it is given. "
        "Running it now would put fabricated values into this pilot's strata and balance "
        "report, and the result would look valid. Port it to the real mart and delete its "
        "`DEMO_ONLY = True` line, drop the metric from the request, or set "
        "AB_SKILL_ALLOW_DEMO_DATA=true if you really do want demo numbers with Spark on."
    )


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
        """One value per client -- the scalar view, unchanged.

        A script returning a monthly series is reduced to the mean over the
        window, which is what a single-number caller wants anyway.
        """
        return self.run_series(metric_code, inn_list, as_of_date, filters=filters).scalar()

    def run_series(
        self,
        metric_code: str,
        inn_list: list[str],
        as_of_date: date,
        filters: dict[str, Any] | None = None,
        months: list[str] | None = None,
    ) -> MetricSeries:
        """The full monthly view: `{инн: {месяц: значение}}` plus who was found.

        `months` is the window to ask for. Scripts that accept a `months`
        argument get it; older ones are called with `as_of_date` alone and
        their flat answer is carried as a single-month series (see
        `MetricSeries.is_flat` -- a flat answer carries no history, and the
        skill must not invent one).
        """
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

        refuse_demo_script_in_production(metric_code, definition.script, module, self.config)

        window = list(months) if months else [f"{as_of_date.year:04d}-{as_of_date.month:02d}"]

        # The script contract grew twice: `filters` first, then `months`. Both
        # are passed only to scripts whose signature accepts them, so one bank
        # can hold scripts of all three generations. What is NOT allowed is
        # silently dropping something that was requested -- unfiltered numbers,
        # or a one-month answer presented as a six-month window, both look
        # perfectly valid and are both wrong.
        kwargs: dict[str, Any] = {"spark": spark}
        if script_accepts_filters(module.run):
            kwargs["filters"] = filters
        elif filters:
            raise TypeError(
                f"metric script {definition.script} does not accept a `filters` argument, "
                f"but filters {sorted(filters)} were requested for metric '{metric_code}'. "
                "Add `filters: dict | None = None` to its run() signature and apply them "
                "inside the query -- running it unfiltered would silently return the wrong numbers."
            )
        if script_accepts(module.run, "months"):
            kwargs["months"] = window

        raw = module.run(inn_list, as_of_date, **kwargs)
        return MetricSeries.from_script_output(metric_code, raw, window)

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

    def run_many_series(
        self,
        metric_codes: list[str],
        inn_list: list[str],
        as_of_date: date,
        filters: dict[str, Any] | None = None,
        months: list[str] | None = None,
    ) -> dict[str, MetricSeries]:
        """The monthly view of several metrics over one window."""
        return {
            code: self.run_series(
                code,
                inn_list,
                as_of_date,
                filters=self.filters_for(code, filters),
                months=months,
            )
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
