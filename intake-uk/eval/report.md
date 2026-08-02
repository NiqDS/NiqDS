# Intake Gate — evaluation report

_Generated with fixed date 2026-08-02 on the fixture set._

## Rule accuracy

| Rule | TP | FP | FN | Precision | Recall |
|------|----|----|----|-----------|--------|
| ARI-VAT-001 | 1 | 0 | 0 | 1.00 | 1.00 |
| CLS-TYPE-001 | 1 | 0 | 0 | 1.00 | 1.00 |
| FMT-CUR-001 | 1 | 0 | 0 | 1.00 | 1.00 |
| FMT-LEGIB-001 | 1 | 0 | 0 | 1.00 | 1.00 |
| FMT-VAT-001 | 1 | 0 | 0 | 1.00 | 1.00 |
| SET-ACCT-001 | 1 | 0 | 0 | 1.00 | 1.00 |
| SET-DUP-001 | 1 | 0 | 0 | 1.00 | 1.00 |
| SET-STMT-001 | 1 | 0 | 0 | 1.00 | 1.00 |
| TMP-PERIOD-001 | 1 | 0 | 0 | 1.00 | 1.00 |

**False positives on BLOCK-severity rules: 0** (target for the demo: 0).

## False-positive examples

_None — no rule raised a flag that wasn't in the ground truth._

## Extraction field accuracy

_Measured separately from rule accuracy — extraction and rules fail for different reasons._

| Field | Correct | Total | Accuracy |
|-------|---------|-------|----------|
| document_date | 12 | 12 | 1.00 |
| gross_total | 12 | 12 | 1.00 |
| supplier_vat_number | 12 | 12 | 1.00 |
| doc_type | 12 | 12 | 1.00 |
