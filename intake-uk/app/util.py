"""Pure, deterministic helpers shared by the rules engine and the extractor.

Nothing here touches a model, the network or the database. Everything is a
plain function over plain data so it can be unit-tested in isolation — which is
the whole point of the product.
"""

from __future__ import annotations

import re
from datetime import date

# ---------------------------------------------------------------------------
# UK VAT registration number
# ---------------------------------------------------------------------------


def normalise_vat(raw: str) -> str:
    """Uppercase, strip spaces and a leading ``GB`` country prefix."""

    v = re.sub(r"\s+", "", raw.upper())
    if v.startswith("GB"):
        v = v[2:]
    return v


def valid_uk_vat(raw: str | None) -> bool:
    """Return True if ``raw`` is a structurally valid UK VAT number.

    Accepts:
      * 9 digits (standard) — check-digit validated
      * 12 digits (9 + 3-digit branch suffix) — first 9 validated, suffix ignored
      * ``GD`` + 3 digits, range 000-499 (government departments) — format only
      * ``HA`` + 3 digits, range 500-999 (health authorities) — format only
      * optional ``GB`` prefix, optional spaces — normalised first

    The 9-digit check accepts both the classic "mod 97" variant and the newer
    "mod 9755" variant.
    """

    if raw is None:
        return False
    v = normalise_vat(raw)

    if v.startswith("GD"):
        rest = v[2:]
        return len(rest) == 3 and rest.isdigit() and 0 <= int(rest) <= 499
    if v.startswith("HA"):
        rest = v[2:]
        return len(rest) == 3 and rest.isdigit() and 500 <= int(rest) <= 999

    if not v.isdigit():
        return False
    if len(v) == 12:  # branch trader: validate the first 9, ignore the suffix
        v = v[:9]
    if len(v) != 9:
        return False

    d = [int(c) for c in v]
    s = 8 * d[0] + 7 * d[1] + 6 * d[2] + 5 * d[3] + 4 * d[4] + 3 * d[5] + 2 * d[6]
    check = d[7] * 10 + d[8]
    # classic ("mod 97") for older numbers, or "mod 9755" for newer numbers
    return (s + check) % 97 == 0 or (s + check + 55) % 97 == 0


# ---------------------------------------------------------------------------
# UK postcode
# ---------------------------------------------------------------------------

_POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$")


def valid_uk_postcode(raw: str | None) -> bool:
    if raw is None:
        return False
    return bool(_POSTCODE_RE.match(raw.upper().strip()))


# ---------------------------------------------------------------------------
# Sort code / account number
# ---------------------------------------------------------------------------


def digits_only(raw: str) -> str:
    return re.sub(r"\D", "", raw)


def valid_sort_code(raw: str | None) -> bool:
    if raw is None:
        return False
    return len(digits_only(raw)) == 6


def valid_account_number(raw: str | None) -> bool:
    if raw is None:
        return False
    return len(digits_only(raw)) == 8


# ---------------------------------------------------------------------------
# UK date parsing (deliberately DD/MM, with ambiguity detection)
# ---------------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b")


def _norm_year(y: int) -> int:
    if y < 100:
        return 2000 + y
    return y


def parse_uk_date(text: str | None) -> tuple[date | None, bool]:
    """Parse the first date found in ``text``.

    Returns ``(parsed_date_or_None, ambiguous)``.

    Numeric dates are read UK-style as ``DD/MM/YYYY``. ``ambiguous`` is True
    only when the token could *also* be read as a different, still-valid
    ``MM/DD`` date (e.g. ``03/04/2026`` — 3 April vs 4 March), so the caller can
    raise a WARN rather than guess silently. Textual months (``3 April 2026``)
    are never ambiguous.
    """

    if not text:
        return None, False

    # Textual month, either "3 April 2026" or "April 3, 2026".
    m = re.search(
        r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})\b", text
    )
    if m:
        day, mon, year = int(m.group(1)), m.group(2).lower()[:4], int(m.group(3))
        mon = mon if mon in _MONTHS else mon[:3]
        if mon in _MONTHS:
            try:
                return date(year, _MONTHS[mon], day), False
            except ValueError:
                return None, False
    m = re.search(
        r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})\b", text
    )
    if m:
        mon, day, year = m.group(1).lower()[:4], int(m.group(2)), int(m.group(3))
        mon = mon if mon in _MONTHS else mon[:3]
        if mon in _MONTHS:
            try:
                return date(year, _MONTHS[mon], day), False
            except ValueError:
                return None, False

    # ISO date.
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), False
        except ValueError:
            return None, False

    # Numeric DD/MM/YYYY (UK reading).
    m = _NUMERIC_DATE_RE.search(text)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), _norm_year(int(m.group(3)))
        uk = _safe_date(y, b, a)  # day=a, month=b
        us = _safe_date(y, a, b)  # day=b, month=a (the MM/DD alternative)
        if uk is None:
            # UK reading invalid; fall back to the US reading if it parses.
            return us, False
        ambiguous = us is not None and us != uk
        return uk, ambiguous

    return None, False


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Name normalisation (duplicate detection)
# ---------------------------------------------------------------------------


def normalise_name(name: str | None) -> str:
    if not name:
        return ""
    n = name.lower().strip()
    n = re.sub(r"[.,]", "", n)
    n = re.sub(r"\b(ltd|limited|plc|llp|inc|co)\b", "", n)
    n = re.sub(r"\s+", " ", n)
    return n.strip()
