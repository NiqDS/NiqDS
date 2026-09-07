"""Shared data structures passed between pipeline stages."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class Role(str, Enum):
    CONTROL = "cg"
    TARGET = "tg"


@dataclass
class ValidationIssue:
    inn: str
    reason: str


@dataclass
class ValidationResult:
    valid_inns: list[str]
    issues: list[ValidationIssue]

    @property
    def ok(self) -> bool:
        return not self.issues


@dataclass
class OverlapFinding:
    inn: str
    existing_pilot_name: str
    existing_valid_from: date
    existing_valid_to: date
    overlapping_metrics: list[str]
    suggestion: str


@dataclass
class OverlapCheckResult:
    available_inns: list[str]
    blocked: list[OverlapFinding]

    @property
    def has_blocked(self) -> bool:
        return bool(self.blocked)


@dataclass
class PilotRequest:
    """One intake form submission (what web/index.html produces as JSON)."""

    pilot_name: str
    valid_from: date
    valid_to: date
    submitter_email: str
    submitter_full_name: str
    recipient_emails: list[str]
    analyst_email: str  # the analyst who handles pilots; gets the raw inn_list + request only
    expected_effect_pct: float
    recalculation_frequency: str  # "day" | "week" | "month"
    grouping_metrics: list[str]  # e.g. ["okved", "opf", "tb", "tenure"]
    financial_effect_articles: list[str]  # metric codes used for $ effect calc
    custom_metric_requests: list[str] = field(default_factory=list)

    def slug(self) -> str:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.pilot_name)
        return f"{safe}_{self.valid_from.isoformat()}_{self.valid_to.isoformat()}"

    @staticmethod
    def from_dict(data: dict) -> "PilotRequest":
        """Parses the JSON bundle produced by web/index.html (or hand-written

        for CLI use). Dates are "YYYY-MM-DD" strings.
        """
        return PilotRequest(
            pilot_name=data["pilot_name"],
            valid_from=date.fromisoformat(data["valid_from"]),
            valid_to=date.fromisoformat(data["valid_to"]),
            submitter_email=data["submitter_email"],
            submitter_full_name=data["submitter_full_name"],
            recipient_emails=list(data.get("recipient_emails") or []),
            analyst_email=data["analyst_email"],
            expected_effect_pct=float(data["expected_effect_pct"]),
            recalculation_frequency=data["recalculation_frequency"],
            grouping_metrics=list(data.get("grouping_metrics") or []),
            financial_effect_articles=list(data.get("financial_effect_articles") or []),
            custom_metric_requests=list(data.get("custom_metric_requests") or []),
        )

    def to_dict(self) -> dict:
        """Inverse of from_dict() -- the same JSON shape web/index.html

        produces. Used to save/forward a copy of the raw submission (e.g.
        to the analyst of record; see pipeline.run_intake's step 1a).
        """
        return {
            "pilot_name": self.pilot_name,
            "valid_from": self.valid_from.isoformat(),
            "valid_to": self.valid_to.isoformat(),
            "submitter_email": self.submitter_email,
            "submitter_full_name": self.submitter_full_name,
            "recipient_emails": self.recipient_emails,
            "analyst_email": self.analyst_email,
            "expected_effect_pct": self.expected_effect_pct,
            "recalculation_frequency": self.recalculation_frequency,
            "grouping_metrics": self.grouping_metrics,
            "financial_effect_articles": self.financial_effect_articles,
            "custom_metric_requests": self.custom_metric_requests,
        }


@dataclass
class CalculationRequest:
    """One submission from web/metrics_calc.html.

    Deliberately much thinner than PilotRequest: this product just
    calculates the selected metrics for a list of IDs and hands back an
    Excel file. No CG/TG split, no pilot registry, no recurring
    recalculation -- so no pilot term, frequency, or expected effect.
    """

    request_name: str
    submitter_email: str
    submitter_full_name: str
    metrics: list[str]
    filters: dict = field(default_factory=dict)
    recipient_emails: list[str] = field(default_factory=list)
    as_of_date: date | None = None

    def effective_date(self) -> date:
        return self.as_of_date or date.today()

    def slug(self) -> str:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.request_name)
        return f"{safe}_{self.effective_date().isoformat()}"

    @staticmethod
    def from_dict(data: dict) -> "CalculationRequest":
        as_of = data.get("as_of_date")
        return CalculationRequest(
            request_name=data["request_name"],
            submitter_email=data["submitter_email"],
            submitter_full_name=data["submitter_full_name"],
            metrics=list(data.get("metrics") or []),
            filters=dict(data.get("filters") or {}),
            recipient_emails=list(data.get("recipient_emails") or []),
            as_of_date=date.fromisoformat(as_of) if as_of else None,
        )

    def to_dict(self) -> dict:
        return {
            "request_name": self.request_name,
            "submitter_email": self.submitter_email,
            "submitter_full_name": self.submitter_full_name,
            "metrics": self.metrics,
            "filters": self.filters,
            "recipient_emails": self.recipient_emails,
            "as_of_date": self.effective_date().isoformat(),
        }


@dataclass
class CalculationResult:
    request: CalculationRequest
    output_folder: str
    result_file: str
    id_count: int
    # metric code -> how many of the submitted IDs actually came back with a
    # value. Surfaced because "ran fine, every column blank" is otherwise a
    # silent failure (wrong filters, IDs absent from the source table, ...).
    coverage: dict[str, int] = field(default_factory=dict)
    rejected_ids: list[ValidationIssue] = field(default_factory=list)


@dataclass
class SplitResult:
    control: list[str]
    target: list[str]
    strata_summary: dict[str, dict[str, int]]
    balance_report: dict[str, dict[str, float]]
    attempts_used: int
    balanced: bool
    # recorded so a split can be reproduced/audited after the fact
    seed: int | None = None


@dataclass
class PilotResult:
    request: PilotRequest
    pilot_folder: str
    split: SplitResult
    control_file: str
    target_file: str
    financial_effect_file: str | None
    duplicate_findings: list[OverlapFinding]
    rejected_inns: list[ValidationIssue]
    # Д15: metric code -> how many of the split clients the reference data
    # actually resolved. Without this, INNs missing from the source silently
    # collapse into a single `None` stratum and never reach the balance
    # report, so the run looks clean while the split is effectively random.
    coverage: dict[str, int] = field(default_factory=dict)
