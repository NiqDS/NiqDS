"""Human/agent-readable rendering of the CLI's JSON payloads.

The CLI's contract is "always a JSON document on stdout" -- that is what
makes it safe for a tool wrapper to shell out and parse. It is a poor
thing to put in front of a person, though, and a poor thing for an agent
to relay: `run` alone emits the whole request echoed back plus every INN
in both groups, several kilobytes of it, when what the user needs is six
lines and the paths to two files.

So this module renders the same payloads as text. Nothing here parses or
decides anything -- `skill/cli.py` builds the payload exactly as before
and `main()` renders it on the way out, so the JSON path is untouched and
`--output text` cannot change what the skill actually did.

The style is deliberately plain: a status line, labelled facts, file
paths rather than inlined data, and an explicit "what to do next" block.
If a target CLI wants a different shape (different casing, a prefix per
line, no blank lines), this is the one file to change -- see
`render_document` for the dispatch table.
"""
from __future__ import annotations

import json
from typing import Any

#: Keys whose value is a path the user may want to open. Rendered last and
#: never truncated, since the whole point of the text output is to point at
#: files instead of inlining their contents.
_OK = "ГОТОВО"
_FAIL = "ОТКАЗ"
_SKIP = "ПРОПУЩЕНО"


def render_stdout(raw: str) -> str:
    """Renders everything a command printed.

    A command may print more than one JSON document (`run
    --drop-invalid-inns` prints the drop report, then the result), and
    `advise-method` without `--json` prints prose that is not JSON at all.
    Anything that does not parse is passed through verbatim rather than
    swallowed -- losing output would be worse than rendering it plainly.
    """
    text = raw.strip()
    if not text:
        return ""
    parts: list[str] = []
    decoder = json.JSONDecoder()
    index = 0
    while index < len(text):
        try:
            payload, end = decoder.raw_decode(text, index)
        except ValueError:
            parts.append(text[index:].strip())
            break
        parts.append(render_document(payload))
        index = end
        while index < len(text) and text[index].isspace():
            index += 1
    return "\n\n".join(p for p in parts if p) + "\n"


def render_document(payload: Any) -> str:
    if isinstance(payload, list):
        return _render_catalog(payload)
    if not isinstance(payload, dict):
        return str(payload)

    status = payload.get("status")
    handler = _HANDLERS.get(status)
    if handler is not None:
        return handler(payload)
    if status == "ok":
        return _render_ok(payload)
    return _render_generic(payload)


# --- success cases ---------------------------------------------------------

def _render_ok(payload: dict) -> str:
    """`status: ok` covers four different commands; tell them apart by shape."""
    if "pilots" in payload:
        return _render_rebase_due(payload)
    if "financial_effect_file" in payload:
        return _lines(
            f"{_OK}: пересчёт выполнен",
            ("Файл фин. эффекта", payload["financial_effect_file"]),
        )
    result = payload.get("result") or {}
    if "split" in result:
        return _render_pilot(result)
    if "result_file" in result:
        return _render_calculation(result)
    if "recommendation" in payload:
        return _render_recommendation(payload)
    return _render_generic(payload)


def _render_pilot(result: dict) -> str:
    request = result.get("request") or {}
    split = result.get("split") or {}
    out = [
        f"{_OK}: КГ и ЦГ сформированы",
        "",
        ("Пилот", f"{request.get('pilot_name')} "
                  f"({request.get('valid_from')} .. {request.get('valid_to')})"),
        ("Метод разделения", result.get("split_method", "single")),
        ("Контрольная группа (КГ)", f"{len(split.get('control') or [])} клиент(ов)"),
        ("Целевая группа (ЦГ)", f"{len(split.get('target') or [])} клиент(ов)"),
        ("Баланс по фин. статьям",
         ("в пределах порога SMD <= 0.1" if split.get("balanced") else
          "НЕ СОШЁЛСЯ в пределах порога SMD <= 0.1 -- см. balance_report")
         + f" (попыток: {split.get('attempts_used')}, seed: {split.get('seed')})"),
    ]

    coverage = result.get("coverage") or {}
    total = len(split.get("control") or []) + len(split.get("target") or [])
    if coverage and total:
        out.append(("Заполненность источника", _coverage_summary(coverage, total)))

    rejected = result.get("rejected_inns") or []
    blocked = result.get("duplicate_findings") or []
    if rejected:
        out.append(("Отклонено по формату", f"{len(rejected)} ИНН"))
    if blocked:
        out.append(("Заблокировано пересечениями", f"{len(blocked)} ИНН"))

    out.extend([
        "",
        "Файлы:",
        ("  КГ", result.get("control_file")),
        ("  ЦГ", result.get("target_file")),
    ])
    if result.get("financial_effect_file"):
        out.append(("  Фин. эффект", result["financial_effect_file"]))
    out.append(("  Папка пилота", result.get("pilot_folder")))

    steps = ["Передайте файлы КГ/ЦГ заказчику (столбец ИНН переименован в codes)."]
    if result.get("rebase_required"):
        out.extend([
            "",
            "ТРЕБУЕТСЯ РЕБЕЙЗ: это НЕ окончательный состав групп.",
        ])
        steps.extend([
            "Прочитайте REBASE_REQUIRED.md в папке пилота -- там чек-лист на каждый период.",
            "На каждом пересчёте сопоставимость групп проверяется заново "
            "(homogeneity_checks.csv); состав групп при этом не переразделяется.",
        ])
    steps.append(
        f"На следующем периоде: python -m skill.cli recalc --pilot-folder "
        f"{result.get('pilot_folder')}"
    )
    return _lines(*out) + "\n\n" + _steps(steps)


def _render_calculation(result: dict) -> str:
    request = result.get("request") or {}
    out = [
        f"{_OK}: метрики рассчитаны",
        "",
        ("Запрос", request.get("request_name")),
        ("Дата расчёта", request.get("as_of_date")),
        ("ID в расчёте", result.get("id_count")),
        ("Метрики", ", ".join(request.get("metrics") or []) or "(нет)"),
    ]
    filters = request.get("filters") or {}
    if filters:
        out.append(("Фильтры", ", ".join(f"{k}={v}" for k, v in filters.items())))
    coverage = result.get("coverage") or {}
    if coverage and result.get("id_count"):
        out.append(("Заполненность", _coverage_summary(coverage, result["id_count"])))
    rejected = result.get("rejected_ids") or []
    if rejected:
        out.append(("Отклонено ID", len(rejected)))
    out.extend(["", "Файлы:", ("  Результат", result.get("result_file"))])
    return _lines(*out)


def _render_rebase_due(payload: dict) -> str:
    pilots = payload.get("pilots") or []
    if not pilots:
        return _lines(
            f"{_OK}: на {payload.get('as_of')} ребейз не требуется ни по одному пилоту"
        )
    out = [
        f"{_OK}: ребейз требуется по {len(pilots)} пилоту(ам) на {payload.get('as_of')}",
        "",
    ]
    for pilot in pilots:
        out.append(f"  {pilot.get('pilot_name')} [{pilot.get('method')}]")
        out.append(("    Срок", f"до {pilot.get('next_due')}, пилот до {pilot.get('valid_to')}"))
        out.append(("    Что сделать", pilot.get("note")))
        out.append(("    Папка", pilot.get("pilot_folder")))
    return _lines(*out) + "\n\n" + _steps([
        "Для каждого пилота: python -m skill.cli recalc --pilot-folder <папка>",
        "Затем проверьте homogeneity_checks.csv -- если по статье within_tolerance=no, "
        "база сравнения пересчитывается с этой даты.",
    ])


def _render_recommendation(payload: dict) -> str:
    """advise-method --json: the outline is the point, so print it in full."""
    rec = payload.get("recommendation") or {}
    out = [
        f"{_OK}: метод подобран",
        "",
        ("Рекомендуемый метод", f"{rec.get('method')} -- {rec.get('label')}"),
        ("Требуется ребейз", "да" if rec.get("rebase_required") else "нет"),
        ("Проверка сопоставимости каждый период",
         "да" if rec.get("homogeneity_recheck_required") else "нет"),
    ]
    text = _lines(*out)
    for label, key in (
        ("Почему именно он:", "reasons"),
        ("Как это будет работать:", "outline"),
        ("Что потребуется от вас:", "requires_from_user"),
        ("Внимание, ответы «не знаю»:", "unknown_answers"),
    ):
        items = rec.get(key) or []
        if items:
            text += "\n\n" + label + "\n" + "\n".join(f"  - {i}" for i in items)
    if payload.get("next_step"):
        text += "\n\n" + _steps([payload["next_step"]])
    return text


# --- refusals and failures -------------------------------------------------

def _render_issues(payload: dict, headline: str, field_key: str = "field") -> str:
    issues = payload.get("issues") or []
    out = [f"{_FAIL}: {headline} ({len(issues)})", ""]
    for issue in issues:
        label = issue.get(field_key) or issue.get("inn") or "-"
        out.append(f"  {label}: {issue.get('reason')}")
    return _lines(*out)


def _render_invalid_request(payload: dict) -> str:
    return _render_issues(payload, "запрос не прошёл проверку, ничего не записано") \
        + "\n\n" + _steps([
            "Исправьте перечисленные поля в request.json и запустите команду снова.",
            "Ни один файл и ни одна запись в реестрах при этом не создавались.",
        ])


def _render_rejected(payload: dict) -> str:
    return _render_issues(payload, "входной файл отклонён", field_key="inn") \
        + "\n\n" + _steps([
            "Либо попросите заказчика прислать исправленный файл,",
            "либо запустите с --drop-invalid-inns, чтобы отбросить плохие строки "
            "и разделить остальные.",
        ])


def _render_dropped(payload: dict) -> str:
    out = [
        f"ВНИМАНИЕ: отброшено строк с некорректными ИНН: {payload.get('dropped_count')}",
        ("Осталось для разделения", payload.get("remaining_count")),
        ("Очищенный файл", payload.get("cleaned_file")),
        "",
    ]
    for issue in (payload.get("dropped") or [])[:10]:
        out.append(f"  {issue.get('inn') or '-'}: {issue.get('reason')}")
    extra = len(payload.get("dropped") or []) - 10
    if extra > 0:
        out.append(f"  ... и ещё {extra}")
    return _lines(*out)


def _render_no_eligible(payload: dict) -> str:
    blocked = payload.get("blocked") or []
    out = [f"{_FAIL}: не осталось ни одного доступного ИНН ({len(blocked)} заблокировано)", ""]
    for item in blocked[:10]:
        if isinstance(item, dict):
            out.append(
                f"  {item.get('inn')}: уже в пилоте '{item.get('existing_pilot_name')}' "
                f"({item.get('existing_valid_from')} .. {item.get('existing_valid_to')})"
            )
        else:
            out.append(f"  {item}")
    if len(blocked) > 10:
        out.append(f"  ... и ещё {len(blocked) - 10}")
    return _lines(*out) + "\n\n" + _steps([
        "Проверьте список с заказчиком: эти клиенты уже задействованы в других пилотах "
        "или помечены как Used в мастер-таблице статусов.",
    ])


def _render_already_exists(payload: dict) -> str:
    return _lines(
        f"{_FAIL}: пилот с таким именем и сроками уже существует",
        ("Папка", payload.get("pilot_folder")),
    ) + "\n\n" + _steps([
        "Измените имя пилота или сроки,",
        "или передайте --force, если прошлый прогон нужно перезаписать осознанно.",
    ])


def _render_skipped(payload: dict) -> str:
    return _lines(
        f"{_SKIP}: пересчёт не требуется",
        ("Причина", payload.get("reason")),
        ("Детали", payload.get("detail")),
    )


def _render_error(payload: dict) -> str:
    out = [f"{_FAIL}: {payload.get('error_type') or 'ошибка'}"]
    if payload.get("detail"):
        out.append(("Детали", payload["detail"]))
    return _lines(*out)


def _render_no_valid(payload: dict) -> str:
    return _lines(
        f"{_FAIL}: после отбрасывания некорректных строк не осталось ни одного ИНН"
    )


# --- catalogs (metrics / filters) -----------------------------------------

def _render_catalog(items: list) -> str:
    if not items:
        return "(пусто)"
    out = [f"Всего: {len(items)}", ""]
    for item in items:
        if not isinstance(item, dict):
            out.append(f"  {item}")
            continue
        head = f"  {item.get('code')} -- {item.get('label')}"
        usable = item.get("usable_as")
        if usable:
            head += f"  [{', '.join(usable) if isinstance(usable, list) else usable}]"
        applies = item.get("applies_to")
        if applies:
            head += f"  [применимо: {', '.join(applies)}]"
        out.append(head)
        if item.get("description"):
            out.append(f"      {item['description']}")
        if item.get("values"):
            out.append(f"      значения: {', '.join(str(v) for v in item['values'])}")
    return _lines(*out)


# --- helpers --------------------------------------------------------------

def _render_generic(payload: dict) -> str:
    """Fallback, so a payload added later is still readable rather than lost."""
    status = payload.get("status")
    out = [f"status: {status}"] if status else []
    for key, value in payload.items():
        if key == "status":
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        out.append((key, value))
    return _lines(*out)


def _coverage_summary(coverage: dict, total: int) -> str:
    parts = []
    for metric, filled in sorted(coverage.items()):
        pct = 100.0 * filled / total if total else 0.0
        flag = " (МАЛО!)" if pct < 95 else ""
        parts.append(f"{metric} {filled}/{total} ({pct:.0f}%){flag}")
    return ", ".join(parts)


def _steps(items: list[str]) -> str:
    return "СЛЕДУЮЩИЙ ШАГ:\n" + "\n".join(f"  - {i}" for i in items)


def _lines(*entries) -> str:
    """Renders a mix of bare strings and (label, value) pairs, aligned."""
    pairs = [e for e in entries if isinstance(e, tuple)]
    width = max((len(p[0]) for p in pairs), default=0)
    out = []
    for entry in entries:
        if isinstance(entry, tuple):
            label, value = entry
            out.append(f"{label.ljust(width)}  {value}")
        else:
            out.append(entry)
    return "\n".join(out)


_HANDLERS = {
    "invalid_request": _render_invalid_request,
    "rejected": _render_rejected,
    "invalid_inns_dropped": _render_dropped,
    "no_valid_inns_remaining": _render_no_valid,
    "no_eligible_clients": _render_no_eligible,
    "pilot_already_exists": _render_already_exists,
    "skipped": _render_skipped,
    "error": _render_error,
}
