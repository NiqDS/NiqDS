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
