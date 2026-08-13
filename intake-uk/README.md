# Intake Gate (UK) — MVP

A locally runnable prototype that demonstrates the core loop end to end: a bundle
of client documents goes in, and a **gap report** plus a **ready-to-send chase
message** come out — naming exactly what is missing or wrong, with every flag
traceable to a named rule.

> **The model extracts. Deterministic code validates.**
> The LLM's only job is turning a document into typed JSON. Every pass/fail
> decision is made by ordinary Python running a named rule, and every flag
> carries a rule ID, a human-readable reason, and the field it fired on. The
> rules engine runs and is fully tested **with no model and no API key**.

---

## Quick start

```bash
./run.sh
```

This creates a virtualenv, installs dependencies, generates the synthetic
fixture PDFs on first run, and starts the app on <http://127.0.0.1:8000> using
the offline **`mock`** backend — **zero configuration, zero API keys**.

Then, in the browser:

1. Click **Load demo → `BUNDLE-B-STATEMENTS`** to watch a bundle with a missing
   April bank statement produce a chase email naming *"April 2026"* and the
   account.
2. Or **`BUNDLE-A-INVOICES`** for a bundle full of broken invoices (bad VAT
   number, arithmetic that doesn't add up, an out-of-period invoice, an
   illegible scan, a duplicate, a EUR invoice, an unrecognised document).
3. Or upload your own folder of PDFs/images and set the client name and period.

## Running the tests

```bash
source .venv/bin/activate      # after the first ./run.sh
pytest
```

All rule tests run **with no network access** against hand-written JSON
fixtures. The flagship UK VAT check-digit rule (`FMT-VAT-001`) has a
table-driven test with known-valid and known-invalid numbers, including numbers
that pass only the classic "mod 97" variant and only the newer "mod 9755"
variant.

## Evaluation

```bash
python eval/run_eval.py
```

Writes [`eval/report.md`](eval/report.md) with per-rule **precision** and
**recall**, false-positive examples printed in full, and **extraction field
accuracy reported separately** from rule accuracy. Target for the demo — met —
is **zero false positives on `BLOCK`-severity rules**: a false BLOCK sends a
client a wrong chase message, the one failure mode that loses the account.

## Concierge CLI (run a bundle without the web app)

For manual / batch delivery — point it at a folder of a client's documents and
get the gap report and chase message as files:

```bash
python -m app.cli run ./client-docs \
  --client "Bright Cafe Ltd" --from 2026-01-01 --to 2026-03-31 \
  --accounts 12344471,99995555 --out ./out

python -m app.cli demo BUNDLE-B-STATEMENTS      # offline demo, no files needed
```

Exit code is non-zero if anything BLOCKs. This is the tool behind the Phase 0
concierge workflow — see [`docs/phase0/concierge-runbook.md`](docs/phase0/concierge-runbook.md).

## Switching to a real model

No code change is needed outside `.env`:

```bash
cp .env.example .env
# edit .env:
#   LLM_BACKEND=anthropic
#   ANTHROPIC_API_KEY=...
pip install -r requirements-optional.txt
```

The extraction adapter (`app/llm/adapter.py`) picks the backend from
`LLM_BACKEND`; the real SDKs are imported lazily.

---

## How it works

```
upload / demo
      │
      ▼
 ingest.loader ──▶ ingest.classify ──▶ ingest.extract ──▶ llm.adapter (mock | anthropic | openai)
      │                                                            │
      │                                                            ▼
      │                                                   ExtractedDocument (typed JSON)
      ▼                                                            │
   Bundle ───────────────────────────────────────────────────────┘
      │
      ▼
 rules.engine.run_bundle  ──▶  list[Flag]   (every decision is deterministic)
      │
      ├──▶ report.gaps  ──▶ gap report  (grouped by document, then bundle-level)
      └──▶ report.chase ──▶ chase email (BLOCK flags only, max 5 items)
```

### The rules

Rule metadata (severity + client-safe message template) lives in a single source
of truth, [`app/rules/registry.yaml`](app/rules/registry.yaml). Each rule is a
pure function returning `list[Flag]`.

| Group | Rules |
|-------|-------|
| Format | `FMT-VAT-001` (UK VAT check digit), `FMT-DATE-001/002` (missing / ambiguous DD-MM), `FMT-CUR-001`, `FMT-POST-001`, `FMT-SORT-001`, `FMT-ACCT-001`, `FMT-SUPP-001`, `FMT-LEGIB-001` |
| Arithmetic | `ARI-VAT-001` (net + VAT = gross), `ARI-LINE-001`, `ARI-RATE-001`, `ARI-NEG-001` |
| Temporal | `TMP-PERIOD-001` (outside declared period), `TMP-FUTURE-001`, `TMP-STALE-001` |
| Bundle / set | `SET-STMT-001` (statement gap detection), `SET-ACCT-001` (expected-account coverage), `SET-DUP-001` (duplicates), `SET-EMPTY-001` (missing document type) |
| Classification | `CLS-TYPE-001` (unrecognised document) |

**Severity:** `BLOCK` (do not release; goes into the chase), `WARN` (release, but
surface for a human), `INFO` (logged only). Money uses `Decimal` throughout — no
`float` anywhere on the money path.

## Layout

```
intake-uk/
├── app/
│   ├── main.py            FastAPI app + routes
│   ├── models.py          Pydantic schemas (Money is Decimal)
│   ├── db.py              SQLite persistence (data/gate.db)
│   ├── util.py            pure helpers (VAT, postcode, UK date parsing)
│   ├── scenarios.py       load fixtures/scenarios into typed Bundles
│   ├── ingest/            loader · classify · extract
│   ├── llm/               adapter · mock (+ lazy anthropic/openai)
│   ├── rules/             engine + checks_{format,arithmetic,temporal,set} + registry.yaml
│   ├── report/            gaps · chase
│   └── templates/         upload · bundle · report (server-rendered)
├── fixtures/
│   ├── generate.py        reproducible synthetic PDFs
│   ├── documents/         generated PDFs
│   ├── extracted/         hand-written JSON — tests the rules engine alone
│   ├── labels/            ground-truth expected flags per fixture
│   ├── scenarios.json     the two demo bundles
│   └── client_profiles.json
├── eval/run_eval.py       precision/recall per rule → eval/report.md
├── tests/                 test_rules_{format,arithmetic,temporal,set} · test_pipeline
├── requirements.txt       core (offline)
├── requirements-optional.txt   real LLM SDKs
└── run.sh
```

## Non-goals (MVP)

No HMRC/MTD submission, no accounting-system write-back, no auth or
multi-tenancy, no categorisation or tax-treatment advice, no model training.
