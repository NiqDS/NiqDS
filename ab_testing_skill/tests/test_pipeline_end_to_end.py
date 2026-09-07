from datetime import date, timedelta
from pathlib import Path

import pytest

from skill.connectors.email_connector import LoggingEmailConnector
from skill.exporter import read_codes_file
from skill.models import PilotRequest
from skill.pipeline import IntakeRejected, NoEligibleClientsError, run_intake

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_INN_FILE = ROOT / "sample_data" / "sample_inn_input.csv"


def _request(**overrides):
    defaults = dict(
        pilot_name="e2e_pilot",
        valid_from=date.today(),
        valid_to=date.today() + timedelta(days=90),
        submitter_email="submitter@bank.internal",
        submitter_full_name="Submitter Name",
        recipient_emails=["submitter@bank.internal"],
        analyst_email="analyst@bank.internal",
        expected_effect_pct=5.0,
        recalculation_frequency="week",
        grouping_metrics=["okved", "opf"],
        financial_effect_articles=["chod", "revenue"],
    )
    defaults.update(overrides)
    return PilotRequest(**defaults)


def test_run_intake_produces_balanced_groups_and_notifies_everyone(scratch_config, tmp_path):
    outbox = LoggingEmailConnector(tmp_path / "outbox")
    result = run_intake(_request(), SAMPLE_INN_FILE, config=scratch_config, email_connector=outbox)

    assert result.split.control
    assert result.split.target
    assert set(result.split.control).isdisjoint(result.split.target)
    assert Path(result.control_file).exists()
    assert Path(result.target_file).exists()
    assert Path(result.pilot_folder, "pilot_meta.json").exists()

    recipients = {r for email in outbox.sent for r in email.to}
    assert "submitter@bank.internal" in recipients
    assert scratch_config.notify.dev_team_email in recipients
    assert scratch_config.notify.analytics_team_email in recipients

    analytics_emails = [e for e in outbox.sent if scratch_config.notify.analytics_team_email in e.to]
    assert analytics_emails
    assert "Grouping/split metrics" in analytics_emails[0].body
    assert "Financial effect articles measured" in analytics_emails[0].body

    # step 1a: the analyst gets exactly one email, with the raw inn file + request.json,
    # sent before any blocking/filtering -- not the same package the dev/analytics teams get.
    analyst_emails = [e for e in outbox.sent if e.to == ["analyst@bank.internal"]]
    assert len(analyst_emails) == 1
    attachment_names = {a.name for a in analyst_emails[0].attachments}
    assert attachment_names == {SAMPLE_INN_FILE.name, "request.json"}


def test_master_status_blocks_used_but_allows_used_as_cg_and_unused(scratch_config, tmp_path):
    from skill.registries import InnStatusRegistry

    used_inn, used_as_cg_inn, unseen_inn = "8319323530", "1346564387", "3319561976"

    status_reg = InnStatusRegistry(scratch_config.master_status.path)
    status_reg.upsert_many({used_inn: "Used", used_as_cg_inn: "Used_as_cg"}, pilot_name="other_pilot")

    with pytest.raises(NoEligibleClientsError):
        # a request containing ONLY the "Used" INN should be fully blocked at the master-status gate
        only_used = tmp_path / "only_used.csv"
        only_used.write_text(f"inn\n{used_inn}\n", encoding="utf-8")
        run_intake(
            _request(pilot_name="blocked_pilot"),
            only_used,
            config=scratch_config,
            email_connector=LoggingEmailConnector(tmp_path / "outbox_blocked"),
        )

    # "Used_as_cg" and a fresh/unseen INN should both go through fine
    inn_file = tmp_path / "inns.csv"
    inn_file.write_text(f"inn\n{used_inn}\n{used_as_cg_inn}\n{unseen_inn}\n", encoding="utf-8")
    result = run_intake(
        _request(pilot_name="mixed_pilot"),
        inn_file,
        config=scratch_config,
        email_connector=LoggingEmailConnector(tmp_path / "outbox_mixed"),
    )
    all_used = set(result.split.control) | set(result.split.target)
    assert used_inn not in all_used
    assert used_as_cg_inn in all_used
    assert unseen_inn in all_used

    # after the split, the master status table reflects the new roles
    updated = status_reg.load()
    assert updated[used_as_cg_inn].status in ("Used", "Used_as_cg")
    assert updated[unseen_inn].status in ("Used", "Used_as_cg")


def test_reusing_former_target_members_is_blocked_but_control_members_are_not(scratch_config, tmp_path):
    outbox = LoggingEmailConnector(tmp_path / "outbox")
    first = run_intake(
        _request(pilot_name="first_pilot"), SAMPLE_INN_FILE, config=scratch_config, email_connector=outbox,
    )
    assert first.split.target, "fixture split produced no target members to test against"

    # resubmit exactly the first pilot's TARGET members as a brand-new pilot's candidate list --
    # per the CG-is-always-reusable / TG-is-blocking-while-active assumption, none should be eligible.
    target_only_file = tmp_path / "target_only.csv"
    target_only_file.write_text("inn\n" + "\n".join(first.split.target) + "\n", encoding="utf-8")

    with pytest.raises(NoEligibleClientsError) as exc_info:
        run_intake(
            _request(pilot_name="second_pilot", financial_effect_articles=["chod"]),
            target_only_file,
            config=scratch_config,
            email_connector=LoggingEmailConnector(tmp_path / "outbox2"),
        )
    assert len(exc_info.value.blocked) == len(first.split.target)

    # but resubmitting the first pilot's CONTROL members should sail through untouched.
    control_only_file = tmp_path / "control_only.csv"
    control_only_file.write_text("inn\n" + "\n".join(first.split.control) + "\n", encoding="utf-8")
    third = run_intake(
        _request(pilot_name="third_pilot", grouping_metrics=["opf"], financial_effect_articles=["chod"]),
        control_only_file,
        config=scratch_config,
        email_connector=LoggingEmailConnector(tmp_path / "outbox3"),
    )
    assert sorted(third.split.control + third.split.target) == sorted(first.split.control)


def test_intake_rejected_on_malformed_inn(scratch_config, tmp_path):
    bad_file = tmp_path / "bad.csv"
    bad_file.write_text("inn\n12345\nnotanumber\n", encoding="utf-8")
    with pytest.raises(IntakeRejected) as exc_info:
        run_intake(_request(), bad_file, config=scratch_config)
    assert len(exc_info.value.issues) == 2
