"""Loader for metric_scripts/subscriptions.json.

Keeps real table names out of individual metric scripts: add an entry to
subscriptions.json (alias -> real table name), then look it up by alias
from a script instead of hardcoding the table name inline:

    from metric_scripts.subscriptions import get_subscription
    table = get_subscription("chod_source")
    df = spark.table(table)...

Editing subscriptions.json (adding/renaming/repointing an alias) never
requires touching the scripts that use it.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SUBSCRIPTIONS_PATH = Path(__file__).resolve().parent / "subscriptions.json"


@lru_cache(maxsize=1)
def _load() -> dict[str, dict[str, str]]:
    with open(SUBSCRIPTIONS_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def list_subscriptions() -> dict[str, dict[str, str]]:
    """Returns the full alias -> {table, description} mapping."""
    return dict(_load())


def get_subscription(alias: str) -> str:
    """Returns the real table name registered for `alias`.

    Raises a clear KeyError (listing what *is* available) instead of
    letting a typo turn into a confusing Spark "table not found" error
    several frames deep in a metric script.
    """
    subscriptions = _load()
    if alias not in subscriptions:
        known = ", ".join(sorted(subscriptions)) or "(none registered)"
        raise KeyError(
            f"no subscription named '{alias}' in {SUBSCRIPTIONS_PATH}. "
            f"Known subscriptions: {known}"
        )
    return subscriptions[alias]["table"]
