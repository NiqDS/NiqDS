# Legal starter pack — DRAFTS

> ⚠️ **These are drafts, not legal advice.** They give your solicitor a strong,
> UK-specific starting point so you pay for review, not authoring. Before anything
> here goes live: have a **qualified solicitor** review it, complete every
> `[bracketed]` item, and confirm it fits how the product actually processes data.

## What's here

| File | What it is | Who signs / sees it |
|------|-----------|---------------------|
| `privacy-policy.md` | How you handle personal data (public-facing) | Published on your site |
| `data-processing-agreement.md` | You as **processor** for a practice's client data | Signed with each practice customer |
| `terms-of-service.md` | The SaaS contract | Accepted by customers |
| `data-retention-policy.md` | What's kept, how long, how it's deleted | Internal + referenced by the above |

## Why these specific documents

You handle **client financial documents on behalf of bookkeeping practices**, which
makes you a **data processor** (the practice is the **controller**). UK GDPR then
requires a written processor agreement (the DPA) — most practices will ask for one
before they send you anything. The privacy policy and retention policy support it.

## Before launch — checklist

- [ ] **Solicitor review** of all four documents.
- [ ] **Register with the ICO** (data-protection fee) — required for processing UK
      personal data. <https://ico.org.uk/registration>
- [ ] Complete every `[bracketed]` field (company name/number, address, DPO/contact,
      retention periods, governing law, sub-processor list).
- [ ] Confirm the **sub-processor list** matches reality — at minimum your **hosting
      provider**, any **LLM provider** you enable (document text/images are sent to
      it), and your **email/OAuth providers**.
- [ ] Decide **international transfer** mechanics if any sub-processor is outside the
      UK (UK IDTA / SCCs).
- [ ] Keep the product's **"records QA, not tax advice; no HMRC submission"** line in
      the ToS and marketing — it's both true and what keeps you out of regulated
      advice.

## Keep them honest
The code already backs these up: configurable retention (`INTAKE_RETENTION_DAYS`),
least-privilege OAuth (drafts only), and no HMRC submission. Don't promise in the
policy what the product doesn't do.
