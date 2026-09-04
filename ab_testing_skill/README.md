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
pip install -r requirements.txt   # optional: only needed for .xlsx output, else falls back to .csv
cd ab_testing_skill

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
- **CG/TG split method**: stratified random 50/50 within each combination
  of the chosen grouping metrics, then a balance check on the chosen
  financial metrics' means (`SplitConfig.max_relative_imbalance`, default
  10%); reshuffles within strata up to `max_reshuffle_attempts` times if
  unbalanced.
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

## Known limitation: over-stratification on small candidate lists

Stratifying on 4 categorical dimensions (OKVED × OPF × TB × tenure bucket)
needs enough candidates per combination for the 50/50 split to actually
land near 50/50 — with a few hundred distinct strata and a candidate list
in the low hundreds, many strata end up with 1–2 members each, which can
skew the overall CG/TG ratio even though each stratum itself is correctly
balanced. For small pilots, either select fewer grouping metrics in step 3
or expect a real overall ratio (not the requested `target_ratio`) and rely
on the balance report per stratum instead of the aggregate count.
