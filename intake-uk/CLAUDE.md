# CLAUDE.md — Intake Gate (UK) MVP

Build brief for Claude Code. Target: a locally runnable prototype that demonstrates the core loop end to end and can be shown to a bookkeeping practice in a live meeting.

---

## Objective

Build a local service that ingests a bundle of client documents, extracts them to typed records, validates them against a deterministic UK rules engine, and emits (a) a gap report and (b) a ready-to-send chase message naming exactly what is missing or wrong.

**Success = a practice owner watches a broken bundle go in and a correct, specific chase email come out, in under 60 seconds, with every flag traceable to a named rule.**

## Non-goals for the MVP

- No HMRC submission. No MTD API integration. Ever, in this prototype.
- No accounting-system write-back (stub the connector interface only).
- No authentication, multi-tenancy, or deployment concerns.
- No categorisation, tax treatment, or advisory logic.
- No fine-tuning or model training.

---

## Hard architectural constraint

**The model extracts. Deterministic code validates.**

The LLM's only job is turning a document into typed JSON. Every pass/fail decision is made by ordinary Python running a named rule, and every flag carries a rule ID, a human-readable reason, and the field it fired on. No validation decision may depend on model inference. This is non-negotiable — it is the property that makes the product sellable to a professionally liable buyer, and it is also what makes the system testable.

Consequence: the rules engine must be runnable and fully testable **without any model or API key**, against hand-written JSON fixtures.

---

## Stack

- Python 3.11+
- FastAPI + Uvicorn (API), Jinja2 templates for a minimal UI — no frontend framework
- Pydantic v2 for all schemas
- SQLite via `sqlite3` or SQLModel — single file `data/gate.db`
- `pdfplumber` for text-layer PDFs, `pypdfium2` for rasterising scans, `Pillow` for images
- LLM access through a thin adapter with three backends: `anthropic`, `openai`, `mock`. Default to `mock` so the repo runs offline out of the box.
- `pytest` for tests
- `uv` or plain `venv` + `requirements.txt` — no Docker in the MVP

---

## Repository layout

```
intake-gate-uk/
├── CLAUDE.md
├── README.md
├── requirements.txt
├── run.sh                       # one command to start everything
├── app/
│   ├── main.py                  # FastAPI app, routes
│   ├── models.py                # Pydantic schemas
│   ├── db.py                    # SQLite init + queries
│   ├── ingest/
│   │   ├── loader.py            # file → pages (text or raster)
│   │   ├── classify.py          # document type classification
│   │   └── extract.py           # page(s) → typed record via LLM adapter
│   ├── llm/
│   │   ├── adapter.py           # provider-agnostic interface
│   │   └── mock.py              # deterministic fake extractor for offline runs
│   ├── rules/
│   │   ├── engine.py            # rule registry + runner
│   │   ├── checks_format.py     # VAT no., postcode, sort code, dates
│   │   ├── checks_arithmetic.py # net + VAT = gross, line sums
│   │   ├── checks_temporal.py   # period boundaries
│   │   ├── checks_set.py        # bundle-level: gaps, duplicates, coverage
│   │   └── registry.yaml        # rule metadata: id, severity, message template
│   ├── report/
│   │   ├── gaps.py              # build the gap report
│   │   └── chase.py             # build the client chase message
│   └── templates/               # upload.html, bundle.html, report.html
├── fixtures/
│   ├── documents/               # sample PDFs/images (see "Fixtures" below)
│   ├── extracted/               # hand-written JSON — tests the rules engine alone
│   └── labels/                  # ground-truth expected flags per fixture
├── eval/
│   ├── run_eval.py              # precision/recall per rule
│   └── report.md                # generated output
└── tests/
    ├── test_rules_format.py
    ├── test_rules_arithmetic.py
    ├── test_rules_temporal.py
    ├── test_rules_set.py
    └── test_pipeline.py
```

---

## Data model

### Document types (MVP scope — keep it to four)

`PURCHASE_INVOICE` · `RECEIPT` · `BANK_STATEMENT` · `SALES_INVOICE`

Anything else → `UNKNOWN`, which is itself a flag, not a silent pass.

### Core schemas (Pydantic)

```python
class Money(BaseModel):
    amount: Decimal          # never float
    currency: str = "GBP"

class LineItem(BaseModel):
    description: str | None
    quantity: Decimal | None
    unit_price: Money | None
    net: Money | None
    vat_rate: Decimal | None
    vat: Money | None
    gross: Money | None

class ExtractedDocument(BaseModel):
    source_file: str
    doc_type: DocType
    confidence: float                 # extraction confidence, NOT a pass/fail input
    supplier_name: str | None
    supplier_vat_number: str | None
    customer_name: str | None
    document_number: str | None
    document_date: date | None
    period_start: date | None         # bank statements
    period_end: date | None
    net_total: Money | None
    vat_total: Money | None
    gross_total: Money | None
    line_items: list[LineItem] = []
    account_identifier: str | None    # last 4 of account, or sort code
    raw_text_excerpt: str             # for audit trail
    page_count: int

class Bundle(BaseModel):
    bundle_id: str
    client_name: str
    declared_period_start: date        # what the client SAYS this covers
    declared_period_end: date
    expected_accounts: list[str] = []  # e.g. ["12345678", "87654321"]
    documents: list[ExtractedDocument]

class Flag(BaseModel):
    rule_id: str
    severity: Literal["BLOCK", "WARN", "INFO"]
    field: str | None
    document: str | None               # source_file, or None for bundle-level
    message: str                       # human-readable, client-safe
    evidence: str | None               # the offending value
```

**Decimal, not float, for all money.** Arithmetic checks are the demo and they must be exact.

---

## The rules engine

Each rule is a function `(bundle_or_doc) -> list[Flag]`, registered with metadata in `registry.yaml`:

```yaml
- id: FMT-VAT-001
  name: VAT registration number fails check digit
  severity: BLOCK
  scope: document
  message: "The VAT number on {supplier_name}'s invoice ({evidence}) isn't a valid UK VAT number. Please check and resend."
```

Messages must be **client-safe** — they get pasted straight into the chase email, so no internal jargon, no rule IDs in the client-facing text.

### Rule set to implement

#### Format checks (`checks_format.py`)

**FMT-VAT-001 — UK VAT registration number check digit.**
This is the flagship demo rule. Implement fully.

Accepted formats:
- 9 digits (standard)
- 12 digits (9 + 3-digit branch suffix — validate the first 9, ignore the suffix)
- `GD` + 3 digits, range 000–499 (government departments) — format check only
- `HA` + 3 digits, range 500–999 (health authorities) — format check only
- Optional `GB` prefix, optional spaces — normalise before checking

Algorithm for the 9-digit case:
```
digits d1..d9
S = 8*d1 + 7*d2 + 6*d3 + 5*d4 + 4*d5 + 3*d6 + 2*d7
check = d8*10 + d9
valid if (S + check) mod 97 == 0            # "mod 97" (older numbers)
      or (S + check + 55) mod 97 == 0       # "mod 9755" (newer numbers)
```
Both variants must be accepted. Write a table-driven test with at least six known-valid and six known-invalid numbers, including one that fails only the 9755 variant and one that fails only the classic variant.

**FMT-DATE-001** — document date missing or unparseable.
Handle UK-ambiguous formats deliberately: `03/04/2026` must be read as 3 April (DD/MM), and if a date could be either DD/MM or MM/DD *and* the alternative reading is also a valid date, raise `WARN` rather than guessing silently.

**FMT-CUR-001** — currency is not GBP (WARN, not BLOCK — foreign supplier invoices are legitimate).

**FMT-POST-001** — postcode present but malformed. Regex:
```
^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$
```
(uppercase-normalise first)

**FMT-SORT-001** — sort code not 6 digits. **FMT-ACCT-001** — account number not 8 digits.

**FMT-SUPP-001** — supplier name absent or under 2 characters.

**FMT-LEGIB-001** — extraction confidence below threshold OR fewer than 20 characters of text recovered from the page. Message: "This scan is too unclear to read — please resend a clearer photo." Do **not** attempt to guess at low-confidence documents; flagging is the correct behaviour and is a selling point.

#### Arithmetic checks (`checks_arithmetic.py`)

**ARI-VAT-001** — `net_total + vat_total != gross_total` (tolerance: £0.02 for rounding).
**ARI-LINE-001** — sum of line item nets ≠ document net total (same tolerance).
**ARI-RATE-001** — implied VAT rate (`vat/net`) not within 0.5pp of 0%, 5% or 20%. `WARN` — there are legitimate edge cases (margin schemes, mixed rates), so never `BLOCK` on this.
**ARI-NEG-001** — negative gross total on a document typed as an invoice (likely a credit note misclassified).

#### Temporal checks (`checks_temporal.py`)

**TMP-PERIOD-001** — document date falls outside `bundle.declared_period_start..declared_period_end`. This is the highest-value rule in the whole set for the MTD pitch. Message must name both the document date and the declared period.
**TMP-FUTURE-001** — document dated in the future.
**TMP-STALE-001** — document more than 24 months old (WARN — possible wrong-bundle upload).

#### Bundle-level / set checks (`checks_set.py`)

These are what nothing else on the market does. Prioritise them.

**SET-STMT-001 — statement period gap detection.** Sort all `BANK_STATEMENT` docs per `account_identifier` by `period_start`. Flag any gap between one statement's `period_end` and the next's `period_start`, and any gap between the declared period boundaries and the first/last statement. Report as "missing 1 May – 31 May for account ending 4471", not as a count.

**SET-ACCT-001 — expected account coverage.** Any account in `bundle.expected_accounts` with zero documents → BLOCK. This catches the client who forgot an entire account, which is invisible to every capture tool on the market.

**SET-DUP-001 — duplicate detection.** Two documents matching on (`supplier_name` normalised, `document_number`, `gross_total`) → flag as probable duplicate. Also fuzzy variant: same supplier + same gross + dates within 3 days + no document number.

**SET-EMPTY-001** — bundle contains zero documents of a type the client normally submits (needs a `client_profile` table; stub with a simple JSON per client for the MVP).

### Severity semantics

- `BLOCK` — do not release the bundle; goes into the chase message
- `WARN` — release, but surface to the practice for a human look; not in the client message by default
- `INFO` — logged only

---

## Outputs

### 1. Gap report (`/bundle/{id}/report`)

Grouped by document, then bundle-level. Each flag shows rule ID, severity, offending value, and reason. Include a summary line: *"7 of 9 documents passed. 2 blocking issues, 1 warning."*

### 2. Chase message (`/bundle/{id}/chase`)

Generated from BLOCK flags only. Plain text and HTML. Structure:

```
Hi {client_name},

Thanks for sending your records for {period}. Before we can complete them,
we need a few things fixed:

1. The bank statement for May 2026 (account ending 4471) is missing.
2. The invoice from Hartley Supplies dated 3 April 2026 falls outside this
   quarter — could you confirm which period it belongs to?
3. The VAT number on the Ridgeway Ltd invoice doesn't look right — could you
   check and resend?

Once we have these we'll get everything filed.
```

Ordered by severity then by how easy it is for the client to fix. Never more than five items in one message — if there are more, take the top five and say "and a few others we'll follow up on." Long lists get ignored; this is a behavioural design decision, not a technical one.

---

## Fixtures

Create `fixtures/documents/` with at least 12 synthetic files that you generate yourself (do not use real client data):

1. Clean purchase invoice, valid VAT number, arithmetic correct
2. Same but VAT number with a transposed digit → FMT-VAT-001
3. Invoice where net + VAT ≠ gross by £1.20 → ARI-VAT-001
4. Invoice dated 3 April in a Jan–Mar bundle → TMP-PERIOD-001
5. Receipt photographed at an angle, low contrast → FMT-LEGIB-001
6–9. Bank statements for Feb, Mar, May, Jun (April deliberately missing) → SET-STMT-001
10. Duplicate of fixture 1 with a different filename → SET-DUP-001
11. Invoice in EUR → FMT-CUR-001
12. A document that is none of the four types (a delivery note) → UNKNOWN

Generate these as PDFs with `reportlab` in a `fixtures/generate.py` script so they're reproducible. For fixture 5, render then apply rotation + blur + noise with Pillow.

`fixtures/extracted/` holds hand-written JSON for each, so `pytest tests/test_rules_*.py` runs green with no model call at all. `fixtures/labels/` holds the expected flag set per fixture.

---

## Evaluation harness

`eval/run_eval.py` must report, per rule:

- **Precision** — of the flags this rule raised, how many were in the ground truth
- **Recall** — of the ground-truth instances, how many were caught
- **False-positive examples** — printed in full, because these are what a practice will complain about

Also report **extraction field accuracy** separately from rule accuracy (they fail for different reasons and must be debugged separately). Fields to measure: `document_date`, `gross_total`, `supplier_vat_number`, `doc_type`.

Output to `eval/report.md`. Target for the demo: zero false positives on `BLOCK`-severity rules across the fixture set. A false BLOCK sends a client a wrong chase message, which is the one failure mode that loses the account.

---

## UI (minimal, but it is the demo)

Three pages, server-rendered:

1. **Upload** — drag a folder of files, set client name and declared period, optionally list expected accounts.
2. **Bundle view** — table of documents, extracted fields, flag badges. Colour-code BLOCK red / WARN amber / clean green.
3. **Report + chase** — the gap report and the generated chase message side by side, with a copy button.

Do not build a login. Do not build a dashboard. The demo is: drag files in, see red, read the email that fixes it.

---

## Build order

1. Schemas + SQLite + rules engine skeleton + `registry.yaml`
2. All format and arithmetic rules, tested against hand-written JSON fixtures — **no LLM yet**
3. Temporal and set-level rules, tested the same way
4. Fixture generator (`fixtures/generate.py`)
5. Document loader + classifier + LLM extraction adapter with mock backend
6. Real model backend behind the adapter
7. Gap report + chase message generation
8. Minimal UI
9. Eval harness
10. `run.sh` and README

Steps 1–4 must be complete and green before step 5. If the rules engine isn't trustworthy on clean input, no amount of extraction quality saves it.

---

## Acceptance criteria

- [ ] `./run.sh` starts the app with zero configuration and zero API keys (mock backend)
- [ ] `pytest` passes with no network access
- [ ] All 12 fixtures produce exactly their labelled flag sets
- [ ] `eval/run_eval.py` produces a report with per-rule precision and recall
- [ ] The April-statement-gap fixture produces a chase message naming "April 2026" and the account
- [ ] Every flag in the UI can be traced to a rule ID and shows the offending value
- [ ] Money arithmetic uses `Decimal` throughout — no `float` anywhere in the money path
- [ ] Switching `LLM_BACKEND=mock` → `anthropic` requires no code change outside `.env`

---

## Notes for whoever runs this

The temptation will be to make the model do the validation because it's fewer lines of code. Resist it. The reason this product can be sold to an accountant is that you can point at a rule and say "this is why it failed" — and the reason the eval harness means anything is that the rules are deterministic. If a rule needs judgement to evaluate, it is not a rule; escalate it to a human and log it as `WARN`.
