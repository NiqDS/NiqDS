"""Step 4/5/6 of the spec: write the CG/TG files and the pilot's financial

effect workbook.

Uses `.xlsx` via openpyxl when it's installed (the realistic case, since
step 6 says the file is uploaded to Navigator as a dashboard source), and
transparently falls back to `.csv` with an identical column layout when it
isn't -- useful for environments where installing packages from PyPI isn't
possible. Callers should treat the return path's suffix as authoritative;
don't hardcode `.xlsx`.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any

try:
    from openpyxl import Workbook, load_workbook

    _HAS_OPENPYXL = True
except ImportError:  # pragma: no cover - exercised in restricted environments
    _HAS_OPENPYXL = False


#: Leading characters Excel/LibreOffice treat as the start of a formula.
#: A cell beginning with one of these is executed on open, so a value like
#: ``=cmd|'/c calc'!A1`` arriving from an uploaded list would run when the
#: analyst opens the exported workbook. Values are prefixed with an escape
#: sentinel on write and unprefixed again on read.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_ESCAPE_SENTINEL = "'"


def _escape_cell(value: Any) -> Any:
    """Neutralise spreadsheet formula injection (Д13).

    Only ever touches strings that start with a formula trigger; numbers,
    dates and None pass through untouched, so INNs (digits), report dates
    and metric values are unaffected. Negative numbers are safe because
    they arrive as numeric types, not as strings beginning with "-".
    """
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return _ESCAPE_SENTINEL + value
    return value


def _unescape_cell(value: Any) -> Any:
    """Inverse of `_escape_cell`, so append-mode round-trips are lossless."""
    if (
        isinstance(value, str)
        and value.startswith(_ESCAPE_SENTINEL)
        and value[1:].startswith(_FORMULA_PREFIXES)
    ):
        return value[1:]
    return value


def resolve_export_path(stem: Path) -> Path:
    """Path a given export lives at, keeping a pilot's extension stable (Д14).

    `_HAS_OPENPYXL` is an environment property, not a per-pilot one: if
    openpyxl gets installed (or removed) between the intake run and a later
    recalculation, a pilot that already has `financial_effect.csv` would
    start writing `financial_effect.xlsx` beside it. Everything downstream
    -- append mode, `read_codes_file`, the Navigator upload -- then reads
    one file while the other keeps growing. An existing file therefore wins
    over the environment's preference.
    """
    for suffix in (".xlsx", ".csv"):
        candidate = stem.with_suffix(suffix)
        if candidate.exists():
            return candidate
    return stem.with_suffix(".xlsx") if _HAS_OPENPYXL else stem.with_suffix(".csv")


def _write_rows(stem: Path, header: list[str], rows: list[list[Any]]) -> Path:
    stem.parent.mkdir(parents=True, exist_ok=True)
    path = resolve_export_path(stem)
    if path.suffix == ".xlsx" and not _HAS_OPENPYXL:
        raise RuntimeError(
            f"{path} already exists but openpyxl is not installed, so it cannot be "
            "updated. Install openpyxl (pip install openpyxl) rather than letting "
            "this pilot end up with both a .xlsx and a .csv export."
        )
    if path.suffix == ".xlsx":
        wb = Workbook()
        ws = wb.active
        ws.append(header)
        for row in rows:
            ws.append([_escape_cell(v) for v in row])
        _format_codes_column_as_text(ws, header)
        wb.save(path)
    else:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows([_escape_cell(v) for v in row] for row in rows)
    return path


def _format_codes_column_as_text(ws, header: list[str]) -> None:
    """Force the INN column to Excel's text format (Д11).

    Without this, an analyst who opens the export and re-saves it gets the
    codes back as numbers: leading zeros vanish (a 10-digit INN becomes 9
    digits) and long values can render as 8,31932E+09. Resubmitting that
    file then fails validation on rows that were perfectly valid on export.
    """
    if "codes" not in header:
        return
    col = header.index("codes") + 1
    for (cell,) in ws.iter_rows(min_row=2, min_col=col, max_col=col):
        cell.number_format = "@"


def _read_rows(path: Path) -> tuple[list[str], list[list[Any]]]:
    if path.suffix == ".xlsx":
        if not _HAS_OPENPYXL:
            raise RuntimeError(f"openpyxl not installed but found an existing .xlsx file at {path}")
        wb = load_workbook(path)
        ws = wb.active
        all_rows = list(ws.iter_rows(values_only=True))
        if not all_rows:
            return [], []
        header = [str(c) for c in all_rows[0]]
        body = [[_unescape_cell(c) for c in r] for r in all_rows[1:]]
        return header, body
    with open(path, newline="", encoding="utf-8") as f:
        all_rows = list(csv.reader(f))
    if not all_rows:
        return [], []
    return all_rows[0], [[_unescape_cell(c) for c in row] for row in all_rows[1:]]


def write_group_file(pilot_folder: Path, group_name: str, inn_list: list[str]) -> Path:
    """spec step 4: "агент ... переименовывает поле ИНН в codes, чтобы

    пересылка прошла" (internal-mail-safe export -- the raw `inn` column
    name is replaced with `codes`).
    """
    return _write_rows(pilot_folder / group_name, header=["codes"], rows=[[inn] for inn in inn_list])


def write_financial_effect_file(
    pilot_folder: Path,
    report_date: date,
    values: dict[str, dict[str, Any]],
    group_of: dict[str, str],
    mode: str = "append",
) -> Path:
    """spec step 5/6: per-article financial-effect results for the pilot,

    saved for upload to Navigator. See config.PilotStorageConfig.recalc_mode
    for the append-vs-overwrite assumption.

    Always includes a `stat_significance` column (statistical significance
    of the CG/TG difference on this pilot's effect). NEW, not in the
    original spec, and not computed yet -- every row gets `None`/NULL as a
    placeholder starting from the very first write; wire up the actual
    test (once there's enough data across report_dates to run one) by
    filling that column in here instead of hardcoding None.
    """
    stem = pilot_folder / "financial_effect"
    path = resolve_export_path(stem)
    articles = sorted(values.keys())
    header = ["report_date", "codes", "group"] + articles + ["stat_significance"]
    all_inns = sorted({inn for article_values in values.values() for inn in article_values})
    new_rows = [
        [report_date.isoformat(), inn, group_of.get(inn, "unknown")]
        + [values[article].get(inn) for article in articles]
        + [None]  # stat_significance placeholder -- see docstring
        for inn in all_inns
    ]

    rows = new_rows
    if mode == "append" and path.exists():
        existing_header, existing_rows = _read_rows(path)
        if existing_header and existing_header != header:
            raise ValueError(
                "financial effect schema changed between recalculations "
                f"(was {existing_header}, now {header}) -- refusing to append, "
                "this would break Navigator's column mapping for this pilot"
            )
        rows = existing_rows + new_rows
    elif mode not in ("append", "overwrite"):
        raise ValueError(f"unknown recalc_mode '{mode}', expected 'append' or 'overwrite'")

    return _write_rows(stem, header, rows)


def write_metrics_result(
    output_folder: Path,
    report_date: date,
    id_list: list[str],
    values: dict[str, dict[str, Any]],
) -> Path:
    """Result file for the metrics-calculation product: one row per

    submitted ID, one column per requested metric.

    Every submitted ID gets a row even when a metric returned nothing for
    it -- a blank cell is the signal that the ID wasn't found under the
    chosen filters, which silently dropping the row would hide.
    """
    metrics = sorted(values.keys())
    header = ["report_date", "codes"] + metrics
    rows = [
        [report_date.isoformat(), inn] + [values[metric].get(inn) for metric in metrics]
        for inn in id_list
    ]
    return _write_rows(output_folder / "metrics_result", header, rows)


def read_rows(path: Path) -> tuple[list[str], list[list[Any]]]:
    """Public wrapper around the internal xlsx/csv reader, for callers

    (monitoring.py) that need to inspect an existing export's rows.
    """
    return _read_rows(path)


def read_codes_file(stem: Path) -> list[str]:
    """Reads a group file written by `write_group_file` back into a plain

    list of INNs (the `codes` column). Used by monitoring.py to reload
    group membership on each recalculation pass.
    """
    path = resolve_export_path(stem)
    header, rows = _read_rows(path)
    if not header:
        return []
    idx = header.index("codes") if "codes" in header else 0
    return [str(row[idx]) for row in rows if row and row[idx] is not None]
