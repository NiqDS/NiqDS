"""Pilot analytics: the DiD, the diagnostics, and the three renderings.

The test that matters most here is the A/A one. A method that finds an
effect where none was injected is worse than no method, because it is
confidently wrong rather than silent.
"""
import csv
import json
from datetime import date
from pathlib import Path

import pytest

from skill.analysis import NoHistoryError, analyse_pilot
from skill.report import render_text, write_excel, write_html


def _build_history(
    folder: Path,
    periods: list[str],
    control: dict[str, list[float]],
    target: dict[str, list[float]],
    homogeneity: list[tuple[str, str]] | None = None,
) -> Path:
    """Writes a financial_effect.csv shaped exactly as the pilot writes it."""
    folder.mkdir(parents=True, exist_ok=True)
    rows = [["report_date", "codes", "group", "chod", "stat_significance"]]
    for index, period in enumerate(periods):
        for inn, series in control.items():
            if index < len(series):
                rows.append([period, inn, "cg", series[index], 0.5])
        for inn, series in target.items():
            if index < len(series):
                rows.append([period, inn, "tg", series[index], 0.5])
    with open(folder / "financial_effect.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)

    (folder / "pilot_meta.json").write_text(
        json.dumps({"pilot_name": folder.name, "financial_effect_articles": ["chod"]}),
        encoding="utf-8",
    )
    if homogeneity:
        with open(folder / "homogeneity_checks.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["report_date", "article", "smd", "within_tolerance", "action"])
            for period, within in homogeneity:
                w.writerow([period, "chod", 0.05, within, ""])
    return folder


PERIODS = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]


def _noise(seed: int, period: int) -> float:
    """Deterministic month-to-month wobble. A pilot with literally zero
    variance has an undefined p-value, which is a property of the fixture
    and not of any real client."""
    return ((seed * 37 + period * 11) % 17 - 8) / 8.0


def _flat(value: float, n: int = 20, jitter: float = 0.0,
          prefix: str = "c") -> dict[str, list[float]]:
    return {
        f"{prefix}{i:03d}": [
            value + jitter * ((i % 5) - 2) + jitter * _noise(i, p)
            for p in range(len(PERIODS))
        ]
        for i in range(n)
    }


def _lifted(value: float, lift: float, n: int = 20, jitter: float = 0.0,
            prefix: str = "t") -> dict[str, list[float]]:
    out = {}
    for i in range(n):
        base = value + jitter * ((i % 5) - 2)
        out[f"{prefix}{i:03d}"] = [base + jitter * _noise(i, 0)] + [
            base * (1 + lift) + jitter * _noise(i, p) for p in range(1, len(PERIODS))
        ]
    return out


# --- the two checks that matter -------------------------------------------

def test_an_injected_effect_is_recovered(tmp_path):
    folder = _build_history(
        tmp_path / "effect",
        PERIODS,
        control=_flat(100_000, jitter=4000),
        target=_lifted(100_000, 0.30, jitter=4000),
    )
    analysis = analyse_pilot(folder)
    assert analysis.effect.mean > 0
    assert analysis.effect.low > 0, "the interval should exclude zero"
    assert analysis.effect.p_value < 0.01
    assert analysis.permutation_p < 0.01
    assert 0.2 < analysis.effect_relative < 0.4, analysis.effect_relative
    assert "значим по обоим тестам" in analysis.verdict


def test_an_aa_pilot_shows_no_effect(tmp_path):
    """Nothing injected. Finding an effect here would be the worst failure
    the module could have."""
    folder = _build_history(
        tmp_path / "aa",
        PERIODS,
        control=_flat(100_000, jitter=4000, prefix="c"),
        target=_flat(100_000, jitter=4000, prefix="t"),
    )
    analysis = analyse_pilot(folder)
    assert analysis.effect.p_value > 0.05
    assert analysis.permutation_p > 0.05
    assert "не подтверждён" in analysis.verdict


# --- the diagnostics -------------------------------------------------------

def test_an_effect_carried_by_three_clients_is_called_out(tmp_path):
    control = _flat(100_000, n=30)
    target = {f"t{i:03d}": [100_000.0] * len(PERIODS) for i in range(30)}
    for i in range(3):                       # three clients do all the moving
        target[f"t{i:03d}"] = [100_000.0] + [900_000.0] * (len(PERIODS) - 1)
    analysis = analyse_pilot(_build_history(tmp_path / "conc", PERIODS, control, target))
    assert analysis.effect_concentration > 0.5
    assert any("приходится на трёх клиентов" in w for w in analysis.warnings)


def test_the_two_tests_disagreeing_is_reported_as_information(tmp_path):
    """A mean carried by a few large clients is exactly the case the sign
    and permutation tests exist to expose."""
    control = _flat(100_000, n=30)
    target = {f"t{i:03d}": [100_000.0, 99_000.0] + [99_000.0] * 4 for i in range(30)}
    target["t000"] = [100_000.0] + [50_000_000.0] * 5
    analysis = analyse_pilot(_build_history(tmp_path / "split", PERIODS, control, target))
    assert analysis.target_share_up < 0.2, "almost everyone went down"
    assert analysis.effect.mean > 0, "but the mean went up, on one client"


def test_a_baseline_imbalance_is_flagged_as_not_the_pilots_doing(tmp_path):
    folder = _build_history(
        tmp_path / "skew",
        PERIODS,
        control=_flat(100_000, jitter=1000),
        target=_flat(400_000, jitter=1000, prefix="t"),
    )
    analysis = analyse_pilot(folder)
    assert analysis.baseline_smd > 0.1
    assert any("на старте группы уже расходились" in w for w in analysis.warnings)


def test_lost_comparability_names_the_month_it_started(tmp_path):
    folder = _build_history(
        tmp_path / "drift", PERIODS,
        control=_flat(100_000, jitter=500),
        target=_flat(100_000, jitter=500, prefix="t"),
        homogeneity=[("2026-02", "yes"), ("2026-04", "no"), ("2026-05", "no")],
    )
    analysis = analyse_pilot(folder)
    assert analysis.drifted_from == "2026-04"
    assert any("2026-04" in w for w in analysis.warnings)


def test_asymmetric_dropout_is_flagged(tmp_path):
    control = _flat(100_000, n=20, jitter=500)
    target = _flat(100_000, n=20, jitter=500, prefix="t")
    for i in range(8):                      # eight clients leave the target group
        target[f"t{i:03d}"] = target[f"t{i:03d}"][:2]
    analysis = analyse_pilot(_build_history(tmp_path / "drop", PERIODS, control, target))
    assert analysis.dropouts["tg"] == 8
    assert analysis.dropouts["cg"] == 0
    assert any("разный отток" in w for w in analysis.warnings)


def test_two_periods_is_flagged_as_too_few(tmp_path):
    folder = _build_history(tmp_path / "short", PERIODS[:2],
                            control=_flat(100_000, jitter=500), target=_flat(100_000, jitter=500, prefix="t"))
    analysis = analyse_pilot(folder)
    assert any("только 2 период" in w for w in analysis.warnings)


# --- refusing to analyse nothing ------------------------------------------

def test_a_pilot_with_no_history_is_refused(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(NoHistoryError) as exc_info:
        analyse_pilot(tmp_path / "empty")
    assert "recalc" in str(exc_info.value)


def test_one_period_is_not_a_trend(tmp_path):
    """"No effect" and "ran once" look the same in a table of zeros, and
    only one of them is a finding."""
    folder = _build_history(tmp_path / "one", PERIODS[:1],
                            control=_flat(100_000, jitter=500), target=_flat(100_000, jitter=500, prefix="t"))
    with pytest.raises(NoHistoryError) as exc_info:
        analyse_pilot(folder)
    assert "least two" in str(exc_info.value)


# --- the renderings --------------------------------------------------------

def test_the_text_overview_carries_the_numbers_a_person_needs(tmp_path):
    folder = _build_history(tmp_path / "text", PERIODS,
                            control=_flat(100_000, jitter=4000),
                            target=_lifted(100_000, 0.30, jitter=4000))
    text = render_text(analyse_pilot(folder))
    for expected in ("ЭФФЕКТ ПИЛОТА", "ВЫВОД:", "ПОМЕСЯЧНО", "перестановочный тест",
                     "КАК ВЕДУТ СЕБЯ КЛИЕНТЫ"):
        assert expected in text
    assert "КАК ЧИТАТЬ" in text, "the reader has to know what DiD means"


def test_the_text_overview_is_deterministic(tmp_path):
    """A report that reads differently each run cannot be compared with
    last month's."""
    folder = _build_history(tmp_path / "det", PERIODS,
                            control=_flat(100_000), target=_lifted(100_000, 0.2))
    first = render_text(analyse_pilot(folder))
    second = render_text(analyse_pilot(folder))
    assert first == second


def test_the_workbook_is_written_with_every_sheet(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    folder = _build_history(tmp_path / "xlsx", PERIODS,
                            control=_flat(100_000), target=_lifted(100_000, 0.2),
                            homogeneity=[("2026-02", "yes")])
    path = write_excel(analyse_pilot(folder), folder)
    assert path.exists()
    wb = openpyxl.load_workbook(path)
    assert {"Динамика", "Клиенты", "Выводы", "Сопоставимость"} <= set(wb.sheetnames)
    assert wb["Динамика"]._charts, "the dynamics sheet needs its chart"
    codes = wb["Клиенты"]["A2"]
    assert codes.number_format == "@", "an ИНН must keep its leading zero"


def test_the_dashboard_is_standalone(tmp_path):
    """It gets emailed and moved, so a relative link to web/ would break."""
    folder = _build_history(tmp_path / "html", PERIODS,
                            control=_flat(100_000), target=_lifted(100_000, 0.2))
    path = write_html(analyse_pilot(folder), folder)
    source = path.read_text(encoding="utf-8")
    assert "<link" not in source, "no external stylesheet"
    assert "--accent:" in source, "the theme travels with the file"
    assert "<svg" in source and "polyline" in source
    assert "src=" not in source, "no external images either"


def test_the_dashboard_escapes_what_it_prints(tmp_path):
    folder = tmp_path / "<script>alert(1)</script>"
    _build_history(folder, PERIODS, control=_flat(100_000, jitter=500), target=_flat(100_000, jitter=500, prefix="t"))
    source = write_html(analyse_pilot(folder), folder).read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in source.split("</head>")[1]
