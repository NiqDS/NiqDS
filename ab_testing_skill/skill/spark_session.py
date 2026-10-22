"""One SparkSession per run, started once and stopped at the end.

Ported from the metrics-calculation fork, whose docstring diagnosed the
problem precisely: `SparkSession.builder.getOrCreate()` inside each metric
script does **not** give a session per metric. In one process it hands back
the JVM's existing session, so a bank of scripts that each build and stop
their own produces "chod starts it -> chod stops it in finally -> chep
starts a new one -> sdo borrows chep's -> nobody stops the last". Every
metric after the first pays to rebuild executors, and the run ends with a
session still holding the cluster.

The second piece is `probe_session`. A `SparkSession` object outlives its
`SparkContext`: after the context is stopped, or after Kubernetes preempts
the executors, the Python object is still there and still truthy, and the
next query fails somewhere deep in py4j. Checking liveness means running a
tiny action, not checking that the variable is not None.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Any, Iterator

__all__ = [
    "SPARK_CONF",
    "active_session",
    "build_session",
    "probe_session",
    "session_scope",
]

#: Matches the configuration the analysts run in DataLab. Overridable per
#: deployment; the defaults are deliberately modest so a run does not sit in
#: the queue waiting for a large allocation.
SPARK_CONF: dict[str, str] = {
    "spark.ui.enabled": "true",
    "spark.driver.memory": "3g",
    "spark.executor.instances": "2",
    "spark.executor.cores": "2",
    "spark.kubernetes.executor.limit.cores": "2",
    "spark.kubernetes.executor.request.cores": "1800m",
    "spark.executor.memory": "10g",
    "spark.executor.memoryOverhead": "1g",
    "spark.sql.parquet.compression.codec": "snappy",
    "spark.sql.execution.arrow.pyspark.enabled": "true",
}


def _log(message: str, prefix: str = "spark") -> None:
    print(f"[{prefix}] {message}", file=sys.stderr, flush=True)


def active_session() -> Any | None:
    """An already-live session in this process, or None without pyspark."""
    try:
        from pyspark.sql import SparkSession
    except ImportError:
        return None
    getter = getattr(SparkSession, "getActiveSession", None)
    if callable(getter):
        session = getter()
        if session is not None:
            return session
    return getattr(SparkSession, "_instantiatedSession", None)


def build_session(app_name: str = "ab-testing-skill", conf: dict[str, str] | None = None) -> Any:
    from pyspark.sql import SparkSession

    builder = SparkSession.builder.appName(app_name)
    for key, value in (conf or SPARK_CONF).items():
        builder = builder.config(key, value)
    return builder.getOrCreate()


def probe_session(spark: Any) -> tuple[bool, str]:
    """Is this session actually usable? Answered with an action, not a cast.

    Checks the context has not been stopped and then runs the smallest
    possible job. A session that passes this is one a query can be sent to;
    a session that merely exists is not.
    """
    if spark is None:
        return False, "SparkSession не передана"
    try:
        context = spark.sparkContext
        if getattr(context, "_jsc", None) is None:
            return False, "SparkContext уже остановлен (_jsc=None)"
        if context._jsc.sc().isStopped():
            return False, "SparkContext остановлен (JVM isStopped=True)"
        spark.range(1).count()
        return True, "SparkSession активна (range(1).count() OK)"
    except Exception as exc:  # noqa: BLE001 - any failure here means unusable
        return False, f"{type(exc).__name__}: {exc}"


@contextmanager
def session_scope(
    app_name: str = "ab-testing-skill",
    conf: dict[str, str] | None = None,
) -> Iterator[Any]:
    """Borrow a live session, or build one and stop it on the way out.

    Whoever creates the session stops it. A scope that finds one already
    running leaves it alone -- stopping a session someone else owns, in a
    notebook for instance, takes their work down with it.
    """
    existing = active_session()
    if existing is not None:
        _log("используется уже живая SparkSession")
        yield existing
        return

    spark = build_session(app_name, conf)
    _log(f"SparkSession поднята (version={spark.version}, app={app_name})")
    try:
        yield spark
    finally:
        try:
            spark.stop()
            _log("SparkSession остановлена")
        except Exception as exc:  # noqa: BLE001 - shutdown must not fail the run
            _log(f"не удалось остановить SparkSession: {exc}")
