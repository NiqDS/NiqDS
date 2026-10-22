"""Subscriptions: where a metric reads from, and what its columns are called."""
import json
import os

import pytest

from metric_scripts.subscriptions import (
    ENV_VAR,
    LOCAL_PATH,
    SUBSCRIPTIONS_PATH,
    Subscription,
    get_subscription,
    list_subscriptions,
    reload_subscriptions,
    source_path,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    reload_subscriptions()
    yield
    reload_subscriptions()


def test_list_subscriptions_excludes_comment_keys():
    subs = list_subscriptions()
    assert subs
    assert "_comment" not in subs
    for entry in subs.values():
        assert isinstance(entry, Subscription)
        assert entry.tables, f"{entry.name} has no candidate table"


def test_a_subscription_names_its_columns_by_role():
    """Scripts ask for "the date column", not for a name: the same column is
    called something else in a replacement mart."""
    chod = get_subscription("chod")
    assert chod.column("inn")
    assert chod.column("date")
    assert chod.column("value")
    assert chod.option("period_type_value") == "M"


def test_missing_role_says_what_to_add():
    with pytest.raises(LookupError) as exc_info:
        get_subscription("chep").column("product")
    assert "product" in str(exc_info.value)
    assert "columns" in str(exc_info.value)


def test_unknown_alias_raises_with_helpful_message():
    with pytest.raises(KeyError) as exc_info:
        get_subscription("definitely_not_registered")
    assert "definitely_not_registered" in str(exc_info.value)
    assert "Known:" in str(exc_info.value)


def test_a_default_source_is_used_when_the_alias_is_not_registered():
    """A metric variant ('chod_by_product') reads the base source."""
    assert get_subscription("chod_by_product", default_source="chod").name == "chod"


# --- candidate tables ------------------------------------------------------

def test_resolve_picks_the_first_table_visible_to_the_session():
    """The same mart is exposed under different schemas to different teams,
    and which ones an analyst can see varies."""
    sub = Subscription(name="x", tables=["nope.one", "yes.two", "nope.three"])

    class FakeSpark:
        def table(self, name):
            if name != "yes.two":
                raise RuntimeError("Table or view not found")
            return type("DF", (), {"schema": {}})()

    assert sub.resolve(FakeSpark()) == "yes.two"


def test_resolve_without_a_session_takes_the_first_candidate():
    sub = Subscription(name="x", tables=["a.one", "b.two"])
    assert sub.resolve(None) == "a.one"


def test_resolve_says_so_when_nothing_is_visible():
    sub = Subscription(name="x", tables=["a.one", "b.two"])

    class Blind:
        def table(self, name):
            raise RuntimeError("no grant")

    with pytest.raises(LookupError) as exc_info:
        sub.resolve(Blind())
    assert "a.one" in str(exc_info.value) and "b.two" in str(exc_info.value)


def test_a_subscription_with_no_table_says_where_to_put_one():
    sub = Subscription(name="sdo", tables=[])
    with pytest.raises(LookupError) as exc_info:
        _ = sub.table
    assert "subscriptions.local.json" in str(exc_info.value)
    assert ENV_VAR in str(exc_info.value)


# --- keeping real names out of a public repository ------------------------

def test_the_committed_file_holds_no_real_mart_names():
    """This repository is public and a mart name cannot be un-pushed.

    The committed file is a template; the real names live in a gitignored
    local file or behind the environment variable.
    """
    raw = json.loads(SUBSCRIPTIONS_PATH.read_text(encoding="utf-8"))
    for name, entry in raw.items():
        if name.startswith("_") or not isinstance(entry, dict):
            continue
        for table in entry.get("tables") or [entry.get("table")]:
            if not table:
                continue
            assert table.startswith("example_db"), (
                f"{name} points at {table!r}; real mart names must go in "
                "subscriptions.local.json, which is gitignored"
            )


def test_the_local_override_is_gitignored():
    ignored = (SUBSCRIPTIONS_PATH.parent.parent / ".gitignore").read_text(encoding="utf-8")
    assert LOCAL_PATH.name in ignored


def test_the_environment_variable_wins_over_both(tmp_path, monkeypatch):
    custom = tmp_path / "subs.json"
    custom.write_text(
        json.dumps({"chod": {"table": "real_schema.real_table", "columns": {"inn": "inn_code"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv(ENV_VAR, str(custom))
    reload_subscriptions()
    assert source_path() == custom
    assert get_subscription("chod").table == "real_schema.real_table"
    assert get_subscription("chod").column("inn") == "inn_code"
