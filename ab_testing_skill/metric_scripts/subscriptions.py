"""Loader for data-source subscriptions.

Keeps real table names out of metric scripts: a script asks for an alias,
this resolves it. Editing where a metric reads from never means touching
the script.

**Real internal table names do not belong in this file.** The committed
`subscriptions.json` holds placeholders and the structure; the real names
go in `subscriptions.local.json` beside it, which is gitignored, or in a
file named by `AB_SKILL_SUBSCRIPTIONS`. This repository is public, and a
mart name is internal infrastructure detail -- the sort of thing that is
trivially avoidable and permanently public once pushed.

Two things learned from the metrics-calculation fork are built in:

*A subscription may name several candidate tables.* The same mart is
exposed under different schemas to different teams, and which ones an
analyst can actually see varies. `resolve()` returns the first that exists,
so a script does not have to know whose grants it is running under.

*Column names are part of the subscription.* The same column is `inn`
in one mart and something else in another, and the period-type column is
`period_type` in one and `speriodtype` in its replacement. Scripts ask by
role -- "the date column" -- rather than by name.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

SUBSCRIPTIONS_PATH = Path(__file__).resolve().parent / "subscriptions.json"
LOCAL_PATH = Path(__file__).resolve().parent / "subscriptions.local.json"
ENV_VAR = "AB_SKILL_SUBSCRIPTIONS"

__all__ = [
    "Subscription",
    "get_subscription",
    "list_subscriptions",
    "reload_subscriptions",
    "source_path",
]


@dataclass
class Subscription:
    """One data source: where it is, what its columns are called, caveats."""

    name: str
    tables: list[str]
    columns: dict[str, str] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    @property
    def table(self) -> str:
        """The first candidate, for callers that cannot probe the cluster."""
        if not self.tables:
            raise LookupError(
                f"subscription '{self.name}' has no table configured. Add it to "
                f"{LOCAL_PATH.name} (gitignored) or set {ENV_VAR} to a file that has it."
            )
        return self.tables[0]

    def column(self, role: str, default: str | None = None) -> str:
        value = self.columns.get(role, default)
        if value is None:
            raise LookupError(
                f"subscription '{self.name}' does not say which column is '{role}'. "
                f"Add it under \"columns\" for this source."
            )
        return value

    def option(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)

    def resolve(self, spark: Any = None) -> str:
        """First candidate table that actually exists for this session.

        Without a Spark session there is nothing to probe, so the first
        candidate is returned and the caller finds out when the query runs.
        """
        if spark is None or len(self.tables) == 1:
            return self.table
        for candidate in self.tables:
            try:
                spark.table(candidate).schema
                return candidate
            except Exception:  # noqa: BLE001 - absence is the expected outcome
                continue
        raise LookupError(
            f"none of the tables for subscription '{self.name}' are visible to this "
            f"session: {', '.join(self.tables)}. Check the grants, or point the "
            f"subscription somewhere else in {LOCAL_PATH.name}."
        )

    def requires_table(self) -> bool:
        return bool(self.tables)


def source_path() -> Path:
    """Which file the subscriptions are being read from.

    Precedence: the environment variable, then the local override, then the
    committed placeholders. Reported in run logs so nobody has to guess
    which set of tables a run actually used.
    """
    override = os.environ.get(ENV_VAR)
    if override:
        return Path(override)
    if LOCAL_PATH.exists():
        return LOCAL_PATH
    return SUBSCRIPTIONS_PATH


@lru_cache(maxsize=4)
def _load(path_text: str) -> dict[str, Subscription]:
    path = Path(path_text)
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out: dict[str, Subscription] = {}
    for name, entry in raw.items():
        if name.startswith("_") or not isinstance(entry, dict):
            continue
        table = entry.get("table")
        tables = entry.get("tables") or ([table] if table else [])
        out[name] = Subscription(
            name=name,
            tables=[t for t in tables if t],
            columns=dict(entry.get("columns") or {}),
            options={
                k: v for k, v in entry.items()
                if k not in {"table", "tables", "columns", "note", "description"}
            },
            note=entry.get("note") or entry.get("description", ""),
        )
    return out


def reload_subscriptions() -> None:
    """Drop the cache, for a test or after editing the file in place."""
    _load.cache_clear()


def list_subscriptions() -> dict[str, Subscription]:
    return dict(_load(str(source_path())))


def get_subscription(name: str, default_source: str | None = None) -> Subscription:
    known = _load(str(source_path()))
    if name in known:
        return known[name]
    if default_source and default_source in known:
        return known[default_source]
    raise KeyError(
        f"unknown subscription '{name}'. Known: {', '.join(sorted(known)) or '(none)'}. "
        f"Reading from {source_path()}."
    )
