"""Intermediate results, written as each metric finishes.

Ported from the metrics-calculation fork. The case for it is simple: a
metric is one query against a mart and takes minutes, and a pilot asks for
several. Collecting everything and writing at the end means a failure on
the last metric throws away every earlier query -- half an hour of cluster
time for nothing, and the operator has nothing to look at while deciding
what went wrong.

Each finished metric lands in `_staging/<metric>.csv` immediately. A run
that dies leaves the completed parts on disk, readable in Excel as they
are. A run that succeeds removes the folder unless asked to keep it.

CSV rather than parquet deliberately: no pandas, no pyarrow, and the file
can be opened by eye. The data is already aggregated to one row per client.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

__all__ = ["Staging", "STAGING_DIRNAME"]

STAGING_DIRNAME = "_staging"
_MANIFEST = "_metrics.json"


class Staging:
    """A folder of partial results for one run."""

    def __init__(self, output_dir: Path, dirname: str = STAGING_DIRNAME):
        self.root = Path(output_dir) / dirname
        self.saved: dict[str, Path] = {}

    def save(self, metric: str, months: list[str], values: dict[str, Any]) -> Path:
        """Write one metric's result. Called the moment it is computed."""
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{_safe_name(metric)}.csv"

        # Atomic: an interrupted write must not corrupt a result that was
        # already complete. Write beside the target, then rename.
        fd, tmp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        os.close(fd)
        try:
            with open(tmp, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["codes"] + list(months))
                for inn, series in sorted(values.items()):
                    if isinstance(series, dict):
                        writer.writerow([inn] + [series.get(month) for month in months])
                    else:
                        writer.writerow([inn] + [series] + [None] * (len(months) - 1))
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

        self.saved[metric] = path
        self._write_manifest()
        return path

    def _write_manifest(self) -> None:
        (self.root / _MANIFEST).write_text(
            json.dumps({k: v.name for k, v in self.saved.items()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self, metric: str) -> dict[str, dict[str, float]]:
        """Read a metric back, for resuming after a failure."""
        path = self.root / f"{_safe_name(metric)}.csv"
        if not path.exists():
            return {}
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        if not rows:
            return {}
        months = rows[0][1:]
        out: dict[str, dict[str, float]] = {}
        for row in rows[1:]:
            if not row:
                continue
            out[row[0]] = {
                month: float(value)
                for month, value in zip(months, row[1:])
                if value not in ("", None)
            }
        return out

    def completed(self) -> set[str]:
        """Metrics already on disk -- what a resumed run can skip."""
        if not self.root.exists():
            return set()
        return {p.stem for p in self.root.glob("*.csv")}

    def clear(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in str(name))[:80] or "metric"
