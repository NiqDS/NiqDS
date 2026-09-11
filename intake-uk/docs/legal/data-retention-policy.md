# Data Retention Policy — DRAFT

> Draft for solicitor review. Complete every `[bracketed]` item.

## Purpose
Set out how long Intake Gate keeps data and how it is deleted, so we hold personal
data no longer than necessary (UK GDPR principle (e), storage limitation).

## Scope
All data processed by the Service: uploaded client documents, extracted records,
account/enquiry data, and operational logs.

## Retention schedule
| Data | Retention | Notes |
|------|-----------|-------|
| **Uploaded documents** (raw files) | `[INTAKE_RETENTION_DAYS, e.g. 30 days]`, then auto-deleted | Enforced in code by the retention sweep |
| **Extracted records** (structured fields in the database) | `[period — e.g. duration of the engagement + X]` | Needed to show the report/history |
| **Account & login data** | `[duration of account + X months]` | |
| **OAuth tokens** (linked mailboxes) | Until the user disconnects or the account is closed | Least-privilege (draft-creation only) |
| **Operational logs** | `[e.g. 90 days]` | Security / debugging |
| **Backups** | `[rotation, e.g. 30 days]` | Deleted data ages out of backups within this window |

## How deletion works
- Raw uploaded files are removed automatically once older than
  `INTAKE_RETENTION_DAYS` (0 disables auto-deletion). Set this to a real value in
  production.
- A customer or their client may request **earlier deletion**; we action verified
  requests within `[e.g. 30 days]`. For documents processed on a practice's behalf,
  the practice (controller) directs deletion.
- On account closure / end of the engagement, data is deleted or returned per the
  DPA.

## Responsibilities
`[Named owner]` reviews this policy `[annually]` and confirms the configured
retention matches this schedule.
