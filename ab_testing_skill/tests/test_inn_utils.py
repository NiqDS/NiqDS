import csv
from pathlib import Path

from skill.inn_utils import is_valid_checksum, validate_file, validate_inn


def test_valid_10_digit_checksum():
    assert is_valid_checksum("7707083893")  # a well-known real bank INN (Sberbank)


def test_invalid_checksum_rejected():
    assert not is_valid_checksum("7707083894")


def test_validate_inn_rejects_non_digits():
    issue = validate_inn("77070838X3")
    assert issue is not None
    assert "non-digit" in issue.reason


def test_validate_inn_rejects_wrong_length():
    issue = validate_inn("12345", check_control_digits=False)
    assert issue is not None
    assert "length" in issue.reason


def test_validate_inn_accepts_good_value():
    assert validate_inn("7707083893") is None


def test_validate_file_flags_duplicates_within_file(tmp_path: Path):
    path = tmp_path / "inns.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["inn"])
        writer.writerow(["7707083893"])
        writer.writerow(["7707083893"])
    result = validate_file(path)
    assert len(result.valid_inns) == 1
    assert any("duplicate" in i.reason for i in result.issues)


def test_validate_file_rejects_wrong_extension(tmp_path: Path):
    path = tmp_path / "inns.xlsx"
    path.write_text("not really a csv", encoding="utf-8")
    result = validate_file(path)
    assert not result.ok
    assert "unsupported file format" in result.issues[0].reason


def test_validate_file_missing_inn_column(tmp_path: Path):
    path = tmp_path / "inns.csv"
    path.write_text("not_inn\n123\n", encoding="utf-8")
    result = validate_file(path)
    assert not result.ok
    assert "must have an 'inn' column" in result.issues[0].reason
