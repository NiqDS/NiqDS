# Intake Gate — project status & what's left

_Snapshot of what's built and everything remaining, across code, infra, legal and
business. Owner tags: **[N]** = Nick (relationships, legal, decisions), **[A]** =
Agent (code/docs I can do), **[N+A]** = together._

---

## ✅ Done (built & tested)

- **Deterministic rules engine** — format, arithmetic, temporal, bundle-level
  (VAT check digit, gaps, duplicates, coverage…), single source of truth in
  `registry.yaml`. Eval harness, 12 fixtures + labels, ~81 automated tests,
  **zero false BLOCKs**.
- **LLM adapter** — `mock` (offline default), `anthropic`, `openai` backends
  (real ones code-complete, key-gated).
- **Practice web app** — upload bundle → gap report → chase message.
- **SME scan app** — login (scrypt + session), capture, single-document check,
  result, history.
- **Send to accountant** — multi-select bundle → draft (`mailto` + `.eml` with
  attachments) + Gmail/Microsoft OAuth draft flow (code done, env-gated).
- **JSON API** — `/api/login|scan|scans|scan/{id}|health` (bearer token).
- **iOS app** — SwiftUI `WKWebView` shell, Xcode project + build guide.
- **Concierge CLI**, `run.sh`, README.
- **Strategy pack** — subscription strategy, investor pitch (+PPTX), Business
  Model Canvas / PESTLE / SWOT (RU+EN +PDF), Phase 0 kit, adjacent-modules
  backlog, OAuth setup guide, SME showcase.

---

## 🔧 Code / product — remaining

### P0 — blocks the product actually working for a real user
- **[A] Real extraction from photos (vision/OCR).** Today the pipeline reads
  *text-layer PDFs*; a phone photo has no text, so it's flagged "too blurry".
  Wire the image to a vision model (Claude/GPT vision) or an OCR step so
  "snap a photo → extract" works outside the fixtures. **This is the biggest
  functional gap.**
- ~~**[A] Data retention controls.**~~ ✅ **Done** — configurable auto-delete via
  `INTAKE_RETENTION_DAYS` (`app/retention.py`, runs on startup).

### P1 — needed to be a real multi-user product (Phase 1)
- **[A] Multi-tenancy + Postgres.** Move off single-file SQLite; add `tenant_id`
  isolation; per-tenant client profiles (promote the `client_profiles.json` stub).
- **[A] Hardened auth.** Email verification, password reset, rate limiting,
  session + API-token revocation. (Current auth is prototype-grade.)
- **[A] Billing.** Stripe subscriptions, metered "active clients/month", plan
  gating + overage.
- **[N+A] Real LLM backend validated** on real documents — measure extraction
  accuracy + false positives, harden rules from the feedback loop.

### P2 — expansion / polish
- **[A] Accounting integrations** — Xero/QBO/FreeAgent import + write-back (stubbed).
- **[A] Adjacent modules** — VAT-period, landlord per-property, supplier
  bank-change, onboarding/AML completeness, CIS (designed, gated on discovery).
- **[A] iOS** — native client via the JSON API (optional), app icon + launch
  screen, a "can't reach server" screen, TestFlight build.
- **[A] Observability** — structured logging, error monitoring (e.g. Sentry).
- **[N+A] Security review** before handling real financial data.

---

## ☁️ Infrastructure / deployment
- ✅ **Deployment scaffolding done** — `Dockerfile`, compose, `fly.toml`,
  `Procfile`, Caddyfile, env config, and `docs/setup/deploy.md` (Fly / Lightsail-
  VM / Render recipes).
- ✅ **CI done** — `.github/workflows/ci.yml` runs `pytest` on push.
- ✅ **Security hardening** — headers, Secure cookies behind HTTPS, upload cap.
- **[N+A] Actually deploy** to a host + HTTPS (pick one from the guide). Unblocks
  off-LAN phone, TestFlight, and OAuth.
- **[N] Domain + DNS**; **[A] deploy the marketing site** (`website/`) + fill its
  placeholders.
- **[A] Managed Postgres + object storage** (Phase 1, for scale); **[N+A] Backups.**

---

## ⚖️ Legal / compliance — remaining  (before real client data)
- ✅ **UK GDPR draft pack done** — privacy policy, DPA (you as processor), Terms
  of Service, retention policy in `docs/legal/` (**drafts — need solicitor review**).
- **[N] Company formation** (Ltd) — Companies House.
- **[N] ICO registration** (data-protection fee) — required for processing UK
  personal data.
- **[N] Get the drafts reviewed by a solicitor** and complete every `[bracketed]`
  item + the sub-processor list.
- **[N] Security posture** — encryption at rest for tokens & documents, access
  controls, breach-response process.
- **[N] OAuth app verification** — Google (gmail.compose is a *sensitive* scope →
  app verification before non-test users) and Microsoft Entra consent.
- **[N] AML positioning advice** — keep the onboarding module "completeness
  check, not AML judgement"; stay out of regulated advice / "tax advice".
- **[N] Insurance** — professional indemnity + cyber (once you have customers).
- **[N] IP** — confirm code ownership; consider trademarking "Intake Gate".

---

## 🧾 Administrative / business — remaining
- **[N] Business bank account + bookkeeping** (dogfood it).
- **[N] Stripe account.**
- **[N] Developer/partner programs** — Xero, QuickBooks, FreeAgent (for
  integrations + marketplace listings).
- **[N] Grants** — Innovate UK eligibility/deadlines; R&D tax-relief record-keeping.
- **[N] Pricing** — validate the tiers in Phase 0.

---

## 🚀 Go-to-market / Phase 0 — remaining  (kit is ready in `docs/phase0/`)
Execute the plan in `docs/phase0/phase0-plan.md`:
- **[N] N1 Legal groundwork**, **N2 recruit 5 design partners**, **N3 discovery
  calls**, **N4 secure transfer**, **N5 run concierge bundles**, **N6 capture
  outcomes/quotes**, **N7 validate pricing + approve modules**, **N8 fill site &
  go public**.
- **[A]** on demand from N5/N3: fix rules from real false positives; prototype the
  validated adjacent modules.

---

## Suggested critical path (next 30–60 days)
1. **[N]** Company + ICO + a solicitor-reviewed privacy policy & DPA. _(Blocks real client data.)_
2. **[N+A]** Deploy backend to HTTPS + domain. _(Unblocks phone testing off-LAN, TestFlight, OAuth.)_
3. **[A]** Wire **vision extraction** so real photos work. _(Makes the core loop real.)_
4. **[N]** Recruit 2–3 **design partners**; start concierge runs (Phase 0).
5. **[A]** CI + a light security pass; retention controls.
6. Then, once validated: **[A]** multi-tenancy + Stripe + one adjacent module.

> Rule of thumb: anything touching **real client financial data** needs steps 1
> (legal) done first. Everything before that can run on fixtures/demo data.
