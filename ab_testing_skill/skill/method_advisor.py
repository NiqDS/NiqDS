"""Step 3b (NEW, not in the original spec): decide HOW the list gets split.

The spec assumes one split per pilot. Real pilots often cannot work that
way -- clients are onboarded in waves, the eligible list keeps growing,
or the pilot runs long enough that clients drift between segments -- and
those pilots need the list split repeatedly, with the strata recomputed
and the CG/TG comparability re-checked each time (a cascade split with
resegmentation and a rebase).

An experienced analyst knows when that applies. The person filling in the
intake form usually does not, and would never pick the cascade option from
a dropdown. So instead of offering the choice, this module asks a handful
of questions about the *rollout* -- when clients start, whether the list
grows, whether their attributes move, whether clients drop out -- and
derives the method from the answers.

Three design decisions worth knowing about:

1. **Questions never mention statistics.** Each option carries the
   mechanism it switches on (`implies`), and the recommendation is derived
   from those flags alone. The questions, the flags and the rules all live
   in `split_method_questionnaire.json`, so the reasoning is auditable and
   the wording can be fixed without touching code.

2. **Unknown answers lean toward the cascade method.** The costs are not
   symmetric: picking "no rebase" for a pilot that needed one invalidates
   the result and cannot be repaired after the fact, while picking
   "rebase" for a pilot that did not need one costs one balance re-check
   per period that comes back "still comparable".

3. **A recommendation is not a decision.** `recommend()` returns the
   method, the reasons behind it, a plain-language outline, and the
   alternative -- the caller shows the outline and asks whether it matches
   the pilot. Only a confirmed (or explicitly overridden) method is
   allowed to reach `run_intake`; see `validation.validate_pilot_request`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

QUESTIONNAIRE_PATH = Path(__file__).resolve().parent / "split_method_questionnaire.json"

#: Number of recalculation periods from which a pilot counts as long-running.
#: Six is a judgement call, not a derived constant: it is the point at which
#: a monthly pilot has run half a year and the t0 baseline is old enough that
#: an analyst would want it re-checked rather than trusted.
LONG_HORIZON_ITERATIONS = 6

PERIOD_DAYS = {"day": 1, "week": 7, "month": 30}


@dataclass
class MethodRecommendation:
    """What to show the user after the questionnaire, and what to record."""

    method: str
    label: str
    summary: str
    outline: list[str]
    reasons: list[str]
    confirmation_question: str
    alternative: str
    alternative_label: str
    rebase_required: bool
    homogeneity_recheck_required: bool
    fits_when: str
    risk_if_wrong: str
    flags: list[str] = field(default_factory=list)
    #: Questions answered "I don't know" that moved the recommendation. Shown
    #: back to the user so an unknown can be resolved instead of silently
    #: deciding the method.
    unknown_answers: list[str] = field(default_factory=list)
    requires_from_user: list[str] = field(default_factory=list)
    modifiers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "label": self.label,
            "summary": self.summary,
            "outline": self.outline,
            "reasons": self.reasons,
            "confirmation_question": self.confirmation_question,
            "alternative": self.alternative,
            "alternative_label": self.alternative_label,
            "rebase_required": self.rebase_required,
            "homogeneity_recheck_required": self.homogeneity_recheck_required,
            "fits_when": self.fits_when,
            "risk_if_wrong": self.risk_if_wrong,
            "flags": self.flags,
            "unknown_answers": self.unknown_answers,
            "requires_from_user": self.requires_from_user,
            "modifiers": self.modifiers,
        }

    def as_text(self) -> str:
        """The block a chat/CLI agent reads out before asking for confirmation."""
        lines = [
            f"Рекомендуемый метод разделения: {self.label}",
            "",
            self.summary,
            "",
            "Почему именно он:",
        ]
        lines.extend(f"  - {reason}" for reason in self.reasons)
        if self.unknown_answers:
            lines.append("")
            lines.append(
                "Внимание: часть ответов — «не знаю», и метод выбран по осторожному варианту. "
                "Уточните и пройдите опрос заново, если это важно:"
            )
            lines.extend(f"  - {q}" for q in self.unknown_answers)
        lines.extend(["", "Как это будет работать:"])
        lines.extend(f"  {i}. {step}" for i, step in enumerate(self.outline, 1))
        if self.requires_from_user:
            lines.extend(["", "Что потребуется от вас:"])
            lines.extend(f"  - {item}" for item in self.requires_from_user)
        if self.modifiers:
            lines.extend(["", "Дополнительно:"])
            lines.extend(f"  - {item}" for item in self.modifiers)
        lines.extend(
            [
                "",
                f"Подходит, когда: {self.fits_when}",
                f"Чем рискуете, если метод выбран неверно: {self.risk_if_wrong}",
                "",
                self.confirmation_question,
                f"(альтернатива: {self.alternative_label})",
            ]
        )
        return "\n".join(lines)


class UnknownAnswerError(Exception):
    """An answer references a question or option the questionnaire doesn't have.

    Raised rather than ignored: silently dropping an unrecognised answer
    would change the recommendation without telling anyone.
    """


@lru_cache(maxsize=1)
def load_questionnaire(path: str | None = None) -> dict:
    return json.loads(Path(path or QUESTIONNAIRE_PATH).read_text(encoding="utf-8"))


def questions() -> list[dict]:
    """The questions to ask, in order. Used by the CLI and the form builder."""
    return load_questionnaire()["questions"]


def methods() -> dict:
    return load_questionnaire()["methods"]


def method_label(method: str) -> str:
    return methods().get(method, {}).get("label", method)


def expected_iterations(valid_from, valid_to, recalculation_frequency: str) -> int:
    """How many recalculation passes the pilot's own term implies.

    Asked of the request rather than of the user: the dates and the cadence
    are already on the form, and a question whose answer the skill can
    compute is a question that can be answered wrong.
    """
    step = PERIOD_DAYS.get(recalculation_frequency, 30)
    days = max((valid_to - valid_from).days, 0)
    return max(days // step, 1)


def _collect_flags(answers: dict[str, str]) -> tuple[list[str], list[str]]:
    """Maps the submitted answers onto mechanism flags.

    Returns (flags, unknown_question_texts). Unknown-answer questions are
    reported separately so the user can see which uncertainty drove the
    recommendation.
    """
    catalog = {q["id"]: q for q in questions()}
    flags: list[str] = []
    unknowns: list[str] = []

    for question_id, option_id in answers.items():
        question = catalog.get(question_id)
        if question is None:
            raise UnknownAnswerError(
                f"unknown question {question_id!r}; expected one of {sorted(catalog)}"
            )
        options = {o["id"]: o for o in question["options"]}
        option = options.get(option_id)
        if option is None:
            raise UnknownAnswerError(
                f"unknown answer {option_id!r} for question {question_id!r}; "
                f"expected one of {sorted(options)}"
            )
        for flag in option.get("implies", []):
            if flag not in flags:
                flags.append(flag)
        if option.get("unknown"):
            unknowns.append(question["question"])

    return flags, unknowns


def recommend(
    answers: dict[str, str],
    iterations: int | None = None,
) -> MethodRecommendation:
    """Turns questionnaire answers into a method + an outline to confirm.

    `iterations` is the pilot's expected number of recalculation passes
    (see `expected_iterations`); passing it lets a long pilot trigger the
    homogeneity re-check even when every answer says "nothing changes".
    """
    data = load_questionnaire()
    flags, unknowns = _collect_flags(answers)

    if iterations is not None and iterations >= LONG_HORIZON_ITERATIONS:
        flags.append("long_horizon")

    decisive = [f for f in flags if f != "nested_tiers"]
    for rule in data["rules"]:
        triggers = rule["if_any"]
        if not triggers or any(flag in decisive for flag in triggers):
            matched = rule
            matched_triggers = [f for f in triggers if f in decisive]
            break
    else:  # pragma: no cover - the last rule has an empty if_any, so always matches
        raise RuntimeError("questionnaire has no catch-all rule")

    method_key = matched["method"]
    method = data["methods"][method_key]
    reasons = [matched["because"]]
    reasons.extend(_flag_reasons(matched_triggers, iterations))

    modifiers = []
    if "nested_tiers" in flags:
        modifiers.append(data["modifiers"]["nested_tiers"]["note"])

    return MethodRecommendation(
        method=method_key,
        label=method["label"],
        summary=method["summary"],
        outline=list(method["outline"]),
        reasons=reasons,
        confirmation_question=data["confirmation_question"],
        alternative=matched["alternative"],
        alternative_label=data["methods"][matched["alternative"]]["label"],
        rebase_required=method["rebase_required"],
        homogeneity_recheck_required=method["homogeneity_recheck_required"],
        fits_when=method["fits_when"],
        risk_if_wrong=method["risk_if_wrong"],
        flags=flags,
        unknown_answers=unknowns,
        requires_from_user=list(method.get("requires_from_user", [])),
        modifiers=modifiers,
    )


_FLAG_REASONS = {
    "membership_grows": "по вашим ответам состав пилота будет пополняться после старта",
    "strata_drift": "по вашим ответам характеристики клиентов за время пилота изменятся",
    "attrition": "по вашим ответам ожидается отток клиентов из пилота",
}


def _flag_reasons(flags: list[str], iterations: int | None) -> list[str]:
    reasons = [_FLAG_REASONS[f] for f in flags if f in _FLAG_REASONS]
    if "long_horizon" in flags:
        reasons.append(
            f"срок пилота даёт {iterations} пересчёт(ов) — на такой дистанции "
            "сопоставимость групп нужно перепроверять, а не считать заданной на старте"
        )
    return reasons


def describe(method: str) -> MethodRecommendation | None:
    """The outline for a method chosen directly, with no questionnaire.

    Used when the submitter overrides the recommendation: the method they
    picked instead still has to be shown to them in full before it is
    recorded.
    """
    data = load_questionnaire()
    spec = data["methods"].get(method)
    if spec is None:
        return None
    alternative = "cascade_rebase" if method != "cascade_rebase" else "single_monitored"
    return MethodRecommendation(
        method=method,
        label=spec["label"],
        summary=spec["summary"],
        outline=list(spec["outline"]),
        reasons=["метод выбран вручную, без опроса"],
        confirmation_question=data["confirmation_question"],
        alternative=alternative,
        alternative_label=data["methods"][alternative]["label"],
        rebase_required=spec["rebase_required"],
        homogeneity_recheck_required=spec["homogeneity_recheck_required"],
        fits_when=spec["fits_when"],
        risk_if_wrong=spec["risk_if_wrong"],
        requires_from_user=list(spec.get("requires_from_user", [])),
    )
