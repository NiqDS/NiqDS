"""The split-method questionnaire: decision rules, the confirmation gate,
and the reminders a rebase-requiring pilot leaves behind."""
from datetime import date, timedelta
from pathlib import Path

import pytest

from skill import method_advisor
from skill.connectors.email_connector import LoggingEmailConnector
from skill.models import PilotRequest, SplitMethodDecision
from skill.monitoring import (
    HOMOGENEITY_FILENAME,
    latest_homogeneity_check,
    run_homogeneity_check,
    run_recalculation,
)
from skill.pipeline import REBASE_NOTE_FILENAME, resolve_method_plan, run_intake
from skill.registries import RebaseRemindersRegistry
from skill.validation import RequestValidationError, validate_pilot_request

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_INN_FILE = ROOT / "sample_data" / "sample_inn_input.csv"

STABLE = {
    "entry_timing": "all_at_once",
    "list_growth": "closed",
    "segment_drift": "stable",
    "attrition": "minimal",
    "treatment_levels": "single_treatment",
}


def _answers(**overrides) -> dict[str, str]:
    answers = dict(STABLE)
    answers.update(overrides)
    return answers


def _request(**overrides) -> PilotRequest:
    defaults = dict(
        pilot_name="method_pilot",
        valid_from=date.today(),
        valid_to=date.today() + timedelta(days=90),
        submitter_email="submitter@bank.internal",
        submitter_full_name="Submitter Name",
        recipient_emails=[],
        analyst_email="analyst@bank.internal",
        expected_effect_pct=5.0,
        recalculation_frequency="month",
        grouping_metrics=["okved"],
        financial_effect_articles=["chod"],
    )
    defaults.update(overrides)
    return PilotRequest(**defaults)


def _confirmed(method: str, recommended: str | None = None, reason: str = "") -> SplitMethodDecision:
    return SplitMethodDecision(
        answers=_answers(),
        recommended=recommended or method,
        chosen=method,
        confirmed=True,
        override_reason=reason,
    )


# --- the decision rules ----------------------------------------------------

def test_closed_short_stable_pilot_needs_no_rebase():
    rec = method_advisor.recommend(_answers(), iterations=3)
    assert rec.method == "single"
    assert rec.rebase_required is False
    assert rec.homogeneity_recheck_required is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"entry_timing": "in_waves"},
        {"list_growth": "will_grow"},
        {"entry_timing": "in_waves", "list_growth": "will_grow"},
    ],
)
def test_a_growing_pilot_gets_the_cascade_method(overrides):
    """Anything that adds clients after the start forces wave-by-wave splitting."""
    rec = method_advisor.recommend(_answers(**overrides), iterations=3)
    assert rec.method == "cascade_rebase"
    assert rec.rebase_required is True
    assert rec.homogeneity_recheck_required is True
    assert rec.requires_from_user, "the cascade method has to state what it needs each wave"


@pytest.mark.parametrize(
    "overrides", [{"segment_drift": "will_drift"}, {"attrition": "expected"}]
)
def test_a_closed_pilot_that_can_lose_comparability_is_monitored_not_resplit(overrides):
    """Membership is frozen, so the baseline is rebased -- never the groups.

    Re-splitting here would move an already-treated client into control.
    """
    rec = method_advisor.recommend(_answers(**overrides), iterations=3)
    assert rec.method == "single_monitored"
    assert rec.homogeneity_recheck_required is True
    assert "НЕ переразделяется" in " ".join(rec.outline)


def test_a_long_pilot_is_monitored_even_when_every_answer_says_nothing_changes():
    """The term and cadence are on the form already, so this is computed."""
    assert method_advisor.recommend(_answers(), iterations=3).method == "single"
    assert method_advisor.recommend(_answers(), iterations=12).method == "single_monitored"


def test_unknown_answers_lean_to_the_cascade_method_and_say_which_ones_did():
    rec = method_advisor.recommend(_answers(list_growth="unknown"), iterations=3)
    assert rec.method == "cascade_rebase"
    assert len(rec.unknown_answers) == 1
    assert "пополняться" in rec.unknown_answers[0]


def test_nested_treatment_levels_are_a_modifier_not_a_different_method():
    rec = method_advisor.recommend(_answers(treatment_levels="multiple_levels"), iterations=3)
    assert rec.method == "single"
    assert rec.modifiers and "внутри тех же однородных подгрупп" in rec.modifiers[0]


def test_every_question_offers_an_unknown_option():
    """An inexperienced submitter is the whole point; "I don't know" must exist."""
    for question in method_advisor.questions():
        assert any(o.get("unknown") for o in question["options"]), question["id"]


def test_unrecognised_answers_are_rejected_rather_than_ignored():
    with pytest.raises(method_advisor.UnknownAnswerError):
        method_advisor.recommend({"no_such_question": "x"})
    with pytest.raises(method_advisor.UnknownAnswerError):
        method_advisor.recommend(_answers(entry_timing="maybe_later"))


def test_expected_iterations_from_the_pilot_term():
    assert method_advisor.expected_iterations(date(2026, 1, 1), date(2026, 12, 31), "month") == 12
    assert method_advisor.expected_iterations(date(2026, 1, 1), date(2026, 2, 1), "month") == 1
    assert method_advisor.expected_iterations(date(2026, 1, 1), date(2026, 3, 1), "week") == 8


def test_the_recommendation_text_contains_what_the_user_has_to_judge():
    text = method_advisor.recommend(_answers(entry_timing="in_waves"), iterations=6).as_text()
    for expected in ("Рекомендуемый метод", "Как это будет работать", "Похоже это на ваш пилот"):
        assert expected in text


# --- the confirmation gate -------------------------------------------------

def test_a_request_with_no_questionnaire_still_runs():
    """Every request.json written before this feature existed must keep working."""
    validate_pilot_request(_request(), known_metrics={"okved", "chod"})


def test_an_unconfirmed_method_is_refused():
    request = _request(
        split_method=SplitMethodDecision(
            answers=_answers(), recommended="cascade_rebase", chosen="cascade_rebase"
        )
    )
    with pytest.raises(RequestValidationError) as exc_info:
        validate_pilot_request(request, known_metrics={"okved", "chod"})
    assert any(i.field == "split_method.confirmed" for i in exc_info.value.issues)


def test_overriding_the_recommendation_requires_a_reason():
    request = _request(split_method=_confirmed("single", recommended="cascade_rebase"))
    with pytest.raises(RequestValidationError) as exc_info:
        validate_pilot_request(request, known_metrics={"okved", "chod"})
    assert any(i.field == "split_method.override_reason" for i in exc_info.value.issues)

    request = _request(
        split_method=_confirmed("single", recommended="cascade_rebase", reason="отдельные пилоты")
    )
    validate_pilot_request(request, known_metrics={"okved", "chod"})


def test_an_unknown_method_name_is_refused():
    request = _request(split_method=_confirmed("cascade_with_sprinkles"))
    with pytest.raises(RequestValidationError) as exc_info:
        validate_pilot_request(request, known_metrics={"okved", "chod"})
    assert any(i.field == "split_method.chosen" for i in exc_info.value.issues)


def test_the_decision_survives_the_request_json_round_trip():
    request = _request(split_method=_confirmed("cascade_rebase"))
    restored = PilotRequest.from_dict(request.to_dict())
    assert restored.split_method.chosen == "cascade_rebase"
    assert restored.split_method.confirmed is True
    assert restored.split_method.answers == _answers()


def test_a_request_without_the_questionnaire_is_reported_as_not_assessed():
    """Not the same as a deliberate "no rebase" -- nobody judged this pilot."""
    plan = resolve_method_plan(_request())
    assert plan.method == "single"
    assert plan.source == "not_assessed"


# --- what a rebase-requiring pilot leaves behind ---------------------------

def test_cascade_pilot_writes_the_note_the_reminder_row_and_the_meta_flags(
    scratch_config, tmp_path
):
    outbox = LoggingEmailConnector(tmp_path / "outbox")
    result = run_intake(
        _request(pilot_name="cascade_pilot", split_method=_confirmed("cascade_rebase")),
        SAMPLE_INN_FILE,
        config=scratch_config,
        email_connector=outbox,
    )
    folder = Path(result.pilot_folder)

    assert result.split_method == "cascade_rebase"
    assert result.rebase_required is True

    note = (folder / REBASE_NOTE_FILENAME).read_text(encoding="utf-8")
    assert "требует ребейза" in note
    assert "Состав групп не переразделять" in note
    assert "Новая партия клиентов распределяется отдельной волной" in note

    import json

    meta = json.loads((folder / "pilot_meta.json").read_text(encoding="utf-8"))
    assert meta["split_method"] == "cascade_rebase"
    assert meta["rebase_required"] is True
    assert meta["homogeneity_recheck_required"] is True
    assert meta["split_method_confirmed"] is True
    assert meta["split_method_answers"] == _answers()

    reminders = RebaseRemindersRegistry(scratch_config.registry.rebase_reminders_path).load()
    assert len(reminders) == 1
    assert reminders[0].pilot_slug == result.request.slug()
    assert reminders[0].homogeneity_recheck == "yes"

    # and the reminder reaches the people who get the files
    delivery = [e for e in outbox.sent if "Control/Target groups ready" in e.subject]
    assert "НЕ являются окончательным составом групп" in delivery[0].body


def test_a_one_shot_pilot_leaves_no_rebase_note_or_reminder(scratch_config, tmp_path):
    result = run_intake(
        _request(pilot_name="single_pilot", split_method=_confirmed("single")),
        SAMPLE_INN_FILE,
        config=scratch_config,
        email_connector=LoggingEmailConnector(tmp_path / "outbox"),
    )
    assert not (Path(result.pilot_folder) / REBASE_NOTE_FILENAME).exists()
    assert RebaseRemindersRegistry(scratch_config.registry.rebase_reminders_path).load() == []


def test_the_reminders_table_answers_what_is_due_now(scratch_config, tmp_path):
    run_intake(
        _request(pilot_name="due_pilot", split_method=_confirmed("cascade_rebase")),
        SAMPLE_INN_FILE,
        config=scratch_config,
        email_connector=LoggingEmailConnector(tmp_path / "outbox"),
    )
    reminders = RebaseRemindersRegistry(scratch_config.registry.rebase_reminders_path)
    assert reminders.due_on(date.today()) == []  # first period has not elapsed yet
    assert len(reminders.due_on(date.today() + timedelta(days=31))) == 1
    # ...and not after the pilot has ended
    assert reminders.due_on(date.today() + timedelta(days=365)) == []


def test_the_setup_package_flags_a_pilot_nobody_assessed(scratch_config, tmp_path):
    outbox = LoggingEmailConnector(tmp_path / "outbox")
    run_intake(
        _request(pilot_name="unassessed_pilot"),
        SAMPLE_INN_FILE,
        config=scratch_config,
        email_connector=outbox,
    )
    package = [e for e in outbox.sent if "analytics package" in e.subject][0].body
    assert "questionnaire was not filled in" in package


# --- the per-period comparability re-check --------------------------------

def test_recalculation_re_checks_comparability_only_when_the_method_says_to(
    scratch_config, tmp_path
):
    cascade = run_intake(
        _request(pilot_name="recheck_pilot", split_method=_confirmed("cascade_rebase")),
        SAMPLE_INN_FILE,
        config=scratch_config,
        email_connector=LoggingEmailConnector(tmp_path / "outbox"),
    )
    plain = run_intake(
        _request(pilot_name="plain_pilot", split_method=_confirmed("single")),
        SAMPLE_INN_FILE,
        config=scratch_config,
        email_connector=LoggingEmailConnector(tmp_path / "outbox2"),
    )

    for folder in (cascade.pilot_folder, plain.pilot_folder):
        run_recalculation(Path(folder), config=scratch_config, force=True)

    assert (Path(cascade.pilot_folder) / HOMOGENEITY_FILENAME).exists()
    assert not (Path(plain.pilot_folder) / HOMOGENEITY_FILENAME).exists()

    check = latest_homogeneity_check(Path(cascade.pilot_folder))
    assert check["report_date"] == date.today().isoformat()
    assert check["articles"]


def test_a_drifted_group_is_recorded_with_the_date_and_the_article(tmp_path):
    """The analyst needs to know *from when* the comparison stopped holding."""
    control, target = ["c1", "c2", "c3"], ["t1", "t2", "t3"]
    balanced = {"chod": {"c1": 100.0, "c2": 110.0, "c3": 90.0,
                         "t1": 101.0, "t2": 109.0, "t3": 91.0}}
    drifted = {"chod": {"c1": 100.0, "c2": 110.0, "c3": 90.0,
                        "t1": 900.0, "t2": 910.0, "t3": 890.0}}

    run_homogeneity_check(tmp_path, control, target, balanced, date(2026, 1, 31), 0.10)
    run_homogeneity_check(tmp_path, control, target, drifted, date(2026, 2, 28), 0.10)

    rows = (tmp_path / HOMOGENEITY_FILENAME).read_text(encoding="utf-8").splitlines()
    assert len(rows) == 3  # header + one row per report_date
    assert "yes" in rows[1] and "no" in rows[2]
    assert "REBASE" in rows[2]

    check = latest_homogeneity_check(tmp_path)
    assert check["report_date"] == "2026-02-28"
    assert check["drifted_articles"] == ["chod"]
    assert check["rebase_needed"] is True


def test_the_check_never_moves_a_client_between_groups(tmp_path):
    """A rebase recalculates the baseline. Moving an already-treated client
    into control to restore balance would contaminate the control group, so
    the check is read-only by construction -- it returns a report and takes
    no group list to modify."""
    control, target = ["c1", "c2"], ["t1", "t2"]
    before = (list(control), list(target))
    run_homogeneity_check(
        tmp_path, control, target,
        {"chod": {"c1": 1.0, "c2": 2.0, "t1": 50.0, "t2": 60.0}},
        date(2026, 3, 31), 0.10,
    )
    assert (control, target) == before


# --- the form and the skill must agree ------------------------------------

def test_the_generated_form_carries_the_same_questionnaire():
    """web/index.html resolves the rules in-browser, so a stale build would
    offer the user a method the skill no longer knows about."""
    source = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "__METHOD_QUESTIONNAIRE__*/{}" not in source, "run python web/build_form.py"
    for question in method_advisor.questions():
        assert question["question"] in source
    for method in method_advisor.methods().values():
        assert method["label"] in source
