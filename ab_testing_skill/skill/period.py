"""Period arithmetic: a pilot's pre-period and the months it covers.

One place for the month maths the rest of the package needs. Adapted from
the metrics-calculation fork's `skill/period.py`, which got the central
rule right:

    **period boundaries always stretch to whole months.**

The marts hold one row per client per month, stamped on the last day of
that month, so "from 15.01 to 10.06" is not a thing a query can express --
it is January..June. Accepting a mid-month boundary and quietly rounding it
somewhere downstream is how two reports of "the same" period end up
disagreeing.

Why this exists at all: a balance check on a single `as_of_date` compares
one month of ЧОД, and one month of ЧОД for an ММБ client swings by tens of
percent. Comparing that is comparing noise. Everything the skill judges
groups on -- level, trend, cohort -- is computed over a window of months,
and this module is what turns a request into that window.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

__all__ = [
    "Period",
    "month_end",
    "month_list",
    "months_before",
    "parse_month",
    "resolve_period",
    "shift_month",
]

_FORMAT_HINT = (
    "ожидается дата 2026-01-31 / 31.01.2026, месяц 2026-01 или квартал 2026-Q1"
)

#: Default length of the pre-period a pilot is judged on, in months. Six is
#: the window the ЧОД matching methodology uses, and it is long enough that
#: one unusual month cannot carry the mean while short enough to stay inside
#: most clients' history.
DEFAULT_PRE_MONTHS = 6


@dataclass(frozen=True)
class Period:
    """A resolved window of whole months."""

    start: date  # first day of the first month
    end: date  # last day of the last month
    months: list[str]  # ['2026-01', '2026-02', ...]
    source: str  # which input produced it, for the run report

    @property
    def text(self) -> str:
        return f"{self.months[0]}:{self.months[-1]}"

    def describe(self) -> str:
        return f"{self.start.isoformat()} .. {self.end.isoformat()} ({len(self.months)} мес.)"

    def __len__(self) -> int:
        return len(self.months)


def month_end(year: int, month: int) -> date:
    first_of_next = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return first_of_next - timedelta(days=1)


def shift_month(month: str, delta: int) -> str:
    """'2026-03' shifted by delta months, as the same string form."""
    year, mon = parse_month(month)
    total = year * 12 + (mon - 1) + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def parse_month(month: str) -> tuple[int, int]:
    year, _, mon = str(month).partition("-")
    return int(year), int(mon)


def month_list(start: date, end: date) -> list[str]:
    """Inclusive at both ends."""
    months: list[str] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def months_before(anchor: date, count: int = DEFAULT_PRE_MONTHS) -> list[str]:
    """The `count` whole months ending with the month before `anchor`.

    The anchor's own month is excluded: a pilot starting on 2026-07-10 is
    judged on January..June, not on a July that has barely begun. A pilot
    starting on the 1st is the same case -- June is still the last complete
    month before it.
    """
    if count < 1:
        raise ValueError(f"pre-period must be at least one month, got {count}")
    last = f"{anchor.year:04d}-{anchor.month:02d}"
    last = shift_month(last, -1)
    return [shift_month(last, -(count - 1 - i)) for i in range(count)]


def _parse_point(raw: str | date, is_end: bool, field: str) -> tuple[int, int]:
    """'2026-05-17' | '2026-05' | '17.05.2026' | '2026-Q2' | '2026' -> (year, month)."""
    if isinstance(raw, date):
        return raw.year, raw.month

    text = str(raw).strip().upper().replace("/", "-").replace(" ", "")
    if not text:
        raise ValueError(f"{field}: пустое значение. {_FORMAT_HINT}")

    try:
        if "." in text:  # 17.05.2026
            _, month, year = text.split(".")
            if len(year) != 4:
                raise ValueError
            return int(year), int(month)

        parts = text.split("-")
        year = int(parts[0])
        if len(parts[0]) != 4:
            raise ValueError
        if len(parts) == 1:  # a bare year is the whole year
            return year, 12 if is_end else 1
        if parts[1].startswith("Q"):
            quarter = int(parts[1][1:])
            if not 1 <= quarter <= 4:
                raise ValueError
            return year, (quarter - 1) * 3 + (3 if is_end else 1)
        month = int(parts[1])
        if not 1 <= month <= 12:
            raise ValueError
        return year, month
    except (ValueError, IndexError):
        raise ValueError(f"{field}: не разобрано значение {raw!r}. {_FORMAT_HINT}") from None


def resolve_period(
    date_from: str | date | None = None,
    date_to: str | date | None = None,
    period: str | None = None,
    months: list[str] | None = None,
    as_of: date | None = None,
) -> Period:
    """Any supported way of naming a period, reduced to whole months.

    Priority: an explicit month list -> date_from/date_to -> a period
    string ('2026-01', '2026-01:2026-06', '2026-Q1') -> the last complete
    month before `as_of`.
    """
    if months:
        ordered = sorted(str(m) for m in months)
        first_y, first_m = parse_month(ordered[0])
        last_y, last_m = parse_month(ordered[-1])
        return Period(
            start=date(first_y, first_m, 1),
            end=month_end(last_y, last_m),
            months=ordered,
            source="months",
        )

    if date_from or date_to:
        source = "date_from/date_to"
        left = _parse_point(date_from or date_to, is_end=False, field="date_from")
        right = _parse_point(date_to or date_from, is_end=True, field="date_to")
    elif period:
        source = "period"
        text = str(period).strip().replace("..", ":")
        head, _, tail = text.partition(":")
        left = _parse_point(head, is_end=False, field="period")
        right = _parse_point(tail or head, is_end=True, field="period")
    else:
        source = "default"
        today = as_of or date.today()
        year, month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        left = right = (year, month)

    if right < left:
        raise ValueError(
            f"конец периода ({right[0]}-{right[1]:02d}) раньше начала "
            f"({left[0]}-{left[1]:02d})"
        )

    start = date(left[0], left[1], 1)
    end = month_end(right[0], right[1])
    return Period(start=start, end=end, months=month_list(start, end), source=source)
