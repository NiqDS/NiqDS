# Phase 0 — plan & ownership

**Goal:** 3–5 design partners, ≥ 20 real bundles run, a measured before/after per
partner, 2–3 permitted case studies, and a validated module backlog — with **zero
unresolved false BLOCKs**.

Two owners: **Nick** (relationships, judgement, legal, real-data operations) and
**Agent** (code, docs, prep — anything that doesn't need Nick's network or a
solicitor).

---

## Nick's tasks (human-only)

| # | Task | Why it's yours | Blocks |
|---|------|----------------|--------|
| N1 | **Legal groundwork** — get the concierge agreement + privacy policy/DPA reviewed by a solicitor; register with the ICO if required | Legal sign-off + liability | ⚠ Blocks handling real client data (N5) |
| N2 | **Recruit partners** — work the channels in the pitch §3, send outreach §4, book calls; aim for 5 | Needs your relationships & credibility | Everything downstream |
| N3 | **Run discovery calls** — use `discovery-questionnaire.md`; log verbatim | Human conversation & judgement | Module validation |
| N4 | **Set up secure transfer** per partner (portal export / encrypted share) | Trust + data protection | N5 |
| N5 | **Operate concierge runs** — run `app/cli.py` on real bundles, review every flag before sending | You hold the client relationship & the false-positive judgement | Case studies |
| N6 | **Capture outcomes** — fill the run log & discovery log; get quotes + one hard number per partner | Evidence base | Site placeholders, pricing |
| N7 | **Business calls** — validate pricing, approve which modules to build, decide company/registration | Owner decisions | Phase 1 scope |
| N8 | **Fill site + go public** — real quotes/photo/address into `website/` placeholders, buy domain, deploy | Real content & spend | Public launch |

**Do first:** N1 (legal, so real data is unblocked) and N2 (recruiting) in parallel —
N1 has lead time, N2 is the long pole.

## Agent's tasks (I handle these)

| # | Task | Status |
|---|------|--------|
| A1 | Add "where to find partners" channels to the pitch | ✅ done this turn |
| A2 | Capture templates (run log + discovery log) so N6 is frictionless | ✅ done this turn (`docs/phase0/templates/`) |
| A3 | This Phase 0 plan / ownership split | ✅ done this turn |
| A4 | Prep Phase 1 + SME showcase points | ✅ done this turn (`docs/phase1/`) |
| A5 | **Fix rules from false positives** you report from real runs (N5→feedback loop) | ⏳ on demand — send me the doc + why it misfired |
| A6 | **Prototype validated modules** (likely M4 landlord / M2 VAT-period) once discovery backs them | ⏳ gated on N3/N7 |
| A7 | Keep the eval green; harden extraction on real document shapes you hit | ⏳ ongoing as real bundles surface issues |

**My blockers are your outputs:** A5–A7 need real bundles and discovery signal
from N3/N5/N6. Until those exist, I've done everything Phase 0 allows on my side,
so I've moved on to prepping Phase 1 (below).

---

## The feedback loop (how we work together in Phase 0)

```
N2/N3 recruit + interview ──▶ discovery log ──▶ A6 module backlog (validated only)
N5 real runs ──▶ false positives / misses ──▶ A5 rules fixes ──▶ re-run (zero false BLOCKs)
N6 quotes + numbers ──▶ N8 site placeholders + N7 pricing
```

When you hit a false BLOCK or a missed problem in a real run, send me: the
document (or a redacted version), what the gate said, and what it *should* have
said. That's the single most valuable thing you can hand me in Phase 0.

## Definition of done (Phase 0 → Phase 1)

- [ ] 3–5 partners active, ≥ 20 bundles run
- [ ] Before/after time + accuracy number per partner
- [ ] Zero unresolved false BLOCKs across the set
- [ ] ≥ 2 modules validated by ≥ 3 partners (would-pay), backlog prioritised
- [ ] 2–3 case studies / quotes with permission, live on the site
- [ ] Pricing hypothesis confirmed or revised with real reactions
