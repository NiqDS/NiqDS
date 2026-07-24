from datetime import date, timedelta

import pytest

from skill.models import PilotRequest
from skill.registries import (
    DuplicatesRegistry,
    InnStatusRegistry,
    InvolvedInnRecord,
    InvolvedInnsRegistry,
    OverlapRegistry,
    check_and_register,
    check_master_status,
)


def _request(**overrides):
    defaults = dict(
        pilot_name="new_pilot",
        valid_from=date.today(),
        valid_to=date.today() + timedelta(days=60),
        submitter_email="submitter@bank.internal",
        submitter_full_name="Submitter Name",
        recipient_emails=[],
        analyst_email="analyst@bank.internal",
        expected_effect_pct=5.0,
        recalculation_frequency="week",
        grouping_metrics=["okved"],
        financial_effect_articles=["chod"],
    )
    defaults.update(overrides)
    return PilotRequest(**defaults)


def test_new_inn_gets_registered_as_available(tmp_path):
    involved = InvolvedInnsRegistry(tmp_path / "involved.csv")
    duplicates = DuplicatesRegistry(tmp_path / "dup.csv")
    overlap = OverlapRegistry(tmp_path / "overlap.csv")

    available, blocked = check_and_register(
        ["1111111111"], _request(), involved, duplicates, overlap,
        blocking_roles=("tg",), require_metric_overlap=True,
    )
    assert available == ["1111111111"]
    assert blocked == []
    rows = involved.load()
    assert len(rows) == 1
    assert rows[0].role == "pending"


def test_active_tg_membership_blocks_reuse(tmp_path):
    involved = InvolvedInnsRegistry(tmp_path / "involved.csv")
    duplicates = DuplicatesRegistry(tmp_path / "dup.csv")
    overlap = OverlapRegistry(tmp_path / "overlap.csv")

    involved.append(InvolvedInnRecord(
        no=0, inn="2222222222", role="tg", pilot_name="running_pilot",
        valid_from=date.today().isoformat(),
        valid_to=(date.today() + timedelta(days=30)).isoformat(),
        email_submitter="someone@bank.internal", report_date=date.today().isoformat(),
    ))

    available, blocked = check_and_register(
        ["2222222222"], _request(), involved, duplicates, overlap,
        blocking_roles=("tg",), require_metric_overlap=True,
    )
    assert available == []
    assert len(blocked) == 1
    assert blocked[0].existing_pilot_name == "running_pilot"
    assert duplicates.load()
    assert overlap.load()


def test_cg_membership_never_blocks_reuse(tmp_path):
    """ASSUMPTION documented in config.OverlapConfig: prior CG membership

    doesn't block reuse in either role -- only active TG membership does.
    """
    involved = InvolvedInnsRegistry(tmp_path / "involved.csv")
    duplicates = DuplicatesRegistry(tmp_path / "dup.csv")
    overlap = OverlapRegistry(tmp_path / "overlap.csv")

    involved.append(InvolvedInnRecord(
        no=0, inn="3333333333", role="cg", pilot_name="running_pilot",
        valid_from=date.today().isoformat(),
        valid_to=(date.today() + timedelta(days=30)).isoformat(),
        email_submitter="someone@bank.internal", report_date=date.today().isoformat(),
    ))

    available, blocked = check_and_register(
        ["3333333333"], _request(), involved, duplicates, overlap,
        blocking_roles=("tg",), require_metric_overlap=True,
    )
    assert available == ["3333333333"]
    assert blocked == []


def test_expired_pilot_membership_frees_the_inn(tmp_path):
    involved = InvolvedInnsRegistry(tmp_path / "involved.csv")
    duplicates = DuplicatesRegistry(tmp_path / "dup.csv")
    overlap = OverlapRegistry(tmp_path / "overlap.csv")

    involved.append(InvolvedInnRecord(
        no=0, inn="4444444444", role="tg", pilot_name="old_pilot",
        valid_from=(date.today() - timedelta(days=100)).isoformat(),
        valid_to=(date.today() - timedelta(days=10)).isoformat(),
        email_submitter="someone@bank.internal", report_date=date.today().isoformat(),
    ))

    available, blocked = check_and_register(
        ["4444444444"], _request(valid_from=date.today()), involved, duplicates, overlap,
        blocking_roles=("tg",), require_metric_overlap=True,
    )
    assert available == ["4444444444"]
    assert blocked == []


def test_inn_status_registry_defaults_unseen_inns_to_unused(tmp_path):
    reg = InnStatusRegistry(tmp_path / "status.csv")
    assert reg.status_of(["9999999999"]) == {"9999999999": "Unused"}


def test_inn_status_registry_upsert_overwrites_previous_status(tmp_path):
    reg = InnStatusRegistry(tmp_path / "status.csv")
    reg.upsert_many({"1234567890": "Used"}, pilot_name="pilot_a")
    assert reg.status_of(["1234567890"]) == {"1234567890": "Used"}
    reg.upsert_many({"1234567890": "Used_as_cg"}, pilot_name="pilot_b")
    assert reg.status_of(["1234567890"]) == {"1234567890": "Used_as_cg"}
    # upsert must not duplicate rows
    assert len(reg.load()) == 1


def test_inn_status_registry_rejects_invalid_status(tmp_path):
    reg = InnStatusRegistry(tmp_path / "status.csv")
    with pytest.raises(ValueError):
        reg.upsert_many({"1234567890": "Definitely_Not_A_Real_Status"}, pilot_name="pilot_a")


def test_check_master_status_splits_available_and_blocked(tmp_path):
    reg = InnStatusRegistry(tmp_path / "status.csv")
    reg.upsert_many({"1111111111": "Used", "2222222222": "Used_as_cg"}, pilot_name="pilot_a")
    available, blocked = check_master_status(
        ["1111111111", "2222222222", "3333333333"], reg, blocking_statuses=("Used",)
    )
    assert available == ["2222222222", "3333333333"]
    assert blocked == ["1111111111"]
