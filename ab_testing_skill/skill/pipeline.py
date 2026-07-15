"""Orchestrates spec steps 1-5: intake validation through CG/TG + financial

effect delivery. Step 6 (recurring recalculation) lives in monitoring.py
since it runs on its own schedule against an already-created pilot folder.

This is the module a GigaCode tool/function wrapper should call --
`run_intake()` is the single entry point steps 1-5 hang off of.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .config import SkillConfig, default_config
from .connectors.dashboard_connector import DashboardConnector, LocalDropzoneDashboardConnector
from .connectors.email_connector import EmailConnector, LoggingEmailConnector, OutgoingEmail
from .exporter import write_financial_effect_file, write_group_file
from .inn_utils import validate_file
from .metrics.runner import MetricRunner
from .models import OverlapFinding, PilotRequest, PilotResult, ValidationIssue
from .registries import (
    DuplicatesRegistry,
    InvolvedInnsRegistry,
    MetricRequestRecord,
    MetricRequestsRegistry,
    OverlapRegistry,
    check_and_register,
    finalize_role,
)
from .splitter import split


class IntakeRejected(Exception):
    """Step 1 failed: the file is malformed or contains invalid INNs.

    Per spec: "агент пишет заказчику с просьбой переделать входной файл в
    нужном формате" -- the whole file is rejected, not just the bad rows,
    so the caller should relay `issues` back to the submitter verbatim.
    """

    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        super().__init__(f"{len(issues)} issue(s) found in the submitted INN file")


class NoEligibleClientsError(Exception):
    """Every submitted INN was already active in another pilot (step 2) --

    nothing left to split. Not explicitly covered by the spec; surfaced as
    its own exception rather than silently producing empty CG/TG files.
    """

    def __init__(self, blocked: list[OverlapFinding]):
        self.blocked = blocked
        super().__init__("no eligible INNs remain after the overlap check")


def build_default_connectors(config: SkillConfig) -> tuple[EmailConnector, DashboardConnector]:
    email = LoggingEmailConnector(config.storage.pilots_root / "_outbox")
    dashboard = LocalDropzoneDashboardConnector(config.storage.navigator_dropzone)
    return email, dashboard


def run_intake(
    request: PilotRequest,
    inn_file: Path,
    config: SkillConfig | None = None,
    email_connector: EmailConnector | None = None,
    dashboard_connector: DashboardConnector | None = None,
    strict_inn_checksum: bool = True,
) -> PilotResult:
    config = config or default_config()
    default_email, default_dashboard = build_default_connectors(config)
    email_connector = email_connector or default_email
    dashboard_connector = dashboard_connector or default_dashboard

    # --- Step 1: format + INN validity -----------------------------------
    validation = validate_file(Path(inn_file), check_control_digits=strict_inn_checksum)
    if validation.issues:
        raise IntakeRejected(validation.issues)

    pilot_folder = config.storage.pilots_root / request.slug()
    pilot_folder.mkdir(parents=True, exist_ok=True)

    # --- Step 2: dedupe against the "involved INNs" registry -------------
    involved = InvolvedInnsRegistry(config.registry.involved_inns_path)
    duplicates = DuplicatesRegistry(config.registry.duplicates_path)
    overlap = OverlapRegistry(config.registry.overlap_path)
    available, blocked = check_and_register(
        validation.valid_inns,
        request,
        involved,
        duplicates,
        overlap,
        blocking_roles=config.overlap.blocking_roles,
        require_metric_overlap=config.overlap.require_metric_overlap,
    )
    if blocked:
        report = _format_overlap_report(request, blocked)
        email_connector.send(
            OutgoingEmail(
                to=[config.notify.dev_team_email],
                subject=f"[AB pilot] overlap detected for '{request.pilot_name}'",
                body=report,
            )
        )
        email_connector.send(
            OutgoingEmail(
                to=[request.submitter_email],
                subject=f"Please review: {len(blocked)} client(s) already in another pilot",
                body=report,
            )
        )
    if not available:
        raise NoEligibleClientsError(blocked)

    # --- Step 3: log any custom-metric requests to the dev backlog -------
    if request.custom_metric_requests:
        metric_requests = MetricRequestsRegistry(config.registry.metric_requests_path)
        for text in request.custom_metric_requests:
            metric_requests.append(
                MetricRequestRecord(
                    no=0,
                    metric_text=text,
                    requested_by=request.submitter_email,
                    pilot_name=request.pilot_name,
                    report_date=date.today().isoformat(),
                )
            )

    # --- Step 4: compute grouping attributes, split, export, notify ------
    runner = MetricRunner(config.metrics)
    today = date.today()
    grouping_values = runner.run_many(request.grouping_metrics, available, today)
    financial_values = runner.run_many(request.financial_effect_articles, available, today)

    split_result = split(available, grouping_values, financial_values, config.split)

    control_path = write_group_file(pilot_folder, "control_group", split_result.control)
    target_path = write_group_file(pilot_folder, "target_group", split_result.target)

    for inn in split_result.control:
        finalize_role(involved, inn, request.pilot_name, "cg")
    for inn in split_result.target:
        finalize_role(involved, inn, request.pilot_name, "tg")

    email_connector.send(
        OutgoingEmail(
            to=request.recipient_emails or [request.submitter_email],
            subject=f"AB pilot '{request.pilot_name}': Control/Target groups ready",
            body=_format_result_summary(request, split_result),
            attachments=[control_path, target_path],
        )
    )

    # --- Step 5: financial-effect calc, Navigator handoff, dev + analytics package ---
    financial_effect_path = None
    if request.financial_effect_articles:
        group_of = {inn: "cg" for inn in split_result.control}
        group_of.update({inn: "tg" for inn in split_result.target})
        financial_effect_path = write_financial_effect_file(
            pilot_folder,
            today,
            financial_values,
            group_of,
            mode=config.storage.recalc_mode,
        )
        dashboard_connector.upload(request.slug(), financial_effect_path)

    package_attachments = [control_path, target_path]
    if financial_effect_path:
        package_attachments.append(financial_effect_path)
    package_body = _format_pilot_package(request, split_result)
    email_connector.send(
        OutgoingEmail(
            to=[config.notify.dev_team_email],
            subject=f"AB pilot '{request.pilot_name}': setup package",
            body=package_body,
            attachments=package_attachments,
        )
    )
    email_connector.send(
        OutgoingEmail(
            to=[config.notify.analytics_team_email],
            subject=f"AB pilot '{request.pilot_name}': analytics package",
            body=package_body,
            attachments=package_attachments,
        )
    )

    _write_pilot_meta(pilot_folder, request)

    return PilotResult(
        request=request,
        pilot_folder=str(pilot_folder),
        split=split_result,
        control_file=str(control_path),
        target_file=str(target_path),
        financial_effect_file=str(financial_effect_path) if financial_effect_path else None,
        duplicate_findings=blocked,
        rejected_inns=validation.issues,
    )


def _write_pilot_meta(pilot_folder: Path, request: PilotRequest) -> None:
    """Persists what monitoring.py needs to run step 6 without the original

    PilotRequest object in hand (a recalculation run is typically kicked
    off later, e.g. by cron, from just a pilot folder path).
    """
    meta = {
        "pilot_slug": request.slug(),
        "pilot_name": request.pilot_name,
        "valid_from": request.valid_from.isoformat(),
        "valid_to": request.valid_to.isoformat(),
        "recalculation_frequency": request.recalculation_frequency,
        "financial_effect_articles": request.financial_effect_articles,
        "grouping_metrics": request.grouping_metrics,
        "expected_effect_pct": request.expected_effect_pct,
        "submitter_email": request.submitter_email,
        "submitter_full_name": request.submitter_full_name,
        "recipient_emails": request.recipient_emails,
        "created_at": date.today().isoformat(),
    }
    (pilot_folder / "pilot_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _format_overlap_report(request: PilotRequest, blocked: list[OverlapFinding]) -> str:
    lines = [
        f"Pilot: {request.pilot_name} ({request.valid_from} .. {request.valid_to})",
        f"Submitted by: {request.submitter_full_name} <{request.submitter_email}>",
        "",
        f"{len(blocked)} client(s) already active in another pilot:",
    ]
    for f in blocked:
        lines.append(
            f"  - INN {f.inn}: currently in '{f.existing_pilot_name}' "
            f"({f.existing_valid_from} .. {f.existing_valid_to}); {f.suggestion}"
        )
    lines.append("")
    lines.append("Please confirm the client list is intentional, or send a corrected list.")
    return "\n".join(lines)


def _format_result_summary(request: PilotRequest, split_result) -> str:
    return "\n".join(
        [
            f"Pilot: {request.pilot_name} ({request.valid_from} .. {request.valid_to})",
            f"Control group: {len(split_result.control)} clients",
            f"Target group: {len(split_result.target)} clients",
            f"Financial balance check: {'PASSED' if split_result.balanced else 'NOT balanced within tolerance'} "
            f"(after {split_result.attempts_used} attempt(s))",
            "",
            "See attached control_group / target_group files (INN column renamed to 'codes').",
        ]
    )


def _format_pilot_package(request: PilotRequest, split_result) -> str:
    return "\n".join(
        [
            f"Pilot name: {request.pilot_name}",
            f"Term: {request.valid_from} .. {request.valid_to}",
            f"Recalculation frequency: {request.recalculation_frequency}",
            f"Requested by: {request.submitter_full_name} <{request.submitter_email}>",
            f"Expected effect: {request.expected_effect_pct}%",
            f"Grouping/split metrics: {', '.join(request.grouping_metrics) or '(none)'}",
            f"Financial effect articles measured: {', '.join(request.financial_effect_articles) or '(none)'}",
            f"Control group size: {len(split_result.control)}",
            f"Target group size: {len(split_result.target)}",
            f"Balance check: {'PASSED' if split_result.balanced else 'NOT balanced'} "
            f"(attempts: {split_result.attempts_used})",
        ]
    )
