# Design-partner pitch kit (Phase 0)

Everything you need to sign 3–5 practices as design partners: the one-page pitch,
the free-concierge offer, outreach templates, and — built in — a way to surface
the pains we *don't* already know about, so we enrich the customer portrait while
we recruit.

Target partner: a **UK bookkeeping practice or independent bookkeeper with
5–40 clients**, ideally with a few clients crossing the MTD ITSA threshold.

---

## 1. The one-pager (pitch)

> **Stop chasing clients for the same missing records.**
>
> Intake Gate checks every client bundle against 20+ UK bookkeeping rules the
> moment it lands, and writes the exact chase email naming what's missing or
> wrong — a missing month of bank statements, an invalid VAT number, an
> out-of-period invoice, a whole account the client forgot.
>
> **Why now:** from April 2026, MTD for Income Tax turns record-keeping into a
> *quarterly* job. The chase you do once a year, you'll do four times.
>
> **Why it's trustworthy:** every flag has a rule ID, a plain-English reason and
> the offending value. It's deterministic code, not an AI guess — you can audit
> exactly why anything failed. Nothing is submitted to HMRC.
>
> **The ask:** be one of five founding design partners. We run your intake for
> free for 8 weeks. You tell us what's still painful.

Keep it to that. One problem, one proof, one ask.

---

## 2. The offer (what a design partner gets — and gives)

**They get**
- Free concierge intake for **8 weeks** (we run their bundles by hand — see the
  runbook). No software to install, no change to their workflow.
- A ready-to-send chase email per bundle, and a "records-ready" status per client.
- Direct line to shape the rules — their edge cases become product.
- **Founding pricing locked** when the self-serve product launches (e.g. 50% off
  for 12 months).

**They give**
- ~30 min kickoff + a 20-min check-in each fortnight.
- Real (anonymisable) bundles to run.
- If it delivers: a short **testimonial and one hard number** we can quote
  (hours saved, emails avoided), and — ideally — a named case study.

**Guardrails (say these up front, they build trust):**
- No HMRC submission, ever. It's a pre-submission QA gate.
- They remain the data controller; we're a processor on their instruction.
- Documents retained only for the run, then deleted (agree the window).
- It's records QA, **not tax advice**.

---

## 3. Outreach templates

Keep the first touch short and about *their* pain, not our features. Always end
with a low-friction question that starts a conversation (and doubles as discovery).

**Cold email / LinkedIn DM**
> Subject: the MTD chase, four times a year
>
> Hi [name] — quick one. With MTD for Income Tax landing in April, the
> record-chasing that used to be a once-a-year scramble becomes quarterly.
>
> I've built a tool that checks a client's bundle the moment it lands and drafts
> the exact chase email — missing statements, dud VAT numbers, out-of-period
> invoices, whole accounts a client forgot. Deterministic, auditable, nothing
> goes to HMRC.
>
> I'm taking on five founding practices to run their intake **free for 8 weeks**
> in exchange for honest feedback. Worth a 15-minute look?
>
> Either way — **what part of client intake eats the most of your time right
> now?** Genuinely curious.

**Warm intro / referral**
> [Referrer] thought we should talk. I run intake QA for bookkeeping practices —
> the "what's missing / what's wrong before I touch the books" step. Doing it
> free for a handful of founding partners ahead of the MTD quarters. Could I show
> you a broken bookkeeping bundle turn into a chase email in 60 seconds?

**Follow-up (no reply)**
> No worries if the timing's off. One thing that might be useful regardless:
> [link to the site / a 60-sec demo clip]. And if intake isn't your pain — what
> is? Always trying to understand where the hour actually goes.

---

## 4. The discovery hook (enrich the portrait while you pitch)

Every conversation is a research opportunity. The goal is to find the **less
obvious pains** — the ones outside "checking documents" — that a small bundled
module could solve (see `docs/roadmap/adjacent-modules.md`).

Two ways to gather it, low-friction:

1. **The one open question**, in every outreach and every call:
   *"What part of client intake / month-end eats the most of your time right now?"*
   Then shut up and listen. Log the answer verbatim.

2. **A 5-minute structured discovery** on the kickoff call — the
   `discovery-questionnaire.md` in this folder. It ends by showing a short menu
   of candidate modules and asking which they'd actually pay for, so we validate
   the backlog against real demand instead of guessing.

Capture everything in one place (`~/intake-runs/discovery-log.md`), tagged by
partner. Patterns across 5 partners are worth more than any single feature request.

---

## 5. Qualifying: who makes a good design partner

| Good fit | Poor fit |
|----------|----------|
| 5–40 clients, some near MTD threshold | Single-client in-house bookkeeper |
| Feels the chase pain, complains about it unprompted | Fully automated already, no pain |
| Willing to give 2×20 min / month | Can't commit any time |
| Open to being named in a case study (eventually) | Can never be referenced |
| Handles sole traders / landlords / small Ltd | Only large audited entities |

Five engaged partners beat twenty passive ones. Optimise for feedback quality.

---

## 6. Success criteria for the kit

- 5 founding partners signed within [X] weeks.
- A discovery log with ≥ 15 distinct pains captured and clustered.
- At least 2 adjacent-module candidates validated by ≥ 3 partners each.
- The marketing site's case-study / review placeholders filled with real, permitted quotes.
