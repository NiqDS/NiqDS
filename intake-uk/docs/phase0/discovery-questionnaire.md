# Discovery questionnaire — enrich the customer portrait

A 5–10 minute structured conversation for every design-partner kickoff (and a
lighter version for any prospect call). Its job: get past the obvious
"chasing documents" pain and surface the **less frequent, higher-value pains**
that a small bundled module could solve — then validate which ones people would
actually pay for.

Run it as a conversation, not a form. Record answers verbatim in
`~/intake-runs/discovery-log.md`, tagged by partner and date. Patterns across
partners matter more than any single answer.

> Interviewer rules: ask, then be quiet. Don't pitch modules until Section D.
> Chase specifics — "how long", "how often", "what happens when it goes wrong".

---

## A. Context (who they are)

1. How many active clients do you run, and what's the mix — sole traders,
   landlords, small Ltds, partnerships?
2. What software is in your stack today (Xero / QBO / FreeAgent; Dext / AutoEntry)?
3. How many clients cross the MTD ITSA threshold (>£50k now, >£30k from 2027)?
4. Roughly how do you charge — fixed monthly, hourly, per return?

_(Why: sizes the ACV and tells us which modules are even relevant.)_

## B. Where the hour goes (time-and-motion)

5. Walk me through what happens from "client sends their stuff" to "I can start
   the books." Where does it stall?
6. Of everything in that flow, **what eats the most time** — and how much, per
   client, per period?
7. What do you do **four times a year now** because of quarterly filing that you
   used to do once?
8. What's the task you most wish you could hand to someone else?

_(Why: quantifies the core pain and reveals adjacent ones. Get numbers.)_

## C. Failure modes (where it goes wrong)

9. When a client's records are wrong or incomplete, how do you catch it today —
   and how often does something slip through to the books?
10. Tell me about the last time an intake mistake cost you real time or an
    awkward client conversation.
11. Onboarding a *new* client — what documents/checks must happen before you can
    act (ID/AML, engagement letter, authority to act)? How painful is that?
12. Anything you're nervous about getting wrong for compliance reasons?

_(Why: surfaces AML/onboarding, CIS, VAT-scheme, and audit-trail pains — prime
module territory — and the emotional stakes that sell.)_

## D. Validate the module menu (only now show options)

"We can bundle small, occasional checks alongside the core intake gate. Which of
these would actually be useful to you — and which would you pay extra for?"

Show 6–8 from `docs/roadmap/adjacent-modules.md`. For each, capture:
`useful? (y/n) · frequency · would pay? (y/n) · notes`.

| Candidate module | Useful? | How often | Pay for it? | Notes |
|------------------|:-------:|-----------|:-----------:|-------|
| New-client onboarding / AML pack completeness | | | | |
| VAT-return-period bundle completeness | | | | |
| CIS subcontractor document checks | | | | |
| Landlord: per-property income/expense completeness | | | | |
| Duplicate / new-supplier fraud sanity check | | | | |
| Year-end / period-end closing checklist | | | | |
| Payroll starter-documents check (P45 / starter checklist) | | | | |
| Companies House / confirmation-statement deadline nudge | | | | |

13. **What's missing from that list** that would genuinely help you? (The most
    valuable answer in the whole call.)

## E. Close

14. If we could wave a wand and fix **one** thing in your intake or month-end,
    what would it be?
15. What would make this a no-brainer to pay for — and what would make you
    distrust it?
16. Who else should I be talking to? (referral)

---

## After the call — turn answers into signal

1. Add each distinct pain to the **discovery log**, one line each, tagged
   `[core] / [adjacent] / [out-of-scope]`.
2. Update the **module scorecard** in `docs/roadmap/adjacent-modules.md`: increment
   "requested-by" and "would-pay" counts per module.
3. Anything mentioned by **≥ 3 of 5 partners** graduates from "idea" to "validated
   backlog". Anything nobody will pay for gets parked, loudly, so we don't build it.
4. Watch for pains that drift into **tax advice / regulated territory** — tag them
   `out-of-scope` and keep the product on the QA side of the line.

## The portrait we're filling in

Each column gets sharper with every call:

- **Trigger** — what makes them feel the pain (a filing deadline, a bounced bundle).
- **Frequency** — daily / quarterly / per-new-client / annual.
- **Current workaround** — spreadsheet, memory, a junior, nothing.
- **Cost of getting it wrong** — time, money, client trust, compliance risk.
- **Willingness to pay** — and whether it's the practice or the end client who pays.
