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

    pre_months = getattr(request, "pre_months", 6)
    try:
        pre_months = int(pre_months)
    except (TypeError, ValueError):
        issues.append(RequestIssue("pre_months", "must be a whole number of months"))
    else:
        if not 1 <= pre_months <= 36:
            issues.append(
                RequestIssue(
                    "pre_months",
                    f"{pre_months} is outside 1..36. The groups are judged on this many whole "
                    "months of history; one month is comparing noise, and more than three years "
                    "of history is rarely loaded in the marts.",
                )
            )

    _check_split_method(getattr(request, "split_method", None), issues)

    if issues:
        raise RequestValidationError(issues)


def _check_split_method(decision, issues: list[RequestIssue]) -> None:
    """Validates the split-method questionnaire block, when there is one.

    Absent is allowed: requests submitted before the questionnaire existed
    (and hand-written ones) must keep working, and the pipeline falls back
    to the one-shot split that was the only behaviour then -- it says so in
    the setup package rather than deciding quietly.

    Present but unconfirmed is NOT allowed. The method determines whether
    the pilot is re-split wave by wave and whether comparability is
    re-checked each period; a pilot run under the wrong one cannot be
    repaired afterwards, so an answered-but-unconfirmed questionnaire is a
    half-finished intake, not a default.
    """
    if decision is None:
        return

    # Imported here, not at module scope: validation.py is deliberately
    # dependency-free so it can run in a browser-side port or a bare
    # environment, and this is the one check that needs the catalog.
    from .method_advisor import UnknownAnswerError, _collect_flags, methods

    known = set(methods())

    if decision.chosen and decision.chosen not in known:
        issues.append(
            RequestIssue(
                "split_method.chosen",
                f"unknown split method {decision.chosen!r}; known: {', '.join(sorted(known))}",
            )
        )
    if decision.recommended and decision.recommended not in known:
        issues.append(
            RequestIssue(
                "split_method.recommended",
                f"unknown split method {decision.recommended!r}; known: {', '.join(sorted(known))}",
            )
        )

    if decision.answers:
        try:
            _collect_flags(decision.answers)
        except UnknownAnswerError as exc:
            issues.append(RequestIssue("split_method.answers", str(exc)))

    if not decision.method:
        issues.append(
            RequestIssue(
                "split_method",
                "questionnaire block present but no method chosen -- run "
                "`python -m skill.cli advise-method` and record the answer",
            )
        )
        return

    if not decision.confirmed:
        issues.append(
            RequestIssue(
                "split_method.confirmed",
                "the submitter has not confirmed that the method's description fits this "
                f"pilot ({decision.method!r}). Show them the outline "
                "(`python -m skill.cli advise-method --describe "
                f"{decision.method}`) and record their answer; picking the wrong method "
                "cannot be corrected once the pilot has started",
            )
        )

    if decision.chosen and decision.recommended and decision.chosen != decision.recommended:
        if not decision.override_reason.strip():
            issues.append(
                RequestIssue(
                    "split_method.override_reason",
                    f"the recommendation was {decision.recommended!r} but {decision.chosen!r} "
                    "was chosen instead -- state why, so the analyst reading this pilot "
                    "later knows the deviation was deliberate",
                )
            )


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
