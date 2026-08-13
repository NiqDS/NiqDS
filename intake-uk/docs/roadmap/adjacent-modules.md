# Adjacent modules — small subagents for less-obvious pains

Beyond the core job (is this document bundle complete and correct?), there are
**occasional, higher-stakes tasks** in a practice's month that the same
architecture can absorb as small, bundled modules. Individually niche — no single
module suits everyone — but each solves a sharp, specific pain for *some*
segment, and together they turn a one-trick tool into a platform.

This is a **backlog to validate, not a build list.** Nothing here ships until the
discovery calls (`docs/phase0/discovery-questionnaire.md`) show ≥ 3 of 5 partners
want it and would pay. The scorecard at the bottom is where that evidence lands.

---

## What a "module" is in our architecture

Our doctrine holds for every module: **the model extracts, deterministic code
validates.** A module is four small, testable parts — nothing exotic:

1. **Doc type(s)** — one or more new `DocType`s (e.g. `CIS_STATEMENT`, `AML_ID`).
2. **A small extractor subagent** — a focused prompt + schema (a handful of
   few-shot examples) that reads *that* document type into typed JSON. This is the
   "small subagent you train": narrow, specialised, cheap to run and to evaluate.
3. **A deterministic rule pack** — ordinary Python checks (`checks_<module>.py`)
   with entries in `registry.yaml`. **Every pass/fail stays here, never in the
   model.**
4. **Chase snippets** — client-safe message templates for the new rules.

Plus the same test discipline we already use: hand-written JSON fixtures +
ground-truth labels + a slice in the eval harness. If a module can't hit zero
false BLOCKs on fixtures, it doesn't ship.

**The subagent extracts; the rules decide.** Where a task needs *judgement*
(tax treatment, AML risk rating), it is not a rule — it becomes a `WARN` that
escalates to a human. That line is what keeps us sellable and out of regulated
advice.

---

## Tier 1 — Strong fit, same doctrine, painful when they hit

### M1 · New-client onboarding & AML pack completeness
- **Who / when:** every practice, each time they take on a client (occasional, high stakes).
- **Pain:** the pre-work before you can act — ID, proof of address, engagement
  letter, authority to act (64-8/agent authorisation), AML risk form — is scattered
  and easy to start work without.
- **Subagent:** identify which onboarding documents are present and pull key fields
  (name, address, dates, expiry).
- **Deterministic checks:** checklist completeness; ID **expiry** in date; name/address
  **match** across documents; engagement letter signed & dated.
- **⚠ Regulatory line:** we check the pack is **complete**, we do **not** make the AML
  risk judgement — that stays the practitioner's. Market it as "onboarding
  completeness", never "AML compliance done".

### M2 · VAT-return-period bundle completeness
- **Who / when:** VAT-registered clients, **quarterly** (recurring, deadline-driven).
- **Pain:** at VAT time, is everything here to file cleanly?
- **Reuses:** our existing gap-detection and set checks, scoped to a VAT quarter.
- **Deterministic checks:** all months of bank statements present for the quarter;
  sales + purchase invoices present; high-level totals reconcile within tolerance;
  no out-of-period documents. (Strictly completeness/consistency — **no** return
  computation, **no** box-by-box VAT figures.)

### M3 · CIS subcontractor document checks
- **Who / when:** construction-sector bookkeepers (niche, but acute), monthly.
- **Pain:** CIS paperwork is fiddly and penalised if wrong.
- **Subagent:** extract subcontractor invoices / CIS statements.
- **Deterministic checks:** UTR present & correct format; verification number present;
  deduction **rate** is one of the valid values (0/20/30%); monthly statement set
  complete per subcontractor. (Format/completeness only — **not** the tax deducted.)

### M4 · Landlord per-property completeness  ⭐ MTD-timely
- **Who / when:** landlords under MTD ITSA (quarterly) and the practices serving them.
- **Pain:** exactly the SET-ACCT problem, but for **properties** — a whole property
  with no income evidence is invisible today.
- **Subagent:** extract per-property rent/agent statements and mortgage-interest certificates.
- **Deterministic checks:** every declared property has income evidence for the period;
  expected expense docs present; flag a property with zero documents (BLOCK); FX/rounding
  sanity. Directly rides the MTD-for-landlords wave.

---

## Tier 2 — Deterministic sanity checks, broad appeal

### M5 · New-supplier & changed-bank-details sanity  ⭐ fraud-adjacent
- **Who / when:** any client, every bundle (recurring, cheap).
- **Pain:** invoice-redirection fraud and typo'd new payees are a real SME loss.
- **Subagent:** extract supplier + payee bank details from invoices.
- **Deterministic checks:** supplier never seen before → confirm-this-payee nudge;
  a **known** supplier whose bank details **changed** vs prior bundles → WARN.
  (A nudge to verify, **not** a fraud determination.)

### M6 · Duplicate-payment / already-paid sanity
- Extends existing SET-DUP to flag an invoice that matches one already marked paid
  in a prior period. Low effort, high "saved me money" value.

---

## Tier 3 — Deadline & admin nudges (low-doc, calendar-driven)

### M7 · Statutory deadline nudges
- Companies House confirmation statement / accounts filing / VAT / payroll dates.
  Mostly a date engine with minimal extraction. Occasional but universally relevant;
  cheap to build. Keep it a **reminder**, not filing.

### M8 · Payroll starter-documents check
- **When:** a new employee joins (occasional). Subagent extracts P45 / starter
  checklist; deterministic: presence, NI-number format, start-date sanity, RTI-ready.

---

## Tier 4 — Vertical / niche (park until a partner asks)

R&D or grant-claim evidence bundles · charity/SORP receipts · foreign-currency
FX-rate sanity on invoices · director's-loan documentation · fixed-asset
capital-vs-revenue evidence · insurance-renewal docs. Real for a few; build only
on demand.

---

## ⛔ Out of scope — keep on the QA side of the line

Tag these `out-of-scope` loudly whenever they come up in discovery:

- Computing tax liability or VAT return **figures**.
- Categorisation / tax-treatment / "is this allowable?" **advice**.
- Making the **AML risk judgement** (vs checking the pack is complete).
- Anything requiring professional judgement to evaluate.

These violate the doctrine (judgement ≠ rule) and drag us into regulated advice.
The most we ever do is `WARN` and escalate to a human.

---

## Scorecard (fill from discovery calls)

`Fit` = doctrine fit. `Reg` = regulatory caution (🟢 low / 🟠 handle-with-care).
`Effort` = build size. `Req` / `Pay` = # partners (of 5) who want it / would pay.

| ID | Module | Persona | Frequency | Pain | Fit | Reg | Effort | Req | Pay |
|----|--------|---------|-----------|:----:|:---:|:---:|:------:|:---:|:---:|
| M1 | Onboarding / AML completeness | All practices | Per new client | High | ✅ | 🟠 | M | – | – |
| M2 | VAT-period completeness | VAT clients | Quarterly | High | ✅ | 🟢 | S | – | – |
| M3 | CIS document checks | Construction | Monthly | High | ✅ | 🟠 | M | – | – |
| M4 | Landlord per-property | Landlords (MTD) | Quarterly | High | ✅ | 🟢 | M | – | – |
| M5 | New-supplier / bank-change | All | Per bundle | High | ✅ | 🟢 | S | – | – |
| M6 | Duplicate / already-paid | All | Per bundle | Med | ✅ | 🟢 | S | – | – |
| M7 | Deadline nudges | All | Annual/quarterly | Med | ✅ | 🟢 | S | – | – |
| M8 | Payroll starter docs | With payroll | Per new hire | Med | ✅ | 🟠 | S | – | – |

## Recommended first prototypes (pending validation)

If the discovery calls back them, prototype **M4 (landlord per-property)** and
**M2 (VAT-period completeness)** first: both ride the MTD tailwind, both mostly
**reuse the set-check machinery we already have** (so they're small), and both are
🟢 on the regulatory line. Add **M5 (bank-details change)** as a cheap, broadly
loved "it saved me money" hook. Hold M1/M3 until a partner with that exact pain
signs up — they're higher-value but need care.
