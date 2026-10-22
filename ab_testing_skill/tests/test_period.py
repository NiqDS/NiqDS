"""Period arithmetic: whole months, and the window a pilot is judged on."""
from datetime import date

import pytest

from skill.period import (
    DEFAULT_PRE_MONTHS,
    month_end,
    month_list,
    months_before,
    resolve_period,
    shift_month,
)


def test_months_before_excludes_the_month_the_pilot_starts_in():
    """A pilot starting 2026-07-10 is judged on January..June. July has
    barely begun and half a month is not a measurement."""
    window = months_before(date(2026, 7, 10), 6)
    assert window == ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]


def test_starting_on_the_first_is_the_same_case():
    assert months_before(date(2026, 7, 1), 3) == ["2026-04", "2026-05", "2026-06"]


def test_months_before_crosses_the_year_boundary():
    assert months_before(date(2026, 2, 15), 4) == ["2025-10", "2025-11", "2025-12", "2026-01"]


def test_a_window_of_zero_months_is_refused():
    with pytest.raises(ValueError):
        months_before(date(2026, 7, 1), 0)


@pytest.mark.parametrize(
    "month,delta,expected",
    [
        ("2026-03", 1, "2026-04"),
        ("2026-12", 1, "2027-01"),
        ("2026-01", -1, "2025-12"),
        ("2026-06", -18, "2024-12"),
        ("2026-06", 0, "2026-06"),
    ],
)
def test_shift_month(month, delta, expected):
    assert shift_month(month, delta) == expected


def test_month_end_handles_february_and_december():
    assert month_end(2026, 2) == date(2026, 2, 28)
    assert month_end(2024, 2) == date(2024, 2, 29)   # leap
    assert month_end(2026, 12) == date(2026, 12, 31)


def test_month_list_is_inclusive_at_both_ends():
    assert month_list(date(2026, 1, 15), date(2026, 3, 2)) == ["2026-01", "2026-02", "2026-03"]


# --- resolve_period --------------------------------------------------------

def test_boundaries_stretch_to_whole_months():
    """The marts hold one row per client per month, so "15.01 to 10.06" is
    not a period a query can express -- it is January..June."""
    period = resolve_period(date_from="2026-01-15", date_to="2026-06-10")
    assert period.start == date(2026, 1, 1)
    assert period.end == date(2026, 6, 30)
    assert len(period) == 6


@pytest.mark.parametrize(
    "text,first,last",
    [
        ("2026-01:2026-06", "2026-01", "2026-06"),
        ("2026-01..2026-06", "2026-01", "2026-06"),
        ("2026-Q2", "2026-04", "2026-06"),
        ("2026", "2026-01", "2026-12"),
        ("2026-03", "2026-03", "2026-03"),
    ],
)
def test_period_strings(text, first, last):
    period = resolve_period(period=text)
    assert period.months[0] == first
    assert period.months[-1] == last


def test_russian_date_format_is_understood():
    period = resolve_period(date_from="15.01.2026", date_to="10.06.2026")
    assert period.text == "2026-01:2026-06"


def test_one_boundary_means_one_month():
    assert resolve_period(date_from="2026-05-17").months == ["2026-05"]


def test_an_explicit_month_list_wins():
    period = resolve_period(months=["2026-03", "2026-01", "2026-02"])
    assert period.months == ["2026-01", "2026-02", "2026-03"]
    assert period.source == "months"


def test_the_default_is_the_last_complete_month():
    period = resolve_period(as_of=date(2026, 7, 5))
    assert period.months == ["2026-06"]
    period = resolve_period(as_of=date(2026, 1, 5))
    assert period.months == ["2025-12"]


def test_a_backwards_period_is_refused():
    with pytest.raises(ValueError) as exc_info:
        resolve_period(date_from="2026-06-01", date_to="2026-01-01")
    assert "раньше начала" in str(exc_info.value)


def test_an_unparseable_boundary_says_what_is_expected():
    with pytest.raises(ValueError) as exc_info:
        resolve_period(date_from="next tuesday")
    assert "2026-01" in str(exc_info.value)


def test_the_default_window_is_six_months():
    assert DEFAULT_PRE_MONTHS == 6
