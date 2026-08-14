# Phase 1 prep + SME showcase points

Two parts:
- **Part A** — what Phase 1 actually builds (the platform seam), so it's ready to
  start the moment Phase 0 validates.
- **Part B** — the showcase points to demo *when the SME-facing product is built*,
  as requested. (In the rollout, the practice SaaS is Phase 1 and the SME-facing
  product is Phase 2 — but the SME showcase is captured here now so the build aims
  at it from day one.)

---

## Part A — Phase 1 build (practice self-serve SaaS)

Recap from the strategy note; this is the engineering seam I can start on your go.

1. **Multi-tenancy + auth** — practices, users, roles, per-tenant isolation.
   Migrate `data/gate.db` (SQLite) → Postgres; add a `tenant_id` to every row.
2. **Per-tenant config** — promote `client_profiles.json` and expected-accounts/
   rule settings to real per-tenant records.
3. **Usage metering** — count active clients / bundles per tenant per month (the
   billing signal).
4. **Billing** — Stripe subscriptions + metered overage; the tier matrix from the
   strategy note.
5. **App behind sign-in** — the marketing site (done) stays public; the app moves
   behind login.
6. **Deploy** — a hosted environment + the privacy/DPA posture finalised.

**What stays untouched:** the rules engine, the eval harness, and the doctrine
(model extracts, code validates). Phase 1 wraps the engine; it doesn't rewrite it.
That's why we can move fast and keep the "zero false BLOCKs" guarantee.

**Kick-off checklist when you say go:**
- [ ] Confirm Postgres + hosting target
- [ ] Auth approach (email+password to start, SSO later)
- [ ] Stripe account + the validated price points from Phase 0
- [ ] A tenant data-model migration from the current schema

---

## Part B — SME showcase points (demo these when the SME product ships)

The SME buyer is a sole trader or landlord under MTD who sends records to an
accountant (or files themselves). They are **not** an accountant — so every point
below is about *confidence and less hassle*, in their language, not ours.

**The 60-second SME demo (the spine of any showcase):**
> A messy personal bundle goes in → the screen shows red → a plain-English fix
> list → they fix two things → **green "records ready"** → one tap to send a clean
> bundle to their accountant.

### The points to showcase

1. **One green light before you send.** "Records ready ✓" — the single moment of
   confidence that you're not the one holding up your own tax return.
2. **Plain English, zero jargon.** "Your April bank statement is missing" — never a
   rule code, never accountancy-speak. *(Reuses our client-safe messages.)*
3. **Catches what you can't see.** A whole bank account you forgot, a missing month,
   a receipt you already sent — the invisible gaps, not just per-document typos.
4. **Snap it on your phone.** Photograph a receipt or invoice; if it's too blurry to
   trust, it says so and asks for a clearer photo instead of guessing. *(FMT-LEGIB.)*
5. **Quarterly, made painless.** An MTD-quarter reminder + a one-tap pre-check, so
   the new four-times-a-year cadence isn't four times the stress.
6. **Nothing goes to HMRC.** It's a pre-check you control — no filing, no surprises.
   Removes the #1 fear a nervous first-time digital filer has.
7. **Fewer emails from your accountant.** Send a clean bundle the first time; stop
   the back-and-forth. *(Position as: your accountant will thank you.)*
8. **"Verify this payment" safety nudge.** If a supplier's bank details changed, it
   flags it before you pay — a small anti-fraud win that feels like magic. *(Module M5.)*
9. **Free to start.** Check one business, upgrade only if it earns it. Removes all
   trial friction.
10. **Landlords: nothing per-property slips.** Every property accounted for, each
    quarter — flags a property with no income evidence. *(Module M4, MTD-timely.)*

### What must be true for each point (build dependencies)

| Showcase point | Needs |
|----------------|-------|
| 1, 2, 3, 4, 6 | **Already built** — core engine + client-safe messages + legibility rule |
| 5 | Scheduling/reminders + a simplified SME UI |
| 7 | "Share bundle with accountant" export (clean PDF/summary) |
| 8 | Module M5 (supplier bank-details change) |
| 9 | Billing free tier (Phase 1) |
| 10 | Module M4 (landlord per-property) |

Half the showcase runs on what exists today — the SME demo is mostly a
**re-skin of the engine for a non-expert**, plus two validated modules. That's the
cheap, high-leverage part.

### How to prove it lands (SME success metrics)
- **Activation:** % who run at least one bundle to a "records ready" state.
- **Records-ready rate:** % of bundles that reach green after fixes.
- **Referral loop:** % who use "send to accountant" (the wedge back into practices).
- **Retention across quarters:** do they come back next MTD quarter?

### One-line SME pitch to open any showcase
> "Check your records are complete before you send them — so your accountant isn't
> chasing you, and you're not the one holding up your own return."
