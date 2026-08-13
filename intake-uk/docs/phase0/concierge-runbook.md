# Concierge intake runbook (Phase 0)

How to run a real design partner's client bundles **by hand**, before the
self-serve platform exists. The engine already works; this is the repeatable
process wrapped around it. Target: **≤ 10 minutes per client bundle**, and a
chase email the partner can send with one edit.

> Phase 0 goal isn't scale — it's proof, quotes, and a rule library hardened
> against real messy bundles. Every run should teach you something; capture it
> (see step 6).

---

## Before you start (once per design partner)

1. Get a signed **one-page concierge agreement** (see the pitch kit) covering: no
   HMRC submission, they remain the data controller, retention terms, and the
   case-study permission.
2. Agree a **secure transfer** method for documents (their client portal export,
   a shared drive folder, or encrypted email). Never real client data over plain
   email if avoidable.
3. Create a working folder per partner, ignored by git:
   ```
   ~/intake-runs/<partner>/<client>/<period>/
   ```
4. Note the client's **declared period**, **expected bank accounts**, and the
   **document types they normally send** (feeds SET-EMPTY-001 later).

---

## Per-bundle steps

### 1. Collect
Drop every document for one client + one period into the client folder. PDFs,
photos, scans — whatever they actually send. Don't tidy it; messy input is the
point.

### 2. Run the gate
From the repo, with the venv active:

```bash
python -m app.cli run ~/intake-runs/<partner>/<client>/<period> \
  --client "Client Ltd" \
  --from 2026-01-01 --to 2026-03-31 \
  --accounts 12345678,87654321 \
  --out ~/intake-runs/<partner>/<client>/<period>/out
```

- Default backend is `mock` (offline). For real extraction on real documents use
  `--backend anthropic` with `ANTHROPIC_API_KEY` set and the SDK installed
  (`pip install -r requirements-optional.txt`).
- Exit code is non-zero if anything **BLOCKs** — handy if you script batches.

You get, in `out/<bundle-id>/`:
- `gap-report.md` — every flag, grouped by document then bundle-level
- `chase.txt` and `chase.html` — the client-ready chase message

### 3. Human review (the part that matters in Phase 0)
Read the gap report against the actual documents. For each flag ask:
- **True positive?** Good — leave it.
- **False positive?** This is gold. Note the document and why the rule misfired.
  A false BLOCK is a P0 (it would send a wrong chase). Log it (step 6) and, if
  it's clear, open a rules fix.
- **Missed something?** A real problem the gate didn't catch → a candidate new
  rule or module (see `docs/roadmap/adjacent-modules.md`).

Never send a chase you haven't eyeballed. In Phase 0 you are the safety net that
lets you promise "zero false BLOCKs" later.

### 4. Hand over
Send the partner:
- the **chase message** (they paste it to their client, tweaking tone), and
- a one-line summary: *"7 of 9 clean, 2 blocking — chase drafted."*

Keep it to the chase + summary. The full gap report is for them on request, not
every time.

### 5. Log the outcome
Append one row to the partner's tracking sheet
(`~/intake-runs/<partner>/log.csv`), columns:

```
date, client, period, docs, blocks, warns, false_positives, minutes, notes
```

This is your evidence base: throughput, accuracy, and the raw material for a
case study ("cut chase time from ~40 min to ~8 min per bundle").

### 6. Feed the loop
- **False positives / misses** → issues against the rules engine, most-severe first.
- **New pains the partner mentions** → the discovery log (`docs/phase0/discovery-questionnaire.md`)
  and the module backlog.
- **A good quote or a hard number** → the case-study/reviews placeholders on the
  marketing site (`website/`), with permission.

---

## Batch tip

To run a whole partner's folder of clients in one go, loop over subfolders:

```bash
for c in ~/intake-runs/<partner>/*/; do
  python -m app.cli run "$c" --client "$(basename "$c")" \
    --from 2026-01-01 --to 2026-03-31 --out "$c/out" || echo "BLOCKS in $c"
done
```

## What "done" looks like for Phase 0

- 3–5 partners, ≥ 20 real bundles run.
- A measured before/after time saving and accuracy number per partner.
- **Zero unresolved false BLOCKs** across the set.
- 2–3 usable case studies / quotes with permission.
- A prioritised backlog of rules + adjacent modules that came from real bundles.
