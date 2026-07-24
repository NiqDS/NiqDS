"""The three prerequisite tables from the spec, plus a metric-request queue.

Backed by plain CSV files so the whole skill runs with zero external
services out of the box. Each registry class only exposes `load`/`append`,
so swapping in a real DB (Hive table, Postgres, whatever Sber uses) means
writing one new class with the same two methods -- nothing in
skill/pipeline.py needs to change.

Schemas are copied verbatim from the spec's "Пререквизиты" section, with
one documented addition: `role` on the involved-INNs table (CG/TG), needed
to implement the CG-is-always-reusable rule the spec flags as
"уточнить" -- see skill/config.py:OverlapConfig for the exact assumption.
"""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime
from pathlib import Path


ROLE_PENDING = "pending"  # placeholder role until the splitter (step 4) assigns cg/tg


def _ensure_file(path: Path, header: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(header)


def _next_no(path: Path) -> int:
    if not path.exists():
        return 1
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    return len(rows)  # header counts as row 0, so len(rows) == next 1-based no


@dataclass
class InvolvedInnRecord:
    no: int
    inn: str
    role: str  # "cg" | "tg" -- see module docstring
    pilot_name: str
    valid_from: str
    valid_to: str
    email_submitter: str
    report_date: str


@dataclass
class DuplicateRecord:
    no: int
    inn: str
    valid_from: str
    valid_to: str
    email_submitter_1: str
    email_submitter_2: str
    sub_date: str
    report_date: str


@dataclass
class OverlapRecord:
    no: int
    inn: str
    pilot_name: str
    valid_from: str
    valid_to: str
    measure: str
    action: str
    suggestion: str


class _CsvRegistry:
    record_cls: type
    path: Path

    def __init__(self, path: Path):
        self.path = Path(path)
        header = [f.name for f in fields(self.record_cls)]
        _ensure_file(self.path, header)

    def load(self) -> list:
        with open(self.path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [self.record_cls(**row) for row in reader]

    def append(self, record) -> None:
        no = _next_no(self.path)
        record.no = no
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[f.name for f in fields(self.record_cls)])
            writer.writerow(asdict(record))


class InvolvedInnsRegistry(_CsvRegistry):
    record_cls = InvolvedInnRecord


class DuplicatesRegistry(_CsvRegistry):
    record_cls = DuplicateRecord


class OverlapRegistry(_CsvRegistry):
    record_cls = OverlapRecord


@dataclass
class MetricRequestRecord:
    no: int
    metric_text: str
    requested_by: str
    pilot_name: str
    report_date: str


class MetricRequestsRegistry(_CsvRegistry):
    """Not in the original 3 prerequisite tables -- extends step 3's

    "если нужной проверки нет, агент спрашивает написать текст метрики, и
    она высылается команде разработки для добавления" into a queryable
    backlog for the dev team instead of a one-off email.
    """

    record_cls = MetricRequestRecord


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def suggest_resolution(overlapping_metrics: list[str], financial_effect_articles: list[str]) -> tuple[str, str]:
    """Very small rule-based suggestion engine for step 2's "перекрытие"

    handling. Returns (action, suggestion). Kept intentionally simple and
    isolated so the dev team can replace it with a real model/ruleset
    without touching the registry or pipeline code.
    """
    hits_financial_metric = any(m in financial_effect_articles for m in overlapping_metrics)
    if hits_financial_metric:
        return (
            "exclude_from_target",
            "client already measured on an overlapping financial-effect article in "
            "another active pilot -- replace with an alternate client rather than "
            "accepting the risk, or the new pilot's effect size will be biased",
        )
    return (
        "review_required",
        "client overlaps only on a grouping/segmentation metric, not a financial "
        "effect article -- acceptable to keep if the team documents the overlap, "
        "otherwise replace",
    )


def check_and_register(
    inn_list: list[str],
    request,  # PilotRequest, avoided import to prevent a cycle with models
    involved: InvolvedInnsRegistry,
    duplicates: DuplicatesRegistry,
    overlap: OverlapRegistry,
    blocking_roles: tuple[str, ...],
    require_metric_overlap: bool,
):
    """Step 2 of the spec.

    Returns (available_inns, blocked_findings) and has the side effect of
    appending new INNs to `involved`, logging conflicts to `duplicates` and
    `overlap`.
    """
    from .models import OverlapFinding  # local import to avoid a cycle

    existing_by_inn: dict[str, list[InvolvedInnRecord]] = {}
    for rec in involved.load():
        existing_by_inn.setdefault(rec.inn, []).append(rec)

    requested_metrics = set(request.grouping_metrics) | set(request.financial_effect_articles)
    available: list[str] = []
    blocked: list[OverlapFinding] = []
    report_date = date.today().isoformat()

    for inn in inn_list:
        records = existing_by_inn.get(inn, [])
        conflict_records = [
            r
            for r in records
            if r.role in blocking_roles and _parse_date(r.valid_to) >= request.valid_from
        ]
        if not conflict_records:
            available.append(inn)
            involved.append(
                InvolvedInnRecord(
                    no=0,
                    inn=inn,
                    role=ROLE_PENDING,  # filled in later by exporter.finalize_roles
                    pilot_name=request.pilot_name,
                    valid_from=request.valid_from.isoformat(),
                    valid_to=request.valid_to.isoformat(),
                    email_submitter=request.submitter_email,
                    report_date=report_date,
                )
            )
            continue

        for rec in conflict_records:
            overlapping = [m for m in requested_metrics]  # conservative: flag all requested metrics
            if require_metric_overlap and not overlapping:
                continue
            action, suggestion = suggest_resolution(overlapping, request.financial_effect_articles)
            duplicates.append(
                DuplicateRecord(
                    no=0,
                    inn=inn,
                    valid_from=rec.valid_from,
                    valid_to=rec.valid_to,
                    email_submitter_1=rec.email_submitter,
                    email_submitter_2=request.submitter_email,
                    sub_date=report_date,
                    report_date=report_date,
                )
            )
            overlap.append(
                OverlapRecord(
                    no=0,
                    inn=inn,
                    pilot_name=rec.pilot_name,
                    valid_from=rec.valid_from,
                    valid_to=rec.valid_to,
                    measure=",".join(overlapping),
                    action=action,
                    suggestion=suggestion,
                )
            )
            blocked.append(
                OverlapFinding(
                    inn=inn,
                    existing_pilot_name=rec.pilot_name,
                    existing_valid_from=_parse_date(rec.valid_from),
                    existing_valid_to=_parse_date(rec.valid_to),
                    overlapping_metrics=overlapping,
                    suggestion=f"{action}: {suggestion}",
                )
            )

    return available, blocked


VALID_INN_STATUSES = ("Used", "Unused", "Used_as_cg")


@dataclass
class InnStatusRecord:
    inn: str
    status: str  # one of VALID_INN_STATUSES
    pilot_name: str
    updated_date: str


class InnStatusRegistry:
    """NEW, not one of the original 3 prerequisite tables: a master

    current-status table, one row per INN, holding a single flag (Used /
    Unused / Used_as_cg). Requested separately from InvolvedInnsRegistry
    above and kept alongside it rather than replacing it -- this table
    answers "can this INN be used right now" with one upsertable flag;
    InvolvedInnsRegistry keeps the historical, date-ranged log of which
    pilot(s) an INN has actually participated in (needed for the
    overlap-suggestion engine and audit trail). See README "Assumptions"
    for how the two are kept in sync.

    Unlike the append-only `_CsvRegistry` tables, this one is upserted:
    each INN has exactly one row reflecting its current state.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        _ensure_file(self.path, [f.name for f in fields(InnStatusRecord)])

    def load(self) -> dict[str, InnStatusRecord]:
        with open(self.path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return {row["inn"]: InnStatusRecord(**row) for row in reader}

    def status_of(self, inn_list: list[str]) -> dict[str, str]:
        """Missing INNs default to "Unused" (never seen by the skill before)."""
        records = self.load()
        return {inn: records[inn].status if inn in records else "Unused" for inn in inn_list}

    def upsert_many(self, statuses: dict[str, str], pilot_name: str) -> None:
        for status in statuses.values():
            if status not in VALID_INN_STATUSES:
                raise ValueError(f"invalid INN status '{status}', expected one of {VALID_INN_STATUSES}")
        records = self.load()
        today = date.today().isoformat()
        for inn, status in statuses.items():
            records[inn] = InnStatusRecord(inn=inn, status=status, pilot_name=pilot_name, updated_date=today)
        header = [f.name for f in fields(InnStatusRecord)]
        with open(self.path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            for rec in records.values():
                writer.writerow(asdict(rec))


def check_master_status(
    inn_list: list[str],
    registry: InnStatusRegistry,
    blocking_statuses: tuple[str, ...],
) -> tuple[list[str], list[str]]:
    """NEW step, not in the original spec: gate the submitted list against

    the master status table before any other processing. Returns
    (available_inns, blocked_inns) -- blocked_inns is just a list of INN
    strings (the status table doesn't carry the richer per-pilot detail
    InvolvedInnsRegistry does, by design -- it's meant to be a fast,
    simple flag check).
    """
    statuses = registry.status_of(inn_list)
    available = [inn for inn in inn_list if statuses[inn] not in blocking_statuses]
    blocked = [inn for inn in inn_list if statuses[inn] in blocking_statuses]
    return available, blocked


def finalize_role(
    involved: InvolvedInnsRegistry, inn: str, pilot_name: str, role: str
) -> None:
    """Rewrites the placeholder role recorded during check_and_register once

    the split (step 4) has actually decided CG vs TG for this INN. CSV has
    no in-place update, so we rewrite the file -- fine at this table's
    expected size (thousands, not millions, of rows per pilot cycle).
    """
    rows = involved.load()
    changed = False
    for rec in rows:
        if rec.inn == inn and rec.pilot_name == pilot_name and rec.role == ROLE_PENDING:
            rec.role = role
            changed = True
            break
    if not changed:
        return
    header = [f.name for f in fields(InvolvedInnRecord)]
    with open(involved.path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for rec in rows:
            writer.writerow(asdict(rec))

