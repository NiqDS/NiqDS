# Sample run — four supplier invoice images

Four invoice images were run through the deterministic rules engine.

**Important — how these were extracted.** The automated vision/OCR extraction
path is not built yet (the deferred "vision extraction" gap in the roadmap: the
pipeline reads *text-layer PDFs*, not photos). So the typed fields for these
four images were **transcribed by hand from the images** — that hand
transcription stands in for the model's extraction step. Every pass/fail
decision below is still made by the deterministic engine (`app/rules/…`, run
via `app/single.py`), which is the part being demonstrated. Reproduce with:

```
PYTHONPATH=. ./.venv/bin/python eval/sample_invoices.py
```

## Result summary

| # | Invoice | Verdict | Deterministic flags |
|---|---------|---------|---------------------|
| 1 | Plumbing Co. #42228 (US) | FIX | `FMT-DATE-001` BLOCK (date blank), `FMT-CUR-001` WARN (USD, not GBP); net not shown |
| 2 | Ellington Wood Decor #042022 (UK) | FIX | no rule flags; net not itemised (no VAT on the invoice) |
| 3 | RealHandy #100-13 (UK) | FIX | `FMT-VAT-001` BLOCK — VAT number `GB123456789` fails the UK check digit |
| 4 | ABC Seller #012345 (UK) | READY | `ARI-RATE-001` WARN — blended VAT rate 1.8% (mixed export/exempt lines); VAT number `GB999 9999 73` is valid |

Notes:
- **#3 is the flagship demo:** `GB123456789` is a plausible-looking placeholder
  that a capture tool would accept; the check-digit rule rejects it
  deterministically and produces a client-safe chase line.
- **#4 shows the engine not over-blocking:** the odd 1.8% blended rate on a
  mixed export/exempt invoice is a WARN for a human to glance at, never a BLOCK —
  exactly the margin/mixed-rate case the rules spec calls out.
- **#1 and #2** are `FIX` mainly because a required field (date / net) isn't
  present on the document; that's the completeness check, not a false alarm.

## Full engine output

```
══════════════════════════════════════════════════════════════════════════════
FILE:    5b66e880 · Plumbing Co #42228.png
TYPE:    Purchase invoice   (extraction confidence 0.92)
VERDICT: FIX  —  A few things to fix

  [✓] Supplier       Plumbing Co.       OK
  [·] VAT number     —                  OPTIONAL
        └ Not present (that's usually fine).
  [✓] Invoice number 42228              OK
  [✗] Date           —                  MISSING
        └ We couldn't read a valid date on the document from Plumbing Co.. Please confirm the date and resend.
  [✗] Net            —                  MISSING
        └ We couldn't find the net on this document.
  [·] VAT            —                  OPTIONAL
        └ Not present (that's usually fine).
  [✓] Total          $135               OK

  What the client would be asked to fix:
    • We couldn't read a valid date on the document from Plumbing Co.. Please confirm the date and resend.
    • We couldn't find the net on this document.

  Rule audit trail:
    BLOCK FMT-DATE-001   field=document_date        evidence=None
    WARN  FMT-CUR-001    field=currency             evidence='USD'
══════════════════════════════════════════════════════════════════════════════
FILE:    6168f4e5 · Ellington Wood Decor #042022.png
TYPE:    Purchase invoice   (extraction confidence 0.97)
VERDICT: FIX  —  A few things to fix

  [✓] Supplier       Ellington Wood Decor OK
  [·] VAT number     —                  OPTIONAL
        └ Not present (that's usually fine).
  [✓] Invoice number 042022             OK
  [✓] Date           30 Apr 2022        OK
  [✗] Net            —                  MISSING
        └ We couldn't find the net on this document.
  [·] VAT            —                  OPTIONAL
        └ Not present (that's usually fine).
  [✓] Total          £600               OK

  What the client would be asked to fix:
    • We couldn't find the net on this document.

  Rule audit trail:
══════════════════════════════════════════════════════════════════════════════
FILE:    97097d5e · RealHandy #100-13.png
TYPE:    Purchase invoice   (extraction confidence 0.96)
VERDICT: FIX  —  A few things to fix

  [✓] Supplier       RealHandy          OK
  [✗] VAT number     GB123456789        INVALID
        └ The VAT number on RealHandy's invoice (GB123456789) isn't a valid UK VAT number. Please check and resend.
  [✓] Invoice number 100-13             OK
  [✓] Date           24 Aug 2021        OK
  [✓] Net            £620               OK
  [✓] VAT            £124               OK
  [✓] Total          £744               OK

  What the client would be asked to fix:
    • The VAT number on RealHandy's invoice (GB123456789) isn't a valid UK VAT number. Please check and resend.

  Rule audit trail:
    BLOCK FMT-VAT-001    field=supplier_vat_number  evidence='GB123456789'
══════════════════════════════════════════════════════════════════════════════
FILE:    12efb195 · ABC Seller #012345.png
TYPE:    Sales invoice   (extraction confidence 0.95)
VERDICT: READY  —  Looks complete

  [✓] Supplier       ABC Seller         OK
  [✓] VAT number     GB999 9999 73      OK
  [✓] Invoice number 012345             OK
  [✓] Date           27 May 2020        OK
  [✓] Net            £3300              OK
  [!] VAT            £60                WARN
        └ The VAT rate on ABC Seller's invoice works out at 1.8%, which isn't a standard UK rate. Please confirm.
  [✓] Total          £3360              OK

  Rule audit trail:
    WARN  ARI-RATE-001   field=vat_total            evidence='1.8%'
══════════════════════════════════════════════════════════════════════════════
BUNDLE-LEVEL flags (all four together):
  (none)
```
