# Turning Intake Gate into a subscription product

_A strategy note: how to package the automation tool into a bundle small
businesses (and the practices that serve them) can subscribe to. Market figures
are cited from the sources at the bottom; all pricing here is an **illustrative
hypothesis to validate**, not a fixed plan._

---

## 1. The tailwind that makes this the right time

**Making Tax Digital for Income Tax (MTD ITSA) is being switched on right now**, and
it changes record-keeping from a once-a-year job into a **quarterly** one:

| From | Who must comply | Cadence change |
|------|-----------------|----------------|
| Apr 2026 | Sole traders + landlords with income **> £50,000** | 4 quarterly digital updates + final declaration, instead of one annual return |
| Apr 2027 | Threshold drops to **> £30,000** | " |
| Apr 2028 | Planned drop to **> £20,000** | " |

Two consequences that point straight at Intake Gate:

1. **The chase happens 4× as often.** Every practice that used to reconcile a
   client's records once a year now has to do it four times. The single most
   painful, least-billable part of that — getting complete, correct records out
   of the client — is exactly what Intake Gate automates.
2. **Hundreds of thousands of new digital filers** are entering the system with
   no habits, sending incomplete bundles. The "you forgot an entire bank
   account / a month of statements" problem gets much bigger.

This is a deadline-driven market with a recurring pain — ideal conditions for a
subscription.

---

## 2. Position it as the layer nobody else owns

Today's tools are **capture** tools — they pull data off documents:

| Tool | Model | Indicative UK price |
|------|-------|---------------------|
| Dext | **per client** (min 10) | ~£25–30/mo small biz; **~£190–240/mo for 10 clients** at practice tier |
| AutoEntry | **per document** (credits) | £14/mo (50 credits) → £469/mo (2,500) |
| Datamolino / Hubdoc | per document | similar per-doc models |

None of them **validate the bundle** or **write the chase**. Intake Gate is not a
capture competitor — it is the **QA + chase layer that sits after capture and
before the books**:

> Capture tools answer "what does this document say?"
> **Intake Gate answers "is this bundle complete and correct, and if not, what's the exact email to send the client?"**

That framing matters for packaging: it lets you sell **alongside** Dext/AutoEntry
(complement, land in existing stacks) rather than rip-and-replace.

---

## 3. Who do you sell the subscription to? (the key fork)

The phrase "small businesses" hides two very different go-to-market motions:

| | **A. Bookkeeping / accountancy practices** (our built ICP) | **B. Small businesses direct** (sole traders, landlords) |
|---|---|---|
| Buyer pain | Acute — chasing clients is their #1 unbillable time-sink | Mild — they don't know records are wrong until the accountant tells them |
| ACV | High (per-client × many clients) | Low (single business) |
| Willingness to pay for tools | High — already buy Dext, Xero practice tools | Low — price-sensitive, already paying £12–55/mo for accounting software |
| Support burden | Low (one savvy buyer serves many) | High (many novices) |
| Distribution | Concentrated — reachable via bodies, marketplaces | Diffuse — expensive to acquire one at a time |

**Recommendation: lead with practices, keep a self-serve SME tier as a funnel.**
Practices are where the money, the concentrated pain, and the MTD urgency all sit.
Selling direct to every sole trader is a high-CAC, low-ACV slog. But a cheap/free
SME tier is still worth having, because:
- it's a **land-and-expand wedge** — an SME who loves it refers their accountant, and vice-versa;
- it's **lead-gen content fuel** for the MTD deadline moment;
- it doubles as the **free tier / demo** funnel for the practice product.

---

## 4. The subscription "bundle" — what you're actually selling

Turning a tool into a subscribable product means bundling the engine with the
things that make it sticky. Three layers:

**Core (the engine you've built)**
- The deterministic UK rules library (VAT, arithmetic, period, gap detection…)
- Gap report + one-click client chase message
- Auditable flags (rule ID + reason + evidence) — the trust differentiator

**Workflow (turns a tool into a habit → this is what justifies a *recurring* fee)**
- **Client profiles** — saved expected accounts, expected document types, period
  cadence per client (you already stub this with `client_profiles.json`)
- **Branded chase templates** — the practice's tone/logo on the email
- **Email/portal intake** — a per-client upload link or forwarding address so
  bundles arrive without manual folder-dragging
- **Status board** — which clients are "records ready" vs "chasing", per quarter
- **Audit log** — every flag and chase, timestamped, for professional cover

**Integrations (raises willingness to pay and switching cost)**
- Import from Dext/AutoEntry and email; export/write-back to Xero, QuickBooks,
  FreeAgent (the connector is stubbed in the MVP — this is the roadmap that
  upgrades the plan)
- Accounting-body / marketplace listings (Xero App Store, QuickBooks app market)

The **value metric** you meter on should be **active clients per month** (a client
run through the gate at least once that month). It aligns with how practices already
buy (Dext is per-client), tracks the value delivered, and is predictable to budget
— better than per-document (feels like a taxi meter) or per-seat (doesn't track value).

---

## 5. An illustrative tier ladder

Anchored to the benchmarks above; **numbers to test, not commit to.**

| Plan | For | Value metric | Indicative price | Key bundle contents |
|------|-----|--------------|------------------|---------------------|
| **Free** | Trial / SME wedge | 1 active client, 5 bundles/mo | £0 | Core rules, gap report, chase (subtle "powered by" footer) |
| **Starter** | Solo bookkeeper | up to 10 active clients | **~£39–49/mo** (≈£4–5/client) | + client profiles, branded chase, email intake |
| **Practice** | Growing practice | up to 40 active clients | **~£129–149/mo** (≈£3.5/client) | + integrations, status board, audit log, priority support |
| **Scale** | Multi-office / franchise | 100+ clients | **custom** | + white-label, API, SSO, onboarding |
| **SME Solo** _(optional, later)_ | Direct sole trader/landlord | 1 business | **~£6–9/mo**, or **free via a partnered accountant** | Core + "records-ready" checklist before they send to their accountant |

Mechanics that make subscriptions work:
- **Annual billing at ~2 months free** (20% off) — the norm in this category and a cash-flow win.
- **Fair-use bundle caps** per plan with **transparent overage** (e.g. £4 per extra active client) so heavy users self-upgrade.
- **Land-and-expand:** practices start on Starter for a few clients, then roll their whole book on as MTD quarters bite.

### Rough unit-economics sanity check
A 40-client practice on the Practice plan ≈ **£1,500–1,800/yr**. If Intake Gate
saves ~1 hour of chasing per client per quarter (4 hrs/yr) at a ~£30–40/hr cost,
that's **£120–160/client/yr of value** — an order of magnitude above the price.
The value story is comfortably there; the job is packaging and distribution, not
justifying the spend.

---

## 6. What has to get built to support "subscription" (the graduation path)

The MVP was deliberately single-tenant with no auth/deploy. A subscription product
needs the pieces the brief scoped out — and this is exactly where the **`vibe`
template's ideas become relevant again** (auth, Postgres, deploy specs, the
website/webapp split), even if implemented in our Python stack rather than adopting
its TypeScript one:

1. **Multi-tenancy + auth** — practices, users, roles; per-tenant data isolation. (Move `data/gate.db` → Postgres.)
2. **Per-tenant rule config & client profiles** — promote the JSON stub to real per-tenant settings.
3. **Usage metering** — count active clients/bundles per tenant per month (this is the billing signal).
4. **Billing** — Stripe subscriptions + metered overage; the plan matrix above.
5. **The public site (done) + the app behind sign-in** — the split we just built the marketing side of.
6. **Deployment** — a hosted environment (the `.do`/deploy-spec idea from vibe).
7. **Data-processing / security posture** — DPA, retention controls, and the privacy policy (templated on the site) finalised, because you're handling client financial documents.

Sequence it so revenue can start before all of that exists (see phases).

---

## 7. Suggested rollout in three phases

**Phase 0 — Design partners (now → 3 months).** Recruit 3–5 practices. Run their
bundles for them (concierge/manual is fine — the engine already works). Charge a
small **founding rate** or trade for **case studies + testimonials** (the exact
placeholders sitting on the new marketing site). Goal: proof, quotes, and a
validated rule library against real messy bundles.

**Phase 1 — Self-serve practice SaaS (3 → 9 months).** Build multi-tenancy, auth,
Stripe, client profiles, email intake. Launch Starter/Practice tiers. Distribution:
MTD-deadline content, accounting bodies (AAT, ICB, ICAEW), and a Xero/QuickBooks
app-marketplace listing.

**Phase 2 — SME wedge + integrations (9 months+).** Ship the write-back connectors
and the free/cheap SME "records-ready" tier as a top-of-funnel and referral loop
into practices. Consider white-label for larger firms.

---

## 8. Moat & risks (be honest)

- **"It's a feature, not a company."** Dext could add validation. Your defensibility
  is (a) the **deterministic, auditable, UK-specific rule library** — a real asset a
  professionally-liable buyer trusts precisely because it's *not* an AI guess — and
  (b) owning the **chase workflow**, not just the check. Deepen both.
- **Regulatory line.** Stay firmly "records QA, not tax advice." The `WARN`/`BLOCK`
  design and "no HMRC submission" stance keep you out of regulated-advice territory —
  keep it that way in marketing copy.
- **Timing risk.** MTD dates have slipped before. Don't build the whole business on a
  single deadline; the "complete & correct records" pain exists with or without MTD —
  MTD just makes it quarterly and urgent.
- **Concierge trap.** Phase 0 manual delivery proves value but doesn't scale — treat
  it as learning, and hold the line on shipping self-serve in Phase 1.

---

## 9. The one-line pitch for each audience

- **To a practice:** _"Run every client's records through the gate before you touch
  the books — it tells you exactly what's missing and writes the chase email. Four
  times a quarter, in seconds, with every flag auditable."_
- **To an SME (via their accountant):** _"Check your records are complete before you
  send them, so your accountant isn't chasing you — and you're not the client
  holding up your own return."_

---

### Sources

- [Making Tax Digital for Sole Traders: 2026 rules, thresholds and deadlines — Companies MadeSimple](https://www.companiesmadesimple.com/blogs/compliance-and-legal/making-tax-digital-for-sole-traders)
- [MTD ITSA further updates — ICAS](https://www.icas.com/news-insights-events/news/tax/further-updates-to-making-tax-digital-for-income-tax-self-assessment-announced)
- [Spring Statement 2025: Making Tax Digital — Deloitte Taxscape](https://taxscape.deloitte.com/measures-spring-statement-2025/making-tax-digital.aspx)
- [Pricing & features: AutoEntry vs Hubdoc vs Dext vs Datamolino 2026 — Datamolino](https://www.datamolino.com/blog/pricing-and-features-autoentry-vs-hubdoc-vs-dext-vs-datamolino-in-2026/)
- [Dext pricing UK 2026 — ThriveOnz360](https://thriveonz360.com/dext-pricing-uk-2026-plans-costs-honest-comparison/)
- [Dext pricing UK 2026: what accountants pay — ReceiptFlow](https://receiptflow.co/blog/dext-pricing-uk-accountants-2026)
- [Xero vs QuickBooks vs FreeAgent 2026 UK pricing — TaxRoot](https://taxroot.co.uk/blog/xero-vs-quickbooks-vs-freeagent-uk)
- [MTD ITSA software comparison — Loyals](https://www.loyals.uk/blog/mtd-itsa-software-comparison)
