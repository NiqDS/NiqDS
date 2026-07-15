#!/usr/bin/env python3
"""Regenerates web/index.html from web/_template.html + metric_scripts/manifest.json.

Run this after editing the metric catalog so the intake form's checkbox
list stays in sync with what the skill can actually compute:

    python3 web/build_form.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = ROOT / "web" / "_template.html"
MANIFEST_PATH = ROOT / "metric_scripts" / "manifest.json"
OUTPUT_PATH = ROOT / "web" / "index.html"

START_MARKER = "/*__METRICS_CATALOG__*/"
END_MARKER = "/*__END_METRICS_CATALOG__*/"


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    catalog = [
        {
            "code": m["code"],
            "label": m["label"],
            "description": m["description"],
            "usable_as": m["usable_as"],
        }
        for m in manifest
    ]
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    start = template.index(START_MARKER) + len(START_MARKER)
    end = template.index(END_MARKER)
    rendered = (
        template[:start]
        + json.dumps(catalog, ensure_ascii=False)
        + template[end:]
    )
    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT_PATH} ({len(catalog)} metrics)")


if __name__ == "__main__":
    main()
