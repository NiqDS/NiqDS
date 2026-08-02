"""Build the gap report from a bundle's flags.

Grouped by document, then bundle-level. Includes a one-line summary. Every flag
carries its rule id, severity, offending value and reason, so any entry can be
traced back to the named rule that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import Bundle, Flag
from app.rules.engine import sort_flags


@dataclass
class DocumentReport:
    source_file: str
    flags: list[Flag] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(f.severity == "BLOCK" for f in self.flags)


@dataclass
class GapReport:
    bundle_id: str
    client_name: str
    summary: str
    documents: list[DocumentReport]
    bundle_flags: list[Flag]
    counts: dict[str, int]


def build_gap_report(bundle: Bundle, flags: list[Flag]) -> GapReport:
    flags = sort_flags(flags)

    by_doc: dict[str, list[Flag]] = {d.source_file: [] for d in bundle.documents}
    bundle_flags: list[Flag] = []
    for f in flags:
        if f.document is None:
            bundle_flags.append(f)
        else:
            by_doc.setdefault(f.document, []).append(f)

    documents = [DocumentReport(source_file=d.source_file, flags=by_doc.get(d.source_file, []))
                 for d in bundle.documents]

    total_docs = len(bundle.documents)
    passed_docs = sum(1 for d in documents if d.passed)
    blocks = sum(1 for f in flags if f.severity == "BLOCK")
    warns = sum(1 for f in flags if f.severity == "WARN")

    summary = (
        f"{passed_docs} of {total_docs} documents passed. "
        f"{blocks} blocking issue{'s' if blocks != 1 else ''}, "
        f"{warns} warning{'s' if warns != 1 else ''}."
    )

    return GapReport(
        bundle_id=bundle.bundle_id,
        client_name=bundle.client_name,
        summary=summary,
        documents=documents,
        bundle_flags=bundle_flags,
        counts={"total": total_docs, "passed": passed_docs, "block": blocks, "warn": warns},
    )
