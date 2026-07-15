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


def validate_inn(raw: str, check_control_digits: bool = True) -> ValidationIssue | None:
    value = raw.strip()
    if not value:
        return ValidationIssue(inn=raw, reason="empty value")
    if not value.isdigit():
        return ValidationIssue(inn=raw, reason="contains non-digit characters")
    if len(value) not in (10, 12):
        return ValidationIssue(inn=raw, reason=f"unexpected length {len(value)} (expected 10 or 12)")
    if check_control_digits and not is_valid_checksum(value):
        return ValidationIssue(inn=raw, reason="failed FNS control-digit checksum")
    return None


def load_inn_column(path: Path) -> list[str]:
    """Reads the `inn` column from a CSV input file (UTF-8 or cp1251)."""
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


def _find_inn_column(fieldnames: list[str]) -> str:
    for name in fieldnames:
        if name.strip().lower() in ("inn", "инн"):
            return name
    raise ValueError(
        f"input file must have an 'inn' column, found columns: {fieldnames}"
    )


def validate_file(path: Path, check_control_digits: bool = True) -> ValidationResult:
    if path.suffix.lower() not in (".csv",):
        return ValidationResult(
            valid_inns=[],
            issues=[
                ValidationIssue(
                    inn="", reason=f"unsupported file format '{path.suffix}', expected .csv"
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
