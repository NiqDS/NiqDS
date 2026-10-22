# AB-Testing Batch Allocation Skill

Two products on one shared foundation, launched from `web/hub.html`:

1. **AB-test pilot allocation** (the original brief) — turns a submitted
   list of client INNs into balanced Control (КГ) / Target (ЦГ) groups,
   computes the financial-effect metrics the pilot is measured on, and
   keeps recalculating them on a schedule for a Navigator dashboard.
   Implements the 7-step agent process from the source spec
   (`docs/original_spec_ru.md` — extracted verbatim from the attached
   `.docx`).
2. **Metrics calculation** — upload a list of IDs, pick metrics and
   filters, get one Excel back. No split, no pilot, read-only. See
   "Product 2" below.

Both share the same `metric_scripts/` bank, `manifest.json`,
`subscriptions.json`, `filters.json`, exporter and CLI — so a fix to a
real table query benefits both.

Deliverable shape for product 1, per the original brief:

- **Requester** gets two files: `control_group` and `target_group` (INN
  column renamed to `codes`, per spec step 4).
- **Analytics team** gets the same two files **plus** a plain-text
  description of the pilot (term, recalculation cadence, requester,
  grouping metrics used, financial-effect articles measured, expected
  effect %, balance-check result) — see `_format_pilot_package` in
  `skill/pipeline.py`.
- **The analyst of record** (`analyst_email` on the request) additionally
  gets the *raw* submission — the uploaded `inn_list.csv` exactly as sent,
  plus a `request.json` copy of the pilot parameters — sent immediately
  after step 1 validation, before any blocking/filtering, and not sent to
  anyone else.
- A local pilot folder (`data/pilots/<slug>/`) is created for monitoring,
  matching spec step 4's "локально создается папка с названием и сроком
  пилота".

## Why an HTML request-builder, not a hosted web app

A real backend would need to run *inside* Sber's secured network with
access to the actual client-attribute tables, mail relay, and Navigator —
none of which this environment can reach or verify. `web/index.html` is a
single, dependency-free static file: it runs entirely in the browser,
collects the same fields a backend form would, and downloads a
`request.json` + `inn_list.csv` bundle instead of POSTing anywhere. Nothing
about the pilot data leaves the browser at this stage — the user hands the
two files to the agent (CLI, or a GigaCode chat message) themselves. This
sidesteps having to stand up and secure a server just to collect five form
fields, while still giving non-technical requesters a form instead of a
JSON file to hand-edit. If GigaCode later exposes real hosted-tool /
webhook support, the same `PilotRequest.from_dict()` contract can be
wired to an HTTP endpoint with no change to `skill/pipeline.py`.

## Quickstart

```bash
# from the root of the skill (the folder containing skill/, web/ and metric_scripts/)
pip install -r requirements.txt   # optional: only needed for .xlsx output, else falls back to .csv

# 1. open web/hub.html in a browser -- one button per product.
#    Two are built ("АБ-Тест параметры пилота" and "Расчёт метрик по списку ID");
#    the other two are placeholders (see "Branching into more products" below).

# --- product 1: AB-test pilot (split a client list into CG/TG) -------------
# fill web/index.html, submit -> downloads request.json + inn_list.csv
python -m skill.cli run --request request.json --inn-file inn_list.csv

# later, on whatever cadence the pilot's recalculation_frequency implies
# (currently locked to monthly -- see "Assumptions" below)
python -m skill.cli recalc --pilot-folder "data/pilots/<pilot_slug>"

# --- product 2: metrics calculation (IDs in, one Excel of metrics out) -----
# fill web/metrics_calc.html, submit -> downloads calc_request.json
python -m skill.cli calc --request calc_request.json --id-file ids.xlsx

# what can be calculated, and what can be filtered on
python -m skill.cli metrics
python -m skill.cli filters --metric chod
```

Run the test suite:

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

## Architecture

```
web/hub.html ──▶ web/index.html ──(request.json + inn_list.csv)──▶ skill/cli.py
                                                          │
                                                          ▼
                                                  skill/pipeline.py
                                                  run_intake()
        step 1  inn_utils.validate_file()      ── format + FNS checksum
        step 1a registries.InnStatusRegistry   ── NEW: raw inn_list + request.json
                connectors/email_connector.py       to analyst_email only, pre-filtering
        step 2a registries.check_master_status()── NEW: gate vs master Used/Unused/
                                                     Used_as_cg status table
        step 2  registries.check_and_register()── dedupe vs "involved INNs"
        step 3  registries.MetricRequestsRegistry ── new-metric backlog
        step 4  metrics/runner.py + splitter.py ── stratified split + balance check
                exporter.write_group_file()     ── control_group / target_group
                registries.InnStatusRegistry.upsert_many() ── NEW: mark cg/tg in
                                                     the master status table
        step 5  exporter.write_financial_effect_file() ── + stat_significance column
                connectors/email_connector.py   ── requester / dev / analytics mail
                connectors/dashboard_connector.py ── Navigator upload
                                                          │
                                                          ▼
                                              data/pilots/<slug>/pilot_meta.json
                                                          │
                                          (scheduler fires on recalculation_frequency)
                                                          ▼
                                                skill/monitoring.py
                                          step 6  run_recalculation()
                                          step 7  (dashboard link is already
                                                   returned by the connector;
                                                   forwarding it to the
                                                   requester is a one-line
                                                   email call left to the
                                                   caller/GigaCode wrapper)
```

Steps labeled "NEW" aren't in the original spec — see "Assumptions & open
questions" below for why each was added and how it was resolved.

### Directory layout

```
skill/                  core package (no I/O side effects outside what's listed below)
  config.py             every path/threshold a deployment needs to change lives here
  models.py              PilotRequest, SplitResult, CalculationRequest, ...
  inn_utils.py           step 1: .xlsx/.csv reading + INN checksum validation
  registries.py           the 3 prerequisite CSV tables from the spec + step 2 logic,
                           plus the NEW InnStatusRegistry (master Used/Unused/Used_as_cg)
  metrics/runner.py       dispatches metric codes to metric_scripts/*
  splitter.py             step 4: stratified split + financial balance check
  exporter.py             xlsx/csv writers (falls back to csv without openpyxl)
  connectors/              pluggable email + Navigator upload (mock by default)
  pipeline.py              product 1: orchestrates steps 1-5 (run_intake)
  monitoring.py            product 1: step 6 (run_recalculation) + step 7 helper (is_due)
  calc_pipeline.py         product 2: run_calculation (IDs + metrics + filters -> Excel)
  cli.py                   `python -m skill.cli run|recalc|calc|metrics|filters`
metric_scripts/           demo "bank of PySpark scripts", one file per metric,
                           shared by both products
  manifest.json            catalog: code, label, value_type, usable_as, script
  subscriptions.json       alias -> real table name/description (edit this, not the scripts)
  subscriptions.py         get_subscription(alias) loader, used from a metric script's run()
  filters.json             filter registry: label, type, values, applies_to (edit this)
  filters.py               loader + up-front validation of a filter selection
sample_data/               demo reference data + empty prerequisite tables
web/
  hub.html                 landing page: one button per product
  _template.html           source template for index.html (edit this, not index.html)
  _calc_template.html      source template for metrics_calc.html
  build_form.py            regenerates BOTH generated forms from manifest.json + filters.json
  index.html               generated intake form for "АБ-Тест параметры пилота"
  metrics_calc.html        generated form for "Расчёт метрик по списку ID"
  km_test.html              placeholder for "Тест-параметры КМ" (not built yet)
  target_group_picker.html  placeholder for "Подбор Целевой группы для пилота" (not built yet)
tests/                     pytest suite, all I/O redirected into tmp_path
docs/original_spec_ru.md   the original spec, verbatim, for traceability
data/pilots/               product 1 runtime output — one folder per pilot (gitignored)
data/calculations/         product 2 runtime output — one folder per calculation (gitignored)
```

## Wiring into GigaCode

No GigaCode skill/plugin manifest spec was available in this environment,
so the package makes no assumptions about it. Two integration paths, pick
whichever GigaCode actually supports:

1. **Shell out to the CLI** (works regardless of GigaCode's plugin format):
   register a GigaCode tool/action that runs
   `python -m skill.cli run --request <path> --inn-file <path>` (or
   `recalc`/`metrics`) and parses the JSON on stdout. This is the safest
   integration point since it doesn't depend on GigaCode's Python API
   surface at all.
2. **Function-calling**: if GigaCode (like the underlying GigaChat API)
   supports OpenAI-style tool/function schemas, expose
   `skill.pipeline.run_intake(request: PilotRequest, inn_file: Path) -> PilotResult`
   and `skill.monitoring.run_recalculation(pilot_folder: Path) -> Path` as
   the two callables. Both take/return plain dataclasses — trivial to wrap
   in whatever tool-schema format GigaCode expects once you have its docs.

`web/index.html`'s "Скопировать сообщение для GigaCode" button produces a
ready-to-paste chat instruction (with the two files attached) for a purely
conversational GigaCode setup, no tool registration required at all.

## Pluggable integrations (mocked by default)

None of these reach a real Sber system in this environment — each is a
`Protocol` with one default no-op-safe implementation and one documented
stub for the real thing:

| Integration | Default (safe, local) | Production |
|---|---|---|
| "Involved INNs" / duplicates / overlap tables | CSV files under `sample_data/` | Swap `skill/registries.py`'s `_CsvRegistry` for a DB-backed class with the same `load`/`append` methods |
| Master INN status table (Used/Unused/Used_as_cg) | `sample_data/inn_master_status.csv` via `InnStatusRegistry` | Swap for a DB-backed class with the same `status_of`/`upsert_many` methods |
| Per-INN attributes (OKVED/OPF/TB/tenure/ЧОД/ЧЭП/...) | `metric_scripts/*.py` read `sample_data/attributes_reference.csv` | Point `MetricScriptConfig.scripts_dir` at the real PySpark script bank (same `run(inn_list, as_of_date, spark)` signature) and set `AB_SKILL_USE_SPARK=true`; look up real table names via `metric_scripts.subscriptions.get_subscription(alias)` instead of hardcoding them in each script |
| Email | `LoggingEmailConnector` writes `.eml.txt` files to `data/pilots/_outbox/` | `SmtpEmailConnector` in `skill/connectors/email_connector.py` (fill in host/port/sender) |
| Navigator dashboard upload | `LocalDropzoneDashboardConnector` copies the workbook to `data/navigator_dropzone/` | `HttpNavigatorConnector` stub — raises `NotImplementedError` until Navigator's real upload API is known |

### Data-source subscriptions (`metric_scripts/subscriptions.json`)

Keeps real internal table names out of individual metric scripts. Add an
entry (alias -> `{"table": "...", "description": "..."}`), save the file,
then reference it from a script instead of hardcoding the table name:

```python
from metric_scripts.subscriptions import get_subscription
table = get_subscription("chod_source")
df = spark.table(table)...
```

Renaming/repointing an alias in `subscriptions.json` then never requires
touching the scripts that use it. The bundled file ships with placeholder
`example_db.*` table names — replace them with real ones in your internal
copy; don't commit real internal table names to a public repo.

## Assumptions & open questions

The source spec explicitly flags two points as "уточнить" (to be
clarified). Both were resolved with an assumption so the pipeline is
runnable end-to-end; **both should be confirmed with the business before
production use**:

1. **Does prior Control-group membership ever block reuse?** Spec: *"при
   участии ИННок в качестве КГ, они должны быть доступны в качестве КГ для
   других пилотов – только при потенциальном попадании в список ЦГ может
   повлиять на чистоту расчетов уже идущего пилота (уточнить)"*.
   Implemented as: **no** — a client already used as CG anywhere is always
   reusable in a new pilot (any role); a client currently active as TG
   blocks reuse only while its pilot's `valid_to` hasn't passed, and only
   for the metrics the overlap-suggestion engine flags. See
   `skill/config.py:OverlapConfig` (`blocking_roles`,
   `require_metric_overlap`) — flip these if the real rule should also
   block, e.g., CG reuse, or block regardless of metric overlap.
   Tested in `tests/test_registries.py`.

2. **Recalculation Excel: overwrite or append?** Spec: *"перезаписывает
   Excel файл с новыми данными (формат полной перезаписи или дописывания
   новых строк - уточнить)"*. Implemented as: **append** by default (each
   `run_recalculation()` call adds a new `report_date` block, producing a
   genuine time series for the Navigator dashboard) — this is what "успешность
   пилота в течении его проведения" (step overview) implies is being
   charted. Overwrite mode is available via `AB_SKILL_RECALC_MODE=overwrite`
   / `PilotStorageConfig.recalc_mode` for teams that want Navigator to only
   ever see the latest snapshot. The exporter refuses to append if the set
   of financial-effect articles changed between recalculations (would
   silently corrupt the dashboard's column mapping) — raises `ValueError`
   instead.

Additional decisions made where the spec was silent, from the earlier
clarification round:

- **Attribute source**: `metric_scripts/` models the "bank of PySpark
  scripts" as one importable module per metric with a fixed
  `run(inn_list, as_of_date, spark=None)` signature. The same script is
  used both when the requester picks that metric as a grouping/split
  attribute (step 3) and later as a financial-effect article during
  monitoring (step 5/6) — matching the confirmed intent that a single
  script bank serves both purposes.
- **CG/TG split method**: stratified random assignment within each
  combination of the grouping metrics the strata budget can afford, then
  rerandomisation — up to `max_reshuffle_attempts` draws, each scored by a
  Mahalanobis distance between the group means over money levels, trends
  and dummy-coded attribute levels, keeping the best. A covariate is
  reported as unbalanced when it exceeds `max_standardized_diff` (0.1) or
  its own achievable floor, whichever is larger.
- **INN validation**: the spec only requires "digits only". Added the
  official FNS control-digit checksum (10-digit legal entities, 12-digit
  individuals) as an extra layer — toggle off via `strict_inn_checksum=False`
  in `run_intake()` if the business only wants the literal spec check.
- **A fully malformed submission blocks the whole file by default**, not
  just the bad rows (`IntakeRejected`), matching "агент пишет заказчику с
  просьбой переделать входной файл в нужном формате" read literally. For
  cases where you'd rather drop the bad rows and split the rest instead of
  failing the whole run, `python -m skill.cli run` takes an opt-in
  `--drop-invalid-inns` flag: it runs step-1 validation up front, writes
  the surviving INNs to `<inn-file stem>_cleaned.csv`, prints what got
  dropped and why, and runs the split on what's left (see
  `skill/cli.py:_drop_invalid_inns`). `run_intake()` itself is unchanged —
  this is a CLI-level convenience, not a change to the library's default
  behavior.
- **`metric_requests` backlog table** (step 3's "нужной проверки нет ...
  высылается команде разработки") isn't one of the spec's 3 prerequisite
  tables; added as a 4th CSV so requests are queryable instead of a
  one-off email that's easy to lose.

Decisions from the most recent round of additions:

- **Master INN status table (`InnStatusRegistry`) is additive, not a
  replacement** for `InvolvedInnsRegistry`. They answer different
  questions: the master table is a fast single-flag check ("can this INN
  be used right now" — Used / Unused / Used_as_cg), checked as its own
  step (2a) before the existing overlap check (step 2); `InvolvedInnsRegistry`
  remains the historical, date-ranged log that feeds the overlap-suggestion
  engine and audit trail. Both are updated after every split. If your
  actual master-status table already replaces the need for date-ranged
  tracking, step 2's `check_and_register` can be removed later without
  touching step 2a.
- **`Used_as_cg` does not block reuse**, only `Used` does
  (`MasterStatusConfig.blocking_statuses`) — kept consistent with the
  existing CG-is-always-reusable assumption in `OverlapConfig` above.
  Change `blocking_statuses` if Used_as_cg should block too.
- **The analyst-only raw copy (step 1a) fires before any filtering**, on
  the request exactly as submitted — not the post-split control/target
  groups (those still go to the requester/dev/analytics team separately
  in step 4/5, per the original spec). If the analyst should instead get
  the *final* groups instead of (or in addition to) the raw submission,
  that's a one-line change to who step 4/5's emails are addressed to.
- **`recalculation_frequency` is locked to `"month"` only in the HTML
  form** (`web/_template.html`'s select is disabled with a single option).
  This is a UI-level restriction only — `skill/models.py`,
  `skill/pipeline.py`, and `skill/monitoring.py` still accept/handle
  `"day"`/`"week"` unchanged if a request.json is hand-written or built by
  another caller. Add a check in `PilotRequest.from_dict` or
  `run_intake` if `"month"` needs to be enforced server-side too.
- **`stat_significance` is a placeholder column only** — added to every
  row of `financial_effect.xlsx/csv` (`exporter.write_financial_effect_file`)
  from the very first write, always `None`/NULL for now. No significance
  test is implemented yet; wire the actual computation into that function
  once there's enough report_date history per pilot to run one (a paired
  test comparing CG vs TG means per financial-effect article is the
  obvious starting point).

## Product 2: metrics calculation (`web/metrics_calc.html`)

Upload a list of IDs (`.xlsx` or `.csv`), tick the metrics you want, tick
any filters, get one Excel back. Deliberately **read-only**: no CG/TG
split, no pilot folder, and it never writes to the involved-INN or
master-status registries — running a calculation must not change which
clients are available for a future pilot (there's a test asserting this).

```
web/metrics_calc.html ──(calc_request.json + ids.xlsx)──▶ skill/cli.py calc
                                                              │
                                                              ▼
                                                    skill/calc_pipeline.py
                                                    run_calculation()
   1  inn_utils.validate_file()   ── .xlsx/.csv, format + FNS checksum
   2  metrics/runner.run_many()   ── same script bank, filters passed through
   3  exporter.write_metrics_result() ── row per ID, column per metric
      connectors/email_connector.py    ── result + coverage summary
```

The output keeps **one row per submitted ID**, blank where a metric
returned nothing, and the run reports **coverage** per metric (how many
IDs actually got a value). That exists because "ran fine, every column
blank" is otherwise a silent failure — wrong filters, or IDs simply
absent from the source table, look identical to success without it.

### Filters (`metric_scripts/filters.json`)

Same pattern as `subscriptions.json`: declare a filter in the JSON file
and it appears in the web form, in `skill.cli filters`, and gets passed
to the scripts — no pipeline change needed.

```json
"sub_segment": {
  "label": "Подсегмент (segmca)",
  "type": "categorical",
  "values": ["Микро", "Малые", "Средние"],
  "applies_to": ["chod", "chep", "turnover", "revenue", "sdo"]
}
```

`applies_to` (`["*"]` for all) means each script only receives the
filters declared for it — a sub-segment filter that's meaningless for
OKVED simply isn't passed to `okved.py`. The file ships seeded with the
values currently **hardcoded inside the production scripts**
(`segment_kratko`, `segmca`, `period_type`, `is_active`, reporting year),
because those are exactly the ones worth lifting out into user-selectable
filters first.

A filter is only *declared* in JSON; how it narrows a query lives in the
metric script, since only the script knows which column of which table it
maps to. The bundled demo scripts are a working reference implementation
(see `metric_scripts/_common.py:FILTER_COLUMNS`).

### The extended script contract

Metric scripts are now:

```python
def run(inn_list, as_of_date, spark=None, filters=None) -> dict[str, Any]:
```

Both products share one bank, so this signature applies to both. It's
backwards compatible: scripts predating `filters` are still called with
the old three-argument form. What is **not** allowed is silently dropping
a requested filter — `MetricRunner.run` raises a `TypeError` naming the
script instead, because unfiltered numbers that look perfectly valid are
a worse outcome than a failed run.

## Branching into more products

`web/hub.html` is the entry point: one button per product.

1. **АБ-Тест параметры пилота** — fully built (`web/index.html`).
2. **Расчёт метрик по списку ID** — fully built (`web/metrics_calc.html`),
   see the section above.
3. **Тест-параметры КМ** — "Исследования эффективности работы клиентских
   менеджеров, относительно заявленного плана." Placeholder page only
   (`web/km_test.html`); no backend yet. When this gets built out, it'll
   likely want its own `skill`-style package (own metrics, own splitter or
   no split at all, own pipeline) rather than being bolted onto this one —
   client-manager performance-vs-plan is a different unit of analysis
   (КМ, not client INN) from everything else here.
4. **Подбор Целевой группы для пилота** — "Заполните требования для выбора
   целевой группы для проведения пилота из метрик на выбор и мы поможем
   вам ее подобрать." Placeholder page only (`web/target_group_picker.html`).
   Unlike the AB-test flow (which takes an already-chosen INN list and
   splits it), this one picks a target group *from scratch* by metric
   criteria. Now that product 2 exists it's much closer to that than to
   `skill/splitter.py` — it's essentially the metrics calculation run
   *backwards*: instead of "these IDs, what are their metrics", it's
   "these metric criteria, which IDs match". The filters mechanism is
   most of the groundwork.

The two remaining placeholders are static pages with no form yet — just
enough for the hub's links to not 404. Come back to this section once
either product's requirements are scoped.

## Over-stratification on small candidate lists

Stratifying on 4 categorical dimensions (OKVED × OPF × TB × tenure bucket)
needs enough candidates per combination to split. On the bundled 50-client
sample those four attributes produce 47 strata, 44 of them holding a single
client — and **a stratum of one cannot be split**.

This used to be far worse than "a skewed ratio". `n_target = round(1 * 0.5)`
is 0 in Python (halves round to even), so every single-client stratum sent
its client to control, deterministically: КГ=47 / ЦГ=3, reported as
`balanced: PASSED` whenever a single financial article happened to clear the
SMD check. Reshuffling could not help either — shuffling a one-element list
is a no-op, so all 25 attempts returned the identical split. Picking a money
metric as a grouping attribute (the form offers `chod`, `revenue`,
`turnover`, `sdo`) made every rouble value its own stratum and emptied the
target group entirely.

Fixed in `skill/splitter.py`: the remainder of each stratum's exact share
carries into the next (largest-remainder allocation) so a run of singletons
alternates ЦГ/КГ, the stratum order is shuffled so the seed matters again, an
empty group raises `DegenerateSplitError` instead of being returned, and
`strata_warnings()` forces `balanced = False` with an explanation when more
than half the list sits in singleton strata or the realised ЦГ share is more
than `max_ratio_deviation` (5pp) from the requested one. The warning reaches
the delivery email, the analytics package and `--output text`. See
`tests/test_stratification.py` — 14 tests, including the 50-client
reproduction.

**It is still worth selecting coarse attributes.** A balanced split needs
several clients per stratum; the guard tells you when you have not got them,
it cannot manufacture them. `docs/chod_matching_review_ru.md` section 5 (P2)
describes the proper fix — bucketing OKVED to its 21 ОКВЭД2 sections and
money metrics to trajectory cohorts before they are ever used as a stratum
key — which is how the ЧОД matching notebook avoids the problem entirely.

## External audit: what changed (wave 1)

An external audit of the MVP raised 16 defects (Д1–Д16). Every one that
was still reproducible on the code at the time has been fixed; each has a
named regression test in `tests/test_audit_regressions.py` that replays the
auditor's own scenario, so reintroducing the defect fails a test carrying
its ID.

| ID | Defect | Fix |
|----|--------|-----|
| Д1 | A negative control mean made *every* split report "balanced" — `abs()` sat in the numerator only, so the ratio went negative and passed `<= threshold`. Routine for ЧОД/ЧЭП on loss-making clients. | Balance is now the **standardized mean difference** (`\|mean_T − mean_C\| / pooled SD`), which cannot be negative and is scale-free. Threshold `SplitConfig.max_standardized_diff = 0.10`, the conventional cutoff. |
| Д2 | A scheduler firing more often than a pilot's cadence appended a duplicate block of rows each time (auditor: 50 rows → 200, all one `report_date`), which Navigator charts as a 4× effect. | `run_recalculation()` now calls `is_due()` itself and refuses a `report_date` it already holds (`RecalculationNotDueError` / `AlreadyCalculatedError`). `--force` overrides. |
| Д3 | Re-running an existing pilot name silently overwrote the pilot folder. | `PilotAlreadyExistsError`, `--force` to override. |
| Д4 | A request with no metrics selected produced a pilot that could not be analysed. | `skill/validation.py` runs as step 0 of `run_intake` — dates, emails, frequency, ≥1 grouping metric **and** ≥1 financial article, metric codes present in the manifest, positive expected effect. Raised **before** any file or registry write. |
| Д6 | `finalize_role` reopened the registry twice per INN; on NFS a 50-INN pilot looked frozen. | `append_many()` / `finalize_roles()` — one open per batch. 4.39s → 0.032s in the reproduction. |
| Д7/Д8 | Failures surfaced as tracebacks the calling agent could not act on. | The CLI reports every error as structured JSON with a `status` field and a non-zero exit code. |
| Д9 | A pilot scheduled to *start* next year blocked candidates today: the overlap check only compared `valid_to`. | Overlap now requires both ends to intersect. |
| Д10 | The web form read the uploaded CSV as UTF-8 and re-downloaded the decoded string, so every cp1251 export (what Russian Excel produces) came back with `ИНН` as replacement characters and the column could not be found. | The form keeps the uploaded **bytes** and hands them over untouched; decoding happens only for the on-screen preview, UTF-8 first with a cp1251 fallback. `.xlsx` uploads keep their extension. |
| Д11 | Excel stores an all-digit cell as a number, so an INN with a leading zero came back 9 digits and was rejected as "unexpected length 9". | Exports set the `codes` column to Excel text format (`@`) so the zero survives a round trip; on input, a 9/11-digit numeric cell is zero-padded when (and only when) the padded value passes the FNS checksum; otherwise the error message names the actual cause and the fix. |
| Д12 | Registries were written into `sample_data/`, i.e. into git — bundled reference data got overwritten by real runs. | Default registry paths moved to `data/registry/` (gitignored). `sample_data/` is now read-only reference. |
| Д13 | A crafted value in the ID column (`=cmd\|'/c calc'!A1`) was written verbatim and executed when the analyst opened the export. | Cells starting with `= + - @ \t \r` are escaped on write and unescaped on read, so append mode stays lossless. Numbers, dates and negative values are untouched. |
| Д14 | If openpyxl was installed or removed between runs, a pilot ended up with both `financial_effect.csv` and `financial_effect.xlsx` — one being read while the other grew. | An existing export's extension wins over the environment's preference. |
| Д15 | Nothing said how much of the reference data was actually populated, so a split on a 30%-covered metric looked identical to a fully covered one. | `PilotResult.coverage` per metric; the analytics package flags anything under 95% as unreliable to split on. |
| Д16 | The outbox counter restarted per run, so a second run into the same outbox silently overwrote the first run's audit trail. | Filenames carry a timestamp plus a collision suffix. |

Two audit points were **not** actioned, deliberately:

- **Н8 ("no dialogue agent")** — the hand-off is a static form plus a CLI
  by design, so the skill runs unattended in GigaCode and in a scheduler;
  see "Why an HTML request-builder, not a hosted web app" above.
- **Д5** — not reproducible here; it exists only in the renamed
  (`internal_skill`) fork, where the package rename was applied partially.

## Choosing how to split: the method questionnaire

Some pilots cannot be split once and for all. If clients are onboarded in
waves, if the eligible list keeps growing, or if the pilot runs long enough
that clients drift between segments, the list has to be split repeatedly —
strata recomputed and CG/TG comparability re-checked each time (a cascade
split with resegmentation and a rebase).

An experienced analyst knows when that applies. The person filling in the
intake form usually does not, and would never pick "cascade" from a
dropdown. So the skill does not offer the choice — it asks five questions
about the **rollout**, derives the method, shows the method's outline in
plain language, and asks whether that description matches the pilot.

### The flow

```
section 6 of web/index.html      ->  five questions, each with an "I don't know"
   (or: skill.cli advise-method)      option
                                 ->  recommended method + why + what will happen
                                     each period + what it needs from you
                                 ->  "Похоже это на ваш пилот?"
         yes                     ->  method recorded, confirmed: true
         no                      ->  the alternative's outline + a required
                                     reason, then recorded as an override
```

```bash
python -m skill.cli advise-method                      # interactive
python -m skill.cli advise-method --questions          # the questions, as JSON
python -m skill.cli advise-method --answers a.json --request request.json --json
python -m skill.cli advise-method --describe cascade_rebase   # for the confirm step
python -m skill.cli rebase-due                         # pilots owing a rebase today
```

### The three methods

| Method | Membership | Each period | Chosen when |
|---|---|---|---|
| `single` | fixed at t0 | financial articles only | everyone starts together, list is closed, pilot is short |
| `single_monitored` | **fixed at t0** | comparability re-checked; baseline rebased if it drifted | list is closed but the pilot is long, clients drop out, or their attributes move |
| `cascade_rebase` | grows wave by wave | new wave assigned into the same strata + comparability re-checked on the full membership | clients are onboarded in waves, or the list will grow |

The distinction between the last two is the one that matters:
`single_monitored` **rebases the comparison baseline, never the
membership**. Once a target-group client has had the treatment, moving them
to control to restore balance contaminates the control group — so no method
here ever re-assigns a client who is already in a group.

### What the questions are, and what each one switches on

| Question (about the rollout) | Switches on |
|---|---|
| Do all clients start on the same date, or in waves? | membership grows → cascade |
| Will the list be added to after the start? | membership grows → cascade |
| Can clients' turnover / size / ТБ / tenure change materially during the pilot? | strata drift → re-check |
| Do you expect material attrition before the pilot ends? | attrition → re-check |
| One treatment for the whole target group, or several variants? | a second-level split inside ЦГ (a modifier, not a different method) |

Pilot length is **not** asked — the term and cadence are already on the
form, so the number of recalculation periods is computed, and six or more
triggers the re-check on its own.

**"I don't know" leans toward the cascade method, deliberately.** The costs
are not symmetric: picking "no rebase" for a pilot that needed one
invalidates the result and cannot be repaired after the fact, while picking
"rebase" for a pilot that did not need one costs one balance re-check per
period that comes back "still comparable". Every unknown answer that moved
the recommendation is listed back to the user so it can be resolved instead.

### The confirmation is enforced, not cosmetic

A request carrying an answered-but-unconfirmed questionnaire is **refused**
at validation, before any side effect — it is a half-finished intake, not a
default. A request with no questionnaire at all still runs (every
`request.json` written before this feature keeps working) under the one-shot
split, and the setup package says *"the questionnaire was not filled in"*
rather than reporting it as a deliberate choice of "no rebase".
Choosing the alternative over the recommendation requires a written reason,
which lands in `pilot_meta.json` and in the pilot's note.

### What a rebase-requiring pilot leaves behind

1. `REBASE_REQUIRED.md` in the pilot folder — a checklist for whoever opens
   that folder next period, in Russian, stating plainly that the two group
   files are **not** the final membership.
2. A row in `data/registry/rebase_reminders.csv` — because no folder can
   answer "which pilots are due a rebase right now". That is what
   `skill.cli rebase-due` reads.
3. `rebase_required` / `homogeneity_recheck_required` in `pilot_meta.json`,
   so a `recalc` started months later from a folder path alone knows it owes
   a comparability check.
4. The reminder in the body of the CG/TG delivery email.
5. `homogeneity_checks.csv`, appended on every `recalc`: one row per article
   per `report_date` with the SMD, whether it is within tolerance, and
   `REBASE: пересчитать базу сравнения с этой даты` when it is not. The
   point is to show **from which period** the comparison stopped holding,
   not just that it does not hold now.

### Not built yet: executing the cascade

The questionnaire records the method and the skill now reminds, re-checks
and reports. **Assigning a new wave into an existing pilot is not
implemented yet** — today a wave means running the second batch and
reconciling by hand. Two things in the current build have to be changed
first, and both are load-bearing:

- **`PilotAlreadyExistsError` (Д3)** refuses a re-run of the same pilot
  folder. A cascade pilot deliberately returns to the same folder for wave
  2, so it needs its own `add-wave` path — `--force` would overwrite wave 1.
- **The master-status and overlap gates would block the pilot's own
  members.** Intake marks target-group clients `Used`, and `Used` blocks
  reuse; on wave 2 the pilot would reject its own wave-1 clients as
  conflicts. Both gates need scoping to exclude the pilot being added to.

The wave assignment itself is then a variant of `splitter.split()` that
takes the existing CG/TG as fixed, builds strata over the new batch only,
and fills the side that is behind first — which is what step 6 of the
`cascade_rebase` outline promises the user.

## CLI output: `--output json` (default) or `--output text`

Every command prints **one machine-readable JSON document per command**.
That is the contract a GigaCode tool wrapper (or any other agent harness)
parses, and it is unchanged — `--output json` is the default and is
byte-identical to what the CLI produced before this option existed.

`--output text` renders the *same payload* for a person, or for an agent
that has to relay the result to one:

```bash
python -m skill.cli run --output text --request request.json --inn-file inn_list.csv
python -m skill.cli --output text rebase-due        # before or after the subcommand
AB_SKILL_OUTPUT=text python -m skill.cli metrics    # or set the default
```

```
ГОТОВО: КГ и ЦГ сформированы

Пилот                    giga_style_demo (2026-10-22 .. 2027-04-22)
Метод разделения         cascade_rebase
Контрольная группа (КГ)  26 клиент(ов)
Целевая группа (ЦГ)      24 клиент(ов)
Баланс по фин. статьям   в пределах порога SMD <= 0.1 (попыток: 3, seed: 44)
Заполненность источника  chod 50/50 (100%), okved 50/50 (100%)

Файлы:
  КГ                     .../control_group.xlsx
  ЦГ                     .../target_group.xlsx
  Фин. эффект            .../financial_effect.xlsx
  Папка пилота           .../giga_style_demo_2026-10-22_2027-04-22

ТРЕБУЕТСЯ РЕБЕЙЗ: это НЕ окончательный состав групп.

СЛЕДУЮЩИЙ ШАГ:
  - Передайте файлы КГ/ЦГ заказчику (столбец ИНН переименован в codes).
  - Прочитайте REBASE_REQUIRED.md в папке пилота -- там чек-лист на каждый период.
  - На следующем периоде: python -m skill.cli recalc --pilot-folder ...
```

Three rules the text renderer follows, and they are the reason it exists:

1. **Paths, not payloads.** `run`'s JSON contains both group lists in full
   — 50+ INNs plus the whole request echoed back. The text form names the
   counts and points at the files. A test asserts no INN from the input
   appears in the rendered output.
2. **Every outcome ends in a next action.** A refusal says what to fix
   *and* that nothing was written, so nobody goes looking for a half-built
   pilot to clean up. A success names the exact next command.
3. **Nothing is ever swallowed.** Commands that print two documents
   (`run --drop-invalid-inns`) render both; output that is not JSON at all
   (`advise-method` without `--json`) passes through verbatim; a payload
   with no dedicated renderer degrades to labelled key/value lines rather
   than disappearing.

### Adapting it to a different CLI's conventions

Text rendering is an adapter applied in `main()` on the way out, not a
second code path through each command: commands still build and print the
same payload, so a command added later is covered without being touched,
and `--output text` cannot change what the skill actually did.

`skill/output.py` is therefore the only file to change for a different
house style — line prefixes, casing, status words, ordering, or a third
format alongside `json`/`text`. The dispatch table at the bottom of that
module maps each payload `status` to its renderer.

**The wording here is a sensible default, not GigaCode's documented
style** — the status words (`ГОТОВО` / `ОТКАЗ` / `ПРОПУЩЕНО`), the
aligned label column and the `СЛЕДУЮЩИЙ ШАГ` block were chosen for an
agent relaying to a Russian-speaking requester. Paste a sample of real
GigaCode CLI output into `skill/output.py`'s docstring and the renderers
can be matched to it exactly.

## Related: the ЧОД matching notebook

`docs/chod_matching_review_ru.md` reviews the internal ЧОД matching notebook
(`_chod_matching_features.ipynb` and its ~200-INN variant) and lists what
each side should take from the other.

Short version: that notebook is a **retrospective 1:1 matched DiD** study —
the training already happened, and a control is *found* for each treated
client in a 3.5M pool. This skill does **prospective stratified
randomisation** — nothing has happened yet, and we *assign* control and
target from one submitted list. Where treatment can still be assigned,
randomisation is strictly stronger than matching, so the two are
complementary rather than competing, and the notebook's design is a natural
fifth product on `web/hub.html` ("the effect already happened — find a
control group and measure it").

What is queued from it, in priority order (section 5 of the review):
minimum detectable effect checked at intake against the requested
`expected_effect_pct` (which today is collected and then ignored),
bucketed/cohort grouping attributes, stratification on pre-period trajectory,
filling the `stat_significance` column with a t-test plus a sign test,
directed swap balancing instead of random reshuffling, a dominant-client
check, and the real table names and loaded-month detection.

## Metric scripts are demo stubs until you port them — and they now say so

Every script in `metric_scripts/` ships reading
`sample_data/attributes_reference.csv`. That is deliberate: the skill runs
end to end with no cluster, and the test suite depends on it. But the
pilot's strata **and its entire balance report** are computed from whatever
these return, so a production run against an unported script used to
produce a split over fabricated attributes, a fabricated financial-effect
workbook in the Navigator dropzone, and an email reading
`Financial balance check: PASSED` — with nothing anywhere saying the
numbers were invented.

The dangerous case is a **partially ported** bank, which is the state any
port is actually in: ЧОД comes back real while ОКВЭД is still demo, and the
split looks entirely plausible.

Two independent guards, both switched on by `AB_SKILL_USE_SPARK=true`:

1. `DEMO_ONLY = True` in each bundled stub. `MetricRunner` refuses to call a
   marked script in production (`DemoDataInProductionError`). **Porting a
   script means querying the mart and deleting that line.**
2. `refuse_demo_reference_in_production()` inside `lookup_column`, which
   fires wherever the demo table is actually read — covering a new stub, or
   a half-ported script that still falls back to it on some path.

Both honour one escape hatch, `AB_SKILL_ALLOW_DEMO_DATA=true`, for a
deliberate dry run with Spark on. A typo in either variable is read as "not
production", so it fails toward the demo path working rather than toward
production quietly accepting invented numbers. See
`tests/test_demo_data_guard.py`.

Borrowed from the metrics-calculation fork (`PepsiMonster/AB_split`), which
reached the same conclusion first: *"тихие демо-числа в боевой выгрузке хуже
падения: аналитик не отличит их от настоящих."*

## Related: the AB_split metrics-calculation fork

`docs/ab_split_calc_review_ru.md` reviews `PepsiMonster/AB_split`
(branch `varvara-dev`) — **a fork of this skill** that the team developed
into the metrics-calculation product, dropping the AB splitting entirely.
It adds a one-session-per-run Spark scope with a live-session probe,
per-metric staging so a late failure does not discard earlier mart queries,
a timed run log, whole-month period arithmetic, and a `subscriptions.json`
carrying the real mart names *with honest caveats* about which ones are
unconfirmed or empty.

Two consequences worth knowing:

- **Do not push this tree over that repository's `main`.** It holds a
  developed branch of the same code; a force push would discard the team's
  work. Section 5 of the review lists what to merge module by module.
- **The same thing is done three different ways** across the matching
  notebook, that fork and this skill — most dangerously the INN key, where
  the notebook and this skill zero-pad to 10/12 digits while the fork strips
  leading zeros. That difference produces wrong numbers rather than an
  error: a join silently misses a client, or matches the wrong one. Section
  6 of the review tabulates all five divergences.

## Related: review of the production stratification notebook

`docs/split_homogeneity_review_ru.md` reviews the notebook currently used to
split pilots in production (12-variable composite stratum key, `rare_strats`
fallback, `train_test_split(stratify=...)`, then KS + z + chi² homogeneity
tests). `docs/analysis/` holds the three scripts the numbers come from.

Three findings, all reproduced by simulation:

1. **The stratification is a no-op.** The 12-variable cross product is ~56M
   cells against an N in the thousands, so 100% of clients land in the
   `rare_strats` bucket (99.7% even at N=20,000) and `stratify=` receives a
   single class — a plain random split. The `rare_strats` line is what makes
   it silent: without it sklearn would raise "the least populated class has
   only 1 member" on the first run.
2. **p-values cannot certify balance.** A fixed 0.10 SMD is flagged 9% of
   the time at n=50 and 100% at n=50,000 — same imbalance, only n changes.
   At n=100 a real 0.3 SMD passes as homogeneous 41% of the time. Effect
   sizes with a threshold (SMD, Cramér's V) answer the question that is
   actually being asked; p-values answer a different one.
3. **18 uncorrected tests at α=0.05**: 55.9% of correctly randomised splits
   fire at least one (theory says 60.3%). Re-drawing the seed until all 18
   pass selects for luck, not balance.

The recommended replacement is **rerandomisation** (Morgan & Rubin 2012) on
a Mahalanobis criterion over numeric *and* one-hot categorical covariates,
with randomization inference for the final analysis. Note the floor: at
N=200 with 12 covariates no assignment reaches an SMD of 0.1 — the
simulation plateaus at 0.22 — so small lists need *fewer* covariates, not
better search.

This skill's own reshuffle loop was already a crude rerandomisation (draw,
keep the best by worst SMD); section 6 of the review describes the three
changes that made it a principled one, and all three are now in
`skill/splitter.py`.

## Related: head-to-head against the team's splitter

`docs/ab_split_benchmark_ru.md` runs this splitter directly against
`metric_calc_skill/skill/ab_test.py` — a second implementation by another
committer, judged by **their** quality metric (`balance_check`, group skew
in sigmas) rather than ours. The bench is `docs/analysis/ab_bench.py`:

```bash
AB_BENCH_THEIRS=/path/to/metric_calc_skill python3 -I docs/analysis/ab_bench.py
```

Their design deliberately has no stratification ("заказчик приносит
произвольный список, признаков для стратов у нас на входе нет") but it
*does* compute a pre-period baseline — after the split, to report the skew.
The fairest comparison therefore gives both sides the same input (INNs plus
ЧОД/ЧЭП, no attributes): the only difference is whether that baseline is
used to choose the split or to describe it afterwards. On that footing the
worst-case starting skew eats 69%/73%/80% of the detectable effect in their
version against 25%/39%/68% in ours at N=200/500/2000 — **but by their own
alarm threshold both versions pass every run**, and the gap closes as N
grows. The value of covariates is on short lists, which is the typical ММБ
pilot.

Two of their decisions are better than ours were, and both were adopted
into `skill/allocation.py` (30 tests in `tests/test_allocation.py`):

- **Proportion chosen by power.** `SplitConfig.target_ratio = None` now
  walks a 50/50…90/10 ladder and picks the largest target share whose
  effective size `4·n_t·n_c/N` still clears what the requested MDE needs —
  so more clients get the treatment when the list can afford it, and a list
  that cannot even support 50/50 is split evenly and *said* to be
  underpowered. The default stays 50/50 (maximum power, and what existing
  pilots assume); the ladder is opt-in.
- **Seed derived from the pilot.** It was the constant `42`, so two
  different pilots over the same list got the *same* split.
  `random_seed = None` now derives it from the pilot name and start date.
  The documented flip side, which we repeat in the docstring: rename the
  pilot or move its start date and the membership changes — measured at 29%
  of clients. Do not touch those fields on a running pilot.

The bench's most useful finding was about our own loop: it **stopped at the
threshold instead of minimising**. At the default 0.1 the first draw already
passes, so 1 draw and 1000 draws returned an identical split — the
rerandomisation was there on paper and doing nothing. Three changes fixed
it, and the numbers above are all post-fix (before it, our worst case ate
25%/39%/68% of MDE instead of 21%/16%/6%):

1. **The threshold is an acceptance bar, not a search target.** The loop
   spends its draw budget and keeps the minimum. It stops early only once
   the bar is met and `search_patience` (250) consecutive draws have failed
   to improve — a cost control, since improvements that late are rare and
   tiny.
2. **The criterion is a real Mahalanobis distance** (inverse covariance of
   the design) rather than a sum of squared SMDs. A sum counts one
   underlying imbalance once per correlated column — a money level and its
   own trend, the dummies of one attribute — so the search drifted towards
   whichever attribute had the most levels. `tests/test_rerandomisation.py`
   measures this: four copies of one direction cost 4× under the sum and 1×
   under Mahalanobis.
3. **Draws are ranked lexicographically**, `(excess over the per-covariate
   allowance, criterion)`. Minimising the criterion alone returned a draw
   that *failed* the bar when a passing one had already been seen —
   measured, 0.133 at 25 draws became 0.171 at 200. Note the consequence:
   `worst_smd` alone is **not** monotone in the draw budget, and should not
   be read as if it were. Once every covariate sits deep inside the bar the
   criterion will happily trade 0.002 on one of them for gains across the
   other thirty. The ranking key is what is monotone.

One statistical consequence worth stating, because it reaches the analysis
and not just the split: best-of-N selection is no longer simple
randomisation, so a permutation test over the final groups is not exact.
It errs safe — Morgan & Rubin show the Fisher test over the full
permutation set is *conservative* on a rerandomised design — so
`skill/analysis.py` keeps using it, and `attempts_used` records how many
draws the selection ran over.

## The rebuild: window, rerandomisation, analytics

Everything in `docs/BUILD_PLAN_ru.md` is now built. What changed, and why.

### Groups are judged over a window, not on one day

One month of ЧОД for an ММБ client swings by tens of percent, so a balance
check on a single `as_of_date` was comparing noise. The metric contract now
carries a monthly series:

```python
run(inn_list, as_of_date, spark=None, filters=None, months=None)
# -> {инн: 1234.5}                        a flat answer, still supported
# -> {инн: {"2026-01": 1234.5, ...}}      a window
```

`MetricRunner.run()` keeps the old scalar view as the window mean, so every
existing caller is numerically unchanged; `run_series()` gives the full
panel. `months` is passed only to scripts whose signature accepts it, the
same way `filters` was introduced, so one bank can hold three generations
of script. A flat answer is *marked* flat rather than repeated across the
window — it carries no history, and inventing a trend from it would be
worse than having none.

`MetricSeries` also carries the distinction the skill was losing: a client
absent from the mart has **no entry**, a client earning zero has `0.0`.
Collapsing both to `None` made a data-supply problem look like a business
one.

### Continuous values can never be stratum keys

`skill/features.py` prepares attributes before they reach a key: numerics
are quantile-bucketed, ОКВЭД is reduced to its 21 ОКВЭД2 sections, tenure to
three states, and the trajectory cohort of the leading article joins the
strata. Cohorts are deliberately **not** the matching methodology's rule:
that one classifies growth by `L / F` and so needs `F > 0 and L > 0`, which
sends every loss-making client to "Нерегулярные" on arithmetic rather than
behaviour. Classifying on the asinh trend removes the carve-out — steady
losses are Стабильные, doubling losses are Снижающиеся.

### The split is a real rerandomisation

Morgan & Rubin, with the three changes the analysis called for: the
criterion is the summed squared standardised mean difference across **every**
covariate (money levels, trends, dummy-coded categorical levels), the draw
count is 1000 under a work budget rather than 25, and the threshold is
declared with failure reported.

Two things were learned building it, both now in the code:

- **A categorical level holding an odd number of clients cannot be split
  evenly.** Five clients in fifty is 0.133 SMD at best — above the 0.1
  convention before anything has gone wrong. Each column is judged against
  the better of the threshold and its own achievable floor, so the guard
  reports imbalance rather than indivisibility.
- **Stratifying and rerandomising pull against each other.** 36 cells over
  50 clients leaves no freedom in a draw, so a thousand of them improve
  nothing. Attributes are taken into the strata coarsest-first and only
  while cells hold at least `min_clients_per_stratum`; the rest are balanced
  on as covariates. Nothing is dropped — the criterion sees everything
  either way.

### The pilot now says whether it can measure what it was asked to

`expected_effect_pct` had been collected, validated and ignored since the
first version. It is now compared against the minimum detectable effect,
computed from the pre-period spread at the realised group sizes:

```
пилот из 25 клиентов в группе различит эффект примерно от 49% при мощности 80%; заявлено 5%
```

A warning by default — the skill cannot know that direction alone is not
what the business wanted — and an error under `--require-power`.

### Pilot analytics

```bash
python -m skill.cli report --pilot-folder data/pilots/<slug> --text
```

The pilot has been accumulating a panel all along: `financial_effect` is
written in append mode, one block per `report_date`, each row carrying
client, group and articles. `skill/analysis.py` is a read layer over that
file — no new collection, no second query against the mart. It computes the
difference-in-differences with a confidence interval, a permutation test
beside the t-test, the share of clients up in each group, which clients
carry the change, the baseline SMD, the comparability history and
asymmetric dropout.

Three renderings over one computation: a deterministic text overview (email,
`--output text`, and what an agent relays), an Excel workbook with line
charts, and a standalone HTML dashboard. All three are rebuilt by every
`recalc`, so an open link always shows the latest state.

**Two tests rather than one, deliberately.** The t-test on means is carried
by the largest clients; the permutation test is not. When they disagree that
is the answer to "who is this effect riding on", and the verdict line says
so in words.

Rehearsed end to end over six periods: **+60% injected reads back as +67.9%**
(p=0.0016, permutation p=0.0006, 92% of the target group up against 52% of
control), and an **A/A run with nothing injected reads +3.7%, p=0.75** — no
false effect.

### Operational

Ported from the metrics-calculation fork, where they were already proven:
one Spark session per run with `probe_session` testing liveness by running a
job rather than trusting the object; per-metric staging so a failure on the
last article does not discard the earlier queries; a timed run log with
`index.jsonl` for comparing runs. All wired into `recalc`, where a late
failure costs the most.

`metric_scripts/subscriptions.py` gained candidate tables (the same mart is
exposed under different schemas to different teams) and column-by-role
lookup (the period column is `period_type` in one mart and `speriodtype` in
its replacement).

**Real mart names are not in this repository.** It is public and a schema
name cannot be un-pushed. The committed file holds structure and
`example_db` placeholders; real names go in `subscriptions.local.json`
(gitignored) or behind `AB_SKILL_SUBSCRIPTIONS`, and a test asserts the
committed file still has none.

### One theme

`skill/theme.py` is the single source of the palette — the dark teal
identity from the team's `front.html`, extended to a light/dark pair because
these pages get projected and printed. `web/build_form.py` generates
`web/_theme.css` from it and the report inlines the same tokens, since a
standalone file that gets emailed cannot rely on a relative link. The
palette used to be copy-pasted into every page three or four times over; a
test now fails if any page declares its own.

Contrast is checked rather than eyeballed: the original `#2ee6a6` carries
1.9:1 against white and is invisible as a button, so the light accent is
`#0a7f5f` for 4.6:1.
