"""Request validation that runs before anything with a side effect.

The audit's central safety point: a bad request used to be discovered
*after* the pilot folder was created, ~50 rows were appended to the
registry and notification emails had gone out -- because the only
validation lived in the browser, and `request.json` is edited by hand as a
matter of course. There is no rollback, so the cheapest fix is to fail
before the first write.

Everything here is pure: it reads the request and the metric manifest and
raises. It never touches the filesystem, the registries or email.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

VALID_FREQUENCIES = ("day", "week", "month")

# Deliberately permissive: this is a typo guard for internal corporate
# addresses, not an RFC 5322 implementation.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class RequestIssue:
    field: str
    reason: str


class RequestValidationError(Exception):
    """The request is unusable. Carries every problem found, not just the
    first, so the requester can fix them in one pass rather than one per
    round trip."""

    def __init__(self, issues: list[RequestIssue]):
        self.issues = issues
        summary = "; ".join(f"{i.field}: {i.reason}" for i in issues)
        super().__init__(f"{len(issues)} problem(s) with the request -- {summary}")


def _check_email(field: str, value: str, issues: list[RequestIssue]) -> None:
    if not value or not value.strip():
        issues.append(RequestIssue(field, "is required"))
    elif not _EMAIL_RE.match(value.strip()):
        issues.append(RequestIssue(field, f"does not look like an email address: {value!r}"))


def validate_pilot_request(request, known_metrics: set[str] | None = None) -> None:
    """Raises RequestValidationError if the pilot request can't be run.

    `known_metrics` is the set of codes in the manifest; when supplied,
    unknown metric codes are caught here rather than several steps later
    with the registry already written.
    """
    issues: list[RequestIssue] = []

    if not request.pilot_name or not request.pilot_name.strip():
        issues.append(RequestIssue("pilot_name", "is required"))

    if request.valid_from > request.valid_to:
        issues.append(
            RequestIssue(
                "valid_from/valid_to",
                f"pilot starts after it ends ({request.valid_from} > {request.valid_to})",
            )
        )

    _check_email("submitter_email", request.submitter_email, issues)
    _check_email("analyst_email", request.analyst_email, issues)
    for i, recipient in enumerate(request.recipient_emails or []):
        _check_email(f"recipient_emails[{i}]", recipient, issues)

    if request.recalculation_frequency not in VALID_FREQUENCIES:
        issues.append(
            RequestIssue(
                "recalculation_frequency",
                f"{request.recalculation_frequency!r} is not one of {VALID_FREQUENCIES} "
                "(an unrecognised value would silently fall back to daily when checking the schedule)",
            )
        )

    # Д4: a pilot with no financial-effect article produces CG/TG files, an
    # email saying the balance check PASSED, and no measurement at all.
    if not request.grouping_metrics:
        issues.append(RequestIssue("grouping_metrics", "select at least one attribute to split on"))
    if not request.financial_effect_articles:
        issues.append(
            RequestIssue(
                "financial_effect_articles",
                "select at least one article, otherwise the pilot has nothing to measure "
                "and the balance check is vacuously 'passed'",
            )
        )

    if known_metrics is not None:
        for field_name in ("grouping_metrics", "financial_effect_articles"):
            for code in getattr(request, field_name) or []:
                if code not in known_metrics:
                    issues.append(
                        RequestIssue(
                            field_name,
                            f"unknown metric {code!r}; known metrics: {', '.join(sorted(known_metrics))}",
                        )
                    )

    try:
        effect = float(request.expected_effect_pct)
    except (TypeError, ValueError):
        issues.append(RequestIssue("expected_effect_pct", "must be a number"))
    else:
        if effect <= 0:
            issues.append(
                RequestIssue("expected_effect_pct", f"must be positive, got {effect}")
            )

    if issues:
        raise RequestValidationError(issues)


def validate_calculation_request(request, known_metrics: set[str] | None = None) -> None:
    """Same guard for the metrics-calculation product."""
    issues: list[RequestIssue] = []

    if not request.request_name or not request.request_name.strip():
        issues.append(RequestIssue("request_name", "is required"))

    _check_email("submitter_email", request.submitter_email, issues)
    for i, recipient in enumerate(request.recipient_emails or []):
        _check_email(f"recipient_emails[{i}]", recipient, issues)

    if not request.metrics:
        issues.append(RequestIssue("metrics", "select at least one metric to calculate"))

    if known_metrics is not None:
        for code in request.metrics or []:
            if code not in known_metrics:
                issues.append(
                    RequestIssue(
                        "metrics",
                        f"unknown metric {code!r}; known metrics: {', '.join(sorted(known_metrics))}",
                    )
                )

    if issues:
        raise RequestValidationError(issues)
