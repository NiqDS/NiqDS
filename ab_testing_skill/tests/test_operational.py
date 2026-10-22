"""Staging, the run log, the Spark scope and the shared theme."""
import json
from pathlib import Path

import pytest

from skill.run_log import INDEX_NAME, RunLog
from skill.spark_session import SPARK_CONF, active_session, probe_session, session_scope
from skill.staging import Staging
from skill.theme import THEME_CSS, TOKENS_DARK, TOKENS_LIGHT


# --- staging ---------------------------------------------------------------

def test_a_finished_metric_survives_a_later_failure(tmp_path):
    """The whole point: a metric is minutes of query time, and a failure on
    the last one used to discard every earlier one."""
    staging = Staging(tmp_path)
    staging.save("chod", ["2026-01"], {"111": {"2026-01": 10.0}})
    staging.save("chep", ["2026-01"], {"111": {"2026-01": 20.0}})
    assert staging.completed() == {"chod", "chep"}
    assert staging.load("chod") == {"111": {"2026-01": 10.0}}


def test_a_rerun_can_skip_what_is_already_on_disk(tmp_path):
    Staging(tmp_path).save("chod", ["2026-01", "2026-02"],
                           {"111": {"2026-01": 1.0, "2026-02": 2.0}})
    fresh = Staging(tmp_path)
    assert "chod" in fresh.completed()
    assert fresh.load("chod")["111"]["2026-02"] == 2.0


def test_a_flat_value_is_stored_too(tmp_path):
    staging = Staging(tmp_path)
    staging.save("legacy", ["2026-01"], {"111": 7.5})
    assert staging.load("legacy")["111"]["2026-01"] == 7.5


def test_missing_months_round_trip_as_missing_not_as_zero(tmp_path):
    staging = Staging(tmp_path)
    staging.save("chod", ["2026-01", "2026-02"], {"111": {"2026-02": 5.0}})
    loaded = staging.load("chod")
    assert "2026-01" not in loaded["111"]
    assert loaded["111"]["2026-02"] == 5.0


def test_a_metric_name_that_is_not_a_filename_is_handled(tmp_path):
    staging = Staging(tmp_path)
    path = staging.save("чод/по продуктам", ["2026-01"], {"1": {"2026-01": 1.0}})
    assert path.exists()


def test_clear_removes_the_folder(tmp_path):
    staging = Staging(tmp_path)
    staging.save("chod", ["2026-01"], {"1": {"2026-01": 1.0}})
    staging.clear()
    assert staging.completed() == set()


def test_loading_a_metric_that_was_never_saved(tmp_path):
    assert Staging(tmp_path).load("nope") == {}


def test_the_manifest_lists_what_is_there(tmp_path):
    staging = Staging(tmp_path)
    staging.save("chod", ["2026-01"], {"1": {"2026-01": 1.0}})
    manifest = json.loads((staging.root / "_metrics.json").read_text(encoding="utf-8"))
    assert "chod" in manifest


# --- run log ---------------------------------------------------------------

def test_the_log_records_stages_with_their_timing(tmp_path):
    with RunLog(tmp_path, "recalc_2026-01") as log:
        with log.stage("chod"):
            pass
        with log.stage("chep"):
            pass
    assert [s.name for s in log.stages] == ["chod", "chep"]
    assert all(s.ok for s in log.stages)
    text = log.path.read_text(encoding="utf-8")
    assert "chod" in text and "готово за" in text


def test_a_failing_stage_is_recorded_and_the_error_still_raised(tmp_path):
    with pytest.raises(ValueError):
        with RunLog(tmp_path, "run") as log:
            with log.stage("chod"):
                raise ValueError("mart unavailable")
    assert log.stages[0].ok is False
    assert "mart unavailable" in log.path.read_text(encoding="utf-8")


def test_the_log_never_swallows_an_exception(tmp_path):
    with pytest.raises(KeyError):
        with RunLog(tmp_path, "run"):
            raise KeyError("boom")


def test_stderr_is_mirrored_into_the_log(tmp_path):
    """Metric scripts print progress to stderr; the console scrolls away."""
    import sys

    with RunLog(tmp_path, "run") as log:
        print("[chod] ИНН с данными : 15 из 15", file=sys.stderr)
    text = log.path.read_text(encoding="utf-8")
    assert "ИНН с данными" in text
    assert "chod" in text


def test_stderr_is_restored_afterwards(tmp_path):
    import sys

    before = sys.stderr
    with RunLog(tmp_path, "run"):
        pass
    assert sys.stderr is before


def test_the_index_gets_one_line_per_run(tmp_path):
    for i in range(3):
        with RunLog(tmp_path, f"run_{i}") as log:
            with log.stage("chod"):
                pass
    lines = (tmp_path / INDEX_NAME).read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3
    entry = json.loads(lines[0])
    assert entry["ok"] is True
    assert entry["profile"][0]["stage"] == "chod"


def test_a_failed_run_is_marked_in_the_index(tmp_path):
    with pytest.raises(RuntimeError):
        with RunLog(tmp_path, "bad"):
            raise RuntimeError("nope")
    entry = json.loads((tmp_path / INDEX_NAME).read_text(encoding="utf-8").strip())
    assert entry["ok"] is False
    assert "nope" in entry["error"]


def test_the_profile_is_ordered_by_time_spent(tmp_path):
    import time

    with RunLog(tmp_path, "run") as log:
        with log.stage("fast"):
            pass
        with log.stage("slow"):
            time.sleep(0.02)
    assert log.profile()[0]["stage"] == "slow"


# --- spark scope -----------------------------------------------------------

def test_probe_rejects_nothing_at_all():
    ok, reason = probe_session(None)
    assert ok is False
    assert "не передана" in reason


def test_probe_rejects_a_session_whose_context_is_stopped():
    """A SparkSession object outlives its SparkContext: the variable stays
    truthy and the next query fails deep in py4j."""

    class StoppedContext:
        _jsc = None

    class Session:
        sparkContext = StoppedContext()

    ok, reason = probe_session(Session())
    assert ok is False
    assert "_jsc" in reason


def test_probe_runs_an_action_rather_than_trusting_the_object():
    calls = []

    class JSC:
        def sc(self):
            return type("SC", (), {"isStopped": lambda self: False})()

    class Session:
        sparkContext = type("Ctx", (), {"_jsc": JSC()})()

        def range(self, n):
            calls.append(n)
            return type("DF", (), {"count": lambda self: 1})()

    ok, _ = probe_session(Session())
    assert ok is True
    assert calls == [1], "liveness has to be proved with a job"


def test_probe_reports_the_failure_rather_than_raising():
    class Session:
        @property
        def sparkContext(self):
            raise RuntimeError("connection reset")

    ok, reason = probe_session(Session())
    assert ok is False
    assert "connection reset" in reason


def test_the_scope_borrows_a_live_session_and_does_not_stop_it(monkeypatch):
    """Stopping a session someone else owns takes their notebook down."""
    stopped = []
    existing = type("S", (), {"stop": lambda self: stopped.append(True)})()
    monkeypatch.setattr("skill.spark_session.active_session", lambda: existing)
    with session_scope() as session:
        assert session is existing
    assert stopped == []


def test_the_conf_names_the_executor_shape():
    assert SPARK_CONF["spark.executor.instances"]
    assert SPARK_CONF["spark.sql.execution.arrow.pyspark.enabled"] == "true"


def test_active_session_without_pyspark_is_none():
    assert active_session() is None


# --- theme -----------------------------------------------------------------

def test_light_and_dark_define_the_same_tokens():
    """A token present in one and missing from the other is an element that
    disappears when someone switches theme."""
    assert set(TOKENS_LIGHT) == set(TOKENS_DARK)


def test_the_stylesheet_covers_system_preference_and_an_explicit_override():
    assert ":root {" in THEME_CSS
    assert "prefers-color-scheme: dark" in THEME_CSS
    assert ':root[data-theme="dark"]' in THEME_CSS
    assert ':root:not([data-theme="light"])' in THEME_CSS


def test_the_generated_stylesheet_is_in_step_with_the_source():
    """web/_theme.css is generated; a stale copy means two pages of the same
    product are different colours."""
    path = Path(__file__).resolve().parent.parent / "web" / "_theme.css"
    assert path.exists(), "run python3 web/build_form.py"
    assert path.read_text(encoding="utf-8") == THEME_CSS


def test_no_page_declares_its_own_palette():
    web = Path(__file__).resolve().parent.parent / "web"
    for page in sorted(web.glob("*.html")):
        source = page.read_text(encoding="utf-8")
        assert "--accent:" not in source, f"{page.name} still has an inline palette"
        assert "_theme.css" in source, f"{page.name} does not link the theme"


def test_the_light_accent_is_dark_enough_to_carry_white_text():
    """#2ee6a6 from the original is 1.9:1 against white -- invisible as a
    button. Checked rather than eyeballed."""

    def luminance(hex_colour: str) -> float:
        rgb = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        rgb = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]

    accent = luminance(TOKENS_LIGHT["--accent"])
    contrast = (1.0 + 0.05) / (accent + 0.05)
    assert contrast >= 4.5, f"white on accent is only {contrast:.2f}:1"
