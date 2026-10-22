"""A timed log of one run: what ran, how long it took, where it broke.

Ported from the metrics-calculation fork. A metric is minutes of query
time, and afterwards somebody has to answer "what was slow" and "where did
it stop". The console scrolls away and is gone, so everything printed to
stderr is mirrored to a file with timestamps, and each stage is measured.

Two files per run directory:

    <date>_<time>_<name>.log   the run, line by line, with elapsed time
    index.jsonl                one JSON line per run, for comparing runs

Line format, which reads like the console with time added::

    16:12:03.481  +12.4s  chod    | ИНН с данными : 15 из 15

What is deliberately **not** here: the JVM's own logs. They go to the
process stderr as a whole and live in the Spark UI; trying to capture them
would double every line without adding anything. The script messages and
the traceback that stopped a metric are what answer the question.
"""
from __future__ import annotations

import json
import re
import sys
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, TextIO

__all__ = ["RunLog", "INDEX_NAME"]

INDEX_NAME = "index.jsonl"
_TAG = re.compile(r"^\s*\[([A-Za-zА-Яа-я0-9_\-]{1,24})\]\s*(.*)$")


@dataclass
class Stage:
    name: str
    seconds: float
    ok: bool = True
    detail: str = ""


class _Tee:
    """Writes to the real stream and to the log file at once."""

    def __init__(self, stream: TextIO, log: "RunLog"):
        self._stream = stream
        self._log = log
        self._buffer = ""

    def write(self, text: str) -> int:
        self._stream.write(text)
        self._buffer += text
        while "\n" in self._buffer:
            line, _, self._buffer = self._buffer.partition("\n")
            self._log.record(line)
        return len(text)

    def flush(self) -> None:
        self._stream.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


@dataclass
class RunLog:
    """One run's log. Use as a context manager around the whole run."""

    directory: Path
    name: str
    started: float = field(default_factory=time.time)
    stages: list[Stage] = field(default_factory=list)
    path: Path | None = None
    _handle: Any = None
    _previous_stderr: Any = None

    def __post_init__(self) -> None:
        self.directory = Path(self.directory)

    def __enter__(self) -> "RunLog":
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = self.directory / f"{stamp}_{_safe(self.name)}.log"
        self._handle = open(self.path, "w", encoding="utf-8")
        self.record(f"run: {self.name}")
        self._previous_stderr = sys.stderr
        sys.stderr = _Tee(sys.stderr, self)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self.record("ОШИБКА: " + "".join(traceback.format_exception_only(exc_type, exc)).strip())
            for line in traceback.format_tb(tb):
                for part in line.rstrip().split("\n"):
                    self.record(part)
        sys.stderr = self._previous_stderr
        self.record(f"итого: {time.time() - self.started:.1f} сек")
        if self._handle:
            self._handle.close()
        self._append_index(ok=exc is None, error="" if exc is None else repr(exc))
        return False  # never swallow the exception

    def record(self, line: str) -> None:
        if self._handle is None or not line.strip():
            return
        match = _TAG.match(line)
        tag, message = (match.group(1), match.group(2)) if match else ("", line.strip())
        now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        elapsed = f"+{time.time() - self.started:.1f}s"
        self._handle.write(f"{now}  {elapsed:>8}  {tag:<8}| {message}\n")
        self._handle.flush()

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Times one step and records whether it finished."""
        started = time.time()
        self.record(f"[{name}] начало")
        try:
            yield
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
            self.stages.append(
                Stage(name, time.time() - started, ok=False, detail=f"{type(exc).__name__}: {exc}")
            )
            self.record(f"[{name}] ОШИБКА за {time.time() - started:.1f} сек: {exc}")
            raise
        else:
            seconds = time.time() - started
            self.stages.append(Stage(name, seconds))
            self.record(f"[{name}] готово за {seconds:.1f} сек")

    def profile(self) -> list[dict[str, Any]]:
        return [
            {"stage": s.name, "seconds": round(s.seconds, 2), "ok": s.ok, "detail": s.detail}
            for s in sorted(self.stages, key=lambda s: -s.seconds)
        ]

    def _append_index(self, ok: bool, error: str) -> None:
        entry = {
            "run": self.name,
            "started": datetime.fromtimestamp(self.started).isoformat(timespec="seconds"),
            "seconds": round(time.time() - self.started, 2),
            "ok": ok,
            "error": error,
            "log": self.path.name if self.path else "",
            "profile": self.profile(),
        }
        with open(self.directory / INDEX_NAME, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in str(name))[:60] or "run"
