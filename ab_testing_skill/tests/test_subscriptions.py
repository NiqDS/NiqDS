import pytest

from metric_scripts.subscriptions import get_subscription, list_subscriptions


def test_list_subscriptions_excludes_comment_key():
    subs = list_subscriptions()
    assert subs
    assert "_comment" not in subs
    for entry in subs.values():
        assert "table" in entry


def test_get_subscription_returns_table_name():
    subs = list_subscriptions()
    alias = next(iter(subs))
    assert get_subscription(alias) == subs[alias]["table"]


def test_get_subscription_unknown_alias_raises_with_helpful_message():
    with pytest.raises(KeyError) as exc_info:
        get_subscription("definitely_not_registered")
    assert "definitely_not_registered" in str(exc_info.value)
