# Data Processing Agreement (DPA) — DRAFT

> Draft for solicitor review. This is the agreement a **practice customer (the
> Controller)** signs with **Intake Gate (the Processor)** under UK GDPR Art. 28.
> Complete every `[bracketed]` item and the Annexes.

**Parties**
- **Controller:** the customer — `[Practice name]`.
- **Processor:** `[Registered company name]` (`[company number]`), `[address]`.

This DPA forms part of the Terms of Service between the parties. Where it conflicts
with the Terms on data protection, this DPA prevails.

## 1. Definitions
"UK GDPR", "personal data", "processing", "data subject", "controller",
"processor", "sub-processor" have the meanings in the UK GDPR and Data Protection
Act 2018.

## 2. Processing details
The Processor processes personal data only to provide the service. Subject matter,
duration, nature and purpose, categories of data subjects and personal data are set
out in **Annex 1**.

## 3. Processor obligations
The Processor shall:
1. Process personal data only on the Controller's **documented instructions**
   (including transfers), unless required by law (and then notify unless prohibited).
2. Ensure persons authorised to process are under a duty of **confidentiality**.
3. Implement appropriate **technical and organisational measures** (UK GDPR Art. 32)
   — see **Annex 2**.
4. Engage **sub-processors** only per clause 4.
5. Taking account of the nature of processing, **assist the Controller** with
   responding to data-subject rights requests.
6. **Assist the Controller** with security, breach notification, DPIAs and prior
   consultation (Arts. 32–36).
7. Notify the Controller **without undue delay** (and in any case within `[72 hours]`)
   after becoming aware of a **personal data breach**.
8. At the Controller's choice, **delete or return** all personal data at the end of
   the service and delete existing copies, unless law requires storage.
9. Make available information necessary to demonstrate compliance and allow for and
   contribute to **audits** `[scope/frequency]`.

## 4. Sub-processors
The Controller gives **general authorisation** for the sub-processors listed in
**Annex 3**. The Processor will inform the Controller of intended changes and give
the Controller the opportunity to object `[notice period]`. The Processor remains
liable for its sub-processors' data-protection obligations.

## 5. International transfers
The Processor will not transfer personal data outside the UK without an appropriate
safeguard (**UK IDTA / SCCs**) and, where required, the Controller's instruction.
Transfers, if any, are identified in Annex 3.

## 6. Liability & term
Liability is subject to the limits in the Terms of Service. This DPA lasts for the
duration of the processing.

---

## Annex 1 — Details of processing
- **Subject matter:** quality-assurance checks on client financial documents.
- **Duration:** the term of the service.
- **Nature & purpose:** ingest, extract to structured data, run deterministic rule
  checks, and produce a gap report and client chase message / email draft.
- **Categories of data subjects:** the Controller's clients and their suppliers/
  contacts (e.g. sole traders, landlords, business contacts).
- **Categories of personal data:** names, business contact details, addresses,
  bank/account identifiers, VAT numbers, invoice/receipt/statement contents,
  financial amounts. `[Confirm no special-category data is expected.]`

## Annex 2 — Technical & organisational measures
`[Complete to match reality]` — e.g.: HTTPS/TLS in transit; encryption at rest for
credentials and OAuth tokens; access controls and least privilege; OAuth limited to
draft-creation (no inbox read, no send); configurable data retention with automatic
deletion; audit logging of rule decisions; regular dependency updates; breach-
response process; backups `[details]`.

## Annex 3 — Approved sub-processors
| Sub-processor | Purpose | Location | Transfer safeguard |
|---------------|---------|----------|--------------------|
| `[Hosting provider]` | Application hosting & storage | `[UK/EU?]` | `[IDTA/SCCs if outside UK]` |
| `[LLM provider, if enabled]` | Document data extraction | `[country]` | `[safeguard]` |
| `[Email/OAuth provider]` | Creating email drafts | `[country]` | `[safeguard]` |
