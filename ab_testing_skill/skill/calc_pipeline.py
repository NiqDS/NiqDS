"""Metrics-calculation product: IDs in, one Excel file of metrics out.

Second product on the same architecture as the AB-testing pipeline
(web form -> request.json + ID file -> CLI -> agent runs -> result file),
sharing the same metric_scripts bank, subscriptions.json and manifest.json.

What it deliberately does NOT do, in contrast to pipeline.run_intake():
no CG/TG split, no involved-INN or master-status registry writes, no
pilot folder or recurring recalculation. It is a read-only calculation --
running it must never change which clients are available for a pilot.
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import SkillConfig, default_config
from .connectors.email_connector import EmailConnector, LoggingEmailConnector, OutgoingEmail
from .exporter import write_metrics_result
from .inn_utils import validate_file
from .metrics.runner import MetricRunner
from .models import CalculationRequest, CalculationResult, ValidationIssue


class CalculationRejected(Exception):
    """The submitted ID file could not be used at all (bad format, no
    readable ID column, or -- unless drop_invalid_ids=True -- it contained
    IDs that failed validation)."""

    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        super().__init__(f"{len(issues)} issue(s) in the submitted ID file")


class NoMetricsSelectedError(Exception):
    """No metrics were selected, so there is nothing to calculate."""


def run_calculation(
    request: CalculationRequest,
    id_file: Path,
    config: SkillConfig | None = None,
    email_connector: EmailConnector | None = None,
    drop_invalid_ids: bool = False,
    strict_inn_checksum: bool = True,
) -> CalculationResult:
    config = config or default_config()
    if not request.metrics:
        raise NoMetricsSelectedError("select at least one metric to calculate")

    runner = MetricRunner(config.metrics)
    unknown = [m for m in request.metrics if m not in runner.manifest]
    if unknown:
        raise KeyError(
            f"unknown metric(s) {unknown} -- known metrics: {sorted(runner.manifest)}"
        )
    _validate_filters(runner, request)

    # --- Step 1: read + validate the uploaded ID list (.xlsx or .csv) ----
    validation = validate_file(Path(id_file), check_control_digits=strict_inn_checksum)
    if validation.issues and not drop_invalid_ids:
        raise CalculationRejected(validation.issues)
    if not validation.valid_inns:
        raise CalculationRejected(
            validation.issues
            or [ValidationIssue(inn="", reason="no IDs found in the submitted file")]
        )

    output_folder = config.calculation.results_root / request.slug()
    output_folder.mkdir(parents=True, exist_ok=True)
    (output_folder / "request.json").write_text(
        json.dumps(request.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # --- Step 2: run each selected metric over the ID list ---------------
    # Each script receives only the filters declared for it (see
    # MetricRunner.filters_for), and a script that can't apply a requested
    # filter raises rather than returning unfiltered numbers.
    as_of = request.effective_date()
    values = runner.run_many(request.metrics, validation.valid_inns, as_of, filters=request.filters)

    # --- Step 3: write the result workbook and report coverage -----------
    result_path = write_metrics_result(output_folder, as_of, validation.valid_inns, values)
    coverage = {
        metric: sum(1 for inn in validation.valid_inns if per_inn.get(inn) is not None)
        for metric, per_inn in values.items()
    }

    connector = email_connector or LoggingEmailConnector(config.calculation.results_root / "_outbox")
    connector.send(
        OutgoingEmail(
            to=request.recipient_emails or [request.submitter_email],
            subject=f"Расчёт метрик '{request.request_name}': результат",
            body=_format_summary(request, len(validation.valid_inns), coverage),
            attachments=[result_path],
        )
    )

    return CalculationResult(
        request=request,
        output_folder=str(output_folder),
        result_file=str(result_path),
        id_count=len(validation.valid_inns),
        coverage=coverage,
        rejected_ids=validation.issues,
    )


def _validate_filters(runner: MetricRunner, request: CalculationRequest) -> None:
    """Checks the filter selection against the bank's filters.json before

    anything expensive runs. A bank without filters.py skips the check.
    """
    if not request.filters:
        return
    try:
        filters_module = runner._import_script("filters.py")
    except ModuleNotFoundError:
        return
    filters_module.validate_selection(request.filters, request.metrics)


def _format_summary(request: CalculationRequest, id_count: int, coverage: dict[str, int]) -> str:
    lines = [
        f"Расчёт: {request.request_name}",
        f"Дата расчёта: {request.effective_date()}",
        f"Запросил: {request.submitter_full_name} <{request.submitter_email}>",
        f"ID в расчёте: {id_count}",
        f"Метрики: {', '.join(request.metrics)}",
        f"Фильтры: {request.filters or '(без фильтров)'}",
        "",
        "Заполненность (сколько ID получили значение):",
    ]
    for metric, filled in sorted(coverage.items()):
        share = f"{filled}/{id_count}"
        note = "  <-- пусто, проверьте фильтры и наличие ID в источнике" if filled == 0 else ""
        lines.append(f"  {metric}: {share}{note}")
    return "\n".join(lines)
