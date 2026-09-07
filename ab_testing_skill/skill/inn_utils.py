"""Step 1 of the spec: input list format + INN validity checks.

The spec only requires "digits only, no other characters" in the INN
column. We additionally verify the official FNS control-digit checksum
(10-digit legal entities, 12-digit individuals/sole proprietors) because a
digits-only check alone will happily accept a typo'd INN. This extra check
is a superset of what was asked and can be disabled via
`check_control_digits=False` if the business only wants the literal spec
behaviour.
"""
from __future__ import annotations

import csv
from pathlib import Path

from .models import ValidationIssue, ValidationResult

_WEIGHTS_10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_WEIGHTS_12_N1 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_WEIGHTS_12_N2 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _control_digit(digits: str, weights: tuple[int, ...]) -> int:
    total = sum(int(d) * w for d, w in zip(digits, weights))
    return (total % 11) % 10


def is_valid_checksum(inn: str) -> bool:
    if len(inn) == 10:
        return _control_digit(inn[:9], _WEIGHTS_10) == int(inn[9])
    if len(inn) == 12:
        n1_ok = _control_digit(inn[:10], _WEIGHTS_12_N1) == int(inn[10])
        n2_ok = _control_digit(inn[:11], _WEIGHTS_12_N2) == int(inn[11])
        return n1_ok and n2_ok
    return False


def _length_reason(value: str) -> str:
    """Д11: name the actual cause when the length is one digit short.

    By far the most common way a valid INN arrives at 9 or 11 digits is
    Excel: an all-digit cell is stored as a number, so a leading zero is
    dropped on save. Telling the submitter "unexpected length 9" sends them
    hunting for a data-quality problem that is really a formatting one, so
    the fix is spelled out instead.
    """
    base = f"unexpected length {len(value)} (expected 10 or 12)"
    if len(value) in (9, 11):
        return (
            f"{base} -- if this INN starts with 0, Excel dropped the leading zero when "
            f"the file was saved (0{value} would be {len(value) + 1} digits). Format the "
            "column as Text (Формат ячеек -> Текстовый) before saving, or export as CSV."
        )
    return base


def validate_inn(raw: str, check_control_digits: bool = True) -> ValidationIssue | None:
    value = raw.strip()
    if not value:
        return ValidationIssue(inn=raw, reason="empty value")
    if not value.isdigit():
        return ValidationIssue(inn=raw, reason="contains non-digit characters")
    if len(value) not in (10, 12):
        return ValidationIssue(inn=raw, reason=_length_reason(value))
    if check_control_digits and not is_valid_checksum(value):
        return ValidationIssue(inn=raw, reason="failed FNS control-digit checksum")
    return None


SUPPORTED_INPUT_SUFFIXES = (".csv", ".xlsx")


def load_inn_column(path: Path) -> list[str]:
    """Reads the `inn` column from a .csv (UTF-8 or cp1251) or .xlsx file."""
    if path.suffix.lower() == ".xlsx":
        return _load_inn_column_xlsx(path)
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            with open(path, newline="", encoding=encoding) as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    raise ValueError("empty file")
                col = _find_inn_column(reader.fieldnames)
                return [row[col] for row in reader]
        except UnicodeDecodeError:
            continue
    raise ValueError(f"could not decode {path} as utf-8 or cp1251")


def _load_inn_column_xlsx(path: Path) -> list[str]:
    """Reads the `inn` column from the first sheet of an .xlsx workbook.

    Excel stores all-digit IDs as numbers, so a 10-digit INN comes back as
    an int (and, if the cell was ever formatted as a float, as something
    like 8319323530.0). Both are normalised back to their digit string
    here rather than being reported as invalid downstream.
    """
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - exercised only without openpyxl
        raise ValueError(
            f"reading {path.name} requires openpyxl (pip install openpyxl), "
            "or supply the ID list as .csv instead"
        ) from exc

    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # BadZipFile, KeyError, openpyxl's own errors...
        # Mislabeled files are common (a .csv or .xls renamed to .xlsx), so
        # report it as a normal validation issue rather than a raw traceback.
        raise ValueError(
            f"{path.name} is not a readable .xlsx workbook ({type(exc).__name__}); "
            "re-save it as real Excel .xlsx, or submit the list as .csv"
        ) from exc
    sheet = workbook.active
    rows = sheet.iter_rows(values_only=True)
    try:
        header = next(rows)
    except StopIteration:
        raise ValueError("empty file") from None

    fieldnames = [str(c).strip() if c is not None else "" for c in header]
    col_index = fieldnames.index(_find_inn_column(fieldnames))
    values: list[str] = []
    for row in rows:
        if row is None or col_index >= len(row):
            continue
        values.append(_normalise_cell(row[col_index]))
    workbook.close()
    return values


def _normalise_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return _restore_leading_zero(str(int(value)))
    if isinstance(value, int):
        return _restore_leading_zero(str(value))
    return str(value).strip()


def _restore_leading_zero(digits: str) -> str:
    """Д11: put back the zero Excel dropped, but only when provably right.

    Only numeric cells reach here, so a 9- or 11-digit value cannot be a
    genuine INN -- it is one digit short. Zero-padding is applied only if
    the padded value passes the FNS checksum, which makes a wrong guess
    about a 1-in-10 proposition essentially impossible; anything else is
    left alone and reported by `validate_inn` with the explanation above.
    """
    if len(digits) in (9, 11):
        padded = "0" + digits
        if is_valid_checksum(padded):
            return padded
    return digits


def _find_inn_column(fieldnames: list[str]) -> str:
    for name in fieldnames:
        if name.strip().lower() in ("inn", "инн"):
            return name
    raise ValueError(
        f"input file must have an 'inn' column, found columns: {fieldnames}"
    )


def validate_file(path: Path, check_control_digits: bool = True) -> ValidationResult:
    if path.suffix.lower() not in SUPPORTED_INPUT_SUFFIXES:
        return ValidationResult(
            valid_inns=[],
            issues=[
                ValidationIssue(
                    inn="",
                    reason=(
                        f"unsupported file format '{path.suffix}', expected one of "
                        f"{', '.join(SUPPORTED_INPUT_SUFFIXES)}"
                    ),
                )
            ],
        )
    try:
        raw_values = load_inn_column(path)
    except ValueError as exc:
        return ValidationResult(valid_inns=[], issues=[ValidationIssue(inn="", reason=str(exc))])

    valid: list[str] = []
    issues: list[ValidationIssue] = []
    seen: set[str] = set()
    for raw in raw_values:
        issue = validate_inn(raw, check_control_digits=check_control_digits)
        if issue is not None:
            issues.append(issue)
            continue
        value = raw.strip()
        if value in seen:
            issues.append(ValidationIssue(inn=value, reason="duplicate within submitted file"))
            continue
        seen.add(value)
        valid.append(value)
    return ValidationResult(valid_inns=valid, issues=issues)
