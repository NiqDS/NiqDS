"""Evaluation harness.

Reports, per rule:
  * precision — of the flags this rule raised, how many were in the ground truth
  * recall    — of the ground-truth instances, how many were caught
  * false-positive examples — printed in full (these are what a practice complains
    about)

Also reports extraction field accuracy separately from rule accuracy (they fail
for different reasons and must be debugged separately).

Run:  python eval/run_eval.py
Output: eval/report.md  (also printed to stdout)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ingest.extract import extract_path  # noqa: E402
from app.models import Flag  # noqa: E402
from app.rules import checks_temporal  # noqa: E402
from app.rules.engine import run_bundle  # noqa: E402
from app.scenarios import (  # noqa: E402
    build_bundle,
    load_extracted,
    load_labels,
    scenario_meta,
    scenario_names,
)

FIXED_TODAY = date(2026, 8, 2)
DOCS_DIR = ROOT / "fixtures" / "documents"
REPORT = ROOT / "eval" / "report.md"


@dataclass
class GroundTruth:
    rule_id: str
    document: str | None
    evidence_contains: str | None = None


@dataclass
class RuleStats:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    fp_examples: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float:
        d = self.tp + self.fp
        return self.tp / d if d else 1.0

    @property
    def recall(self) -> float:
        d = self.tp + self.fn
        return self.tp / d if d else 1.0


def _ground_truth(bundle_id: str) -> list[GroundTruth]:
    meta = scenario_meta(bundle_id)
    gts: list[GroundTruth] = []
    for stem in meta["documents"]:
        source_file = load_extracted(stem).source_file
        for rule_id in load_labels(stem):
            gts.append(GroundTruth(rule_id, source_file))
    for spec in meta.get("bundle_flags", []):
        gts.append(GroundTruth(spec["rule_id"], None, spec.get("evidence_contains")))
    return gts


def _matches(pred: Flag, gt: GroundTruth) -> bool:
    if pred.rule_id != gt.rule_id or pred.document != gt.document:
        return False
    if gt.evidence_contains is None:
        return True
    haystack = (pred.message or "") + (pred.evidence or "")
    return gt.evidence_contains in haystack


def evaluate_rules() -> tuple[dict[str, RuleStats], list[str]]:
    checks_temporal.set_today(FIXED_TODAY)
    stats: dict[str, RuleStats] = {}
    all_rule_ids: set[str] = set()

    for bundle_id in scenario_names():
        bundle = build_bundle(bundle_id)
        predicted = run_bundle(bundle)
        gts = _ground_truth(bundle_id)
        for g in gts:
            all_rule_ids.add(g.rule_id)
        for p in predicted:
            all_rule_ids.add(p.rule_id)

        unmatched_gt = list(gts)
        for p in predicted:
            hit = next((g for g in unmatched_gt if _matches(p, g)), None)
            st = stats.setdefault(p.rule_id, RuleStats())
            if hit is not None:
                st.tp += 1
                unmatched_gt.remove(hit)
            else:
                st.fp += 1
                st.fp_examples.append(
                    f"[{bundle_id}] {p.document or 'bundle'} — {p.message}"
                )
        for g in unmatched_gt:
            stats.setdefault(g.rule_id, RuleStats()).fn += 1

    for rid in all_rule_ids:
        stats.setdefault(rid, RuleStats())
    checks_temporal.set_today(None)
    return stats, sorted(all_rule_ids)


# --- extraction field accuracy ---------------------------------------------

FIELDS = ["document_date", "gross_total", "supplier_vat_number", "doc_type"]


def _field_value(doc, name):
    v = getattr(doc, name)
    if name == "gross_total":
        return None if v is None else f"{v.amount} {v.currency}"
    if name == "doc_type":
        return v.value
    if name == "document_date":
        return v.isoformat() if v else None
    return v


def evaluate_extraction(backend: str | None = None) -> dict[str, tuple[int, int]]:
    results = {f: [0, 0] for f in FIELDS}
    for stem_path in sorted((ROOT / "fixtures" / "extracted").glob("*.json")):
        stem = stem_path.stem
        truth = load_extracted(stem)
        pdf = DOCS_DIR / truth.source_file
        if not pdf.exists():
            continue
        got = extract_path(pdf, backend=backend)
        for f in FIELDS:
            results[f][1] += 1
            if _field_value(got, f) == _field_value(truth, f):
                results[f][0] += 1
    return {f: (c[0], c[1]) for f, c in results.items()}


def build_report() -> str:
    stats, rule_ids = evaluate_rules()
    extraction = evaluate_extraction()

    lines: list[str] = ["# Intake Gate — evaluation report", ""]
    lines.append(f"_Generated with fixed date {FIXED_TODAY.isoformat()} on the fixture set._")
    lines.append("")

    lines.append("## Rule accuracy")
    lines.append("")
    lines.append("| Rule | TP | FP | FN | Precision | Recall |")
    lines.append("|------|----|----|----|-----------|--------|")
    block_fp = 0
    from app.rules.engine import REGISTRY

    for rid in rule_ids:
        s = stats[rid]
        if REGISTRY.get(rid) and REGISTRY[rid].severity == "BLOCK":
            block_fp += s.fp
        lines.append(
            f"| {rid} | {s.tp} | {s.fp} | {s.fn} | "
            f"{s.precision:.2f} | {s.recall:.2f} |"
        )
    lines.append("")

    lines.append(f"**False positives on BLOCK-severity rules: {block_fp}** "
                 f"(target for the demo: 0).")
    lines.append("")

    fp_all = [ex for s in stats.values() for ex in s.fp_examples]
    lines.append("## False-positive examples")
    lines.append("")
    if fp_all:
        for ex in fp_all:
            lines.append(f"- {ex}")
    else:
        lines.append("_None — no rule raised a flag that wasn't in the ground truth._")
    lines.append("")

    lines.append("## Extraction field accuracy")
    lines.append("")
    lines.append("_Measured separately from rule accuracy — extraction and rules "
                 "fail for different reasons._")
    lines.append("")
    lines.append("| Field | Correct | Total | Accuracy |")
    lines.append("|-------|---------|-------|----------|")
    for f, (correct, total) in extraction.items():
        acc = correct / total if total else 1.0
        lines.append(f"| {f} | {correct} | {total} | {acc:.2f} |")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    report = build_report()
    REPORT.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nWritten to {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
