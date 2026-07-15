from datetime import date, timedelta

from skill.models import PilotRequest
from skill.registries import (
    DuplicatesRegistry,
    InvolvedInnRecord,
    InvolvedInnsRegistry,
    OverlapRegistry,
    check_and_register,
)


def _request(**overrides):
    defaults = dict(
        pilot_name="new_pilot",
        valid_from=date.today(),
        valid_to=date.today() + timedelta(days=60),
        submitter_email="submitter@bank.internal",
        submitter_full_name="Submitter Name",
        recipient_emails=[],
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
