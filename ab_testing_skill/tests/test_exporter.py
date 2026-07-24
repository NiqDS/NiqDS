from datetime import date, timedelta

import pytest

from skill.exporter import read_codes_file, read_rows, write_financial_effect_file, write_group_file


def test_write_and_read_group_file_roundtrip(tmp_path):
    path = write_group_file(tmp_path, "control_group", ["1111111111", "2222222222"])
    assert path.exists()
    assert path.stem == "control_group"
    codes = read_codes_file(tmp_path / "control_group")
    assert codes == ["1111111111", "2222222222"]


def test_financial_effect_append_accumulates_report_dates(tmp_path):
    day1 = date(2026, 1, 1)
    day2 = day1 + timedelta(days=7)
    values = {"chod": {"1111111111": 100.0, "2222222222": 200.0}}
    group_of = {"1111111111": "cg", "2222222222": "tg"}

    write_financial_effect_file(tmp_path, day1, values, group_of, mode="append")
    path = write_financial_effect_file(tmp_path, day2, values, group_of, mode="append")

    header, rows = read_rows(path)
    assert header == ["report_date", "codes", "group", "chod", "stat_significance"]
    assert len(rows) == 4  # 2 clients x 2 report dates
    report_dates = {row[0] for row in rows}
    assert report_dates == {day1.isoformat(), day2.isoformat()}


def test_financial_effect_overwrite_keeps_only_latest(tmp_path):
    day1 = date(2026, 1, 1)
    day2 = day1 + timedelta(days=7)
    values = {"chod": {"1111111111": 100.0}}
    group_of = {"1111111111": "cg"}

    write_financial_effect_file(tmp_path, day1, values, group_of, mode="overwrite")
    path = write_financial_effect_file(tmp_path, day2, values, group_of, mode="overwrite")

    _, rows = read_rows(path)
    assert len(rows) == 1
    assert rows[0][0] == day2.isoformat()


def test_financial_effect_schema_change_refuses_to_append(tmp_path):
    day1 = date(2026, 1, 1)
    day2 = day1 + timedelta(days=7)
    group_of = {"1111111111": "cg"}

    write_financial_effect_file(tmp_path, day1, {"chod": {"1111111111": 1.0}}, group_of, mode="append")
    with pytest.raises(ValueError):
        write_financial_effect_file(
            tmp_path, day2, {"chod": {"1111111111": 1.0}, "revenue": {"1111111111": 2.0}},
            group_of, mode="append",
        )
