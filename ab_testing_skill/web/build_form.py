#!/usr/bin/env python3
"""Regenerates the generated web forms from their templates + the JSON catalogs.

Run this after editing metric_scripts/manifest.json or filters.json so the
forms stay in sync with what the skill can actually compute:

    python3 web/build_form.py

Generates:
  web/index.html        <- web/_template.html       + manifest.json
  web/metrics_calc.html <- web/_calc_template.html  + manifest.json + filters.json
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "metric_scripts" / "manifest.json"
FILTERS_PATH = ROOT / "metric_scripts" / "filters.json"


def _inject(template: str, marker: str, payload: list) -> str:
    start_marker = f"/*__{marker}__*/"
    end_marker = f"/*__END_{marker}__*/"
    start = template.index(start_marker) + len(start_marker)
    end = template.index(end_marker)
    return template[:start] + json.dumps(payload, ensure_ascii=False) + template[end:]


def load_metrics() -> list[dict]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return [
        {
            "code": m["code"],
            "label": m["label"],
            "description": m["description"],
            "usable_as": m["usable_as"],
        }
        for m in manifest
    ]


def load_filters() -> list[dict]:
    raw = json.loads(FILTERS_PATH.read_text(encoding="utf-8"))
    return [
        {
            "code": code,
            "label": entry["label"],
            "description": entry.get("description", ""),
            "type": entry.get("type", "categorical"),
            "values": entry.get("values"),
            "applies_to": entry.get("applies_to") or ["*"],
        }
        for code, entry in raw.items()
        if not code.startswith("_")
    ]


def main() -> None:
    metrics = load_metrics()
    filters = load_filters()

    intake = _inject(
        (ROOT / "web" / "_template.html").read_text(encoding="utf-8"),
        "METRICS_CATALOG",
        metrics,
    )
    (ROOT / "web" / "index.html").write_text(intake, encoding="utf-8")
    print(f"wrote {ROOT / 'web' / 'index.html'} ({len(metrics)} metrics)")

    calc = (ROOT / "web" / "_calc_template.html").read_text(encoding="utf-8")
    calc = _inject(calc, "METRICS_CATALOG", metrics)
    calc = _inject(calc, "FILTERS_CATALOG", filters)
    (ROOT / "web" / "metrics_calc.html").write_text(calc, encoding="utf-8")
    print(
        f"wrote {ROOT / 'web' / 'metrics_calc.html'} "
        f"({len(metrics)} metrics, {len(filters)} filters)"
    )


if __name__ == "__main__":
    main()
