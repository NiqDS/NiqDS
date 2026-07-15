# AB-Testing Batch Allocation Skill

Turns a submitted list of client INNs into balanced Control (КГ) / Target
(ЦГ) groups for a bank pilot, computes the financial-effect metrics the
pilot is measured on, and keeps recalculating them on a schedule for a
Navigator dashboard. Implements the 7-step agent process from the source
spec (`docs/original_spec_ru.md` — extracted verbatim from the attached
`.docx`).

Deliverable shape, per the brief:

- **Requester** gets two files: `control_group` and `target_group` (INN
  column renamed to `codes`, per spec step 4).
- **Analytics team** gets the same two files **plus** a plain-text
  description of the pilot (term, recalculation cadence, requester,
  grouping metrics used, financial-effect articles measured, expected
  effect %, balance-check result) — see `_format_pilot_package` in
  `skill/pipeline.py`.
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

# 1. open web/index.html in a browser, fill the form, submit ->
#    downloads request.json + inn_list.csv

# 2. hand them to the skill
python -m skill.cli run --request request.json --inn-file inn_list.csv

# 3. later, on whatever cadence the pilot's recalculation_frequency implies
python -m skill.cli recalc --pilot-folder "data/pilots/<pilot_slug>"
```

Run the test suite:

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

## Architecture

```
web/index.html  ──(request.json + inn_list.csv)──▶  skill/cli.py
                                                          │
                                                          ▼
                                                  skill/pipeline.py
                                                  run_intake()
        step 1  inn_utils.validate_file()      ── format + FNS checksum
        step 2  registries.check_and_register()── dedupe vs "involved INNs"
        step 3  registries.MetricRequestsRegistry ── new-metric backlog
        step 4  metrics/runner.py + splitter.py ── stratified split + balance check
                exporter.write_group_file()     ── control_group / target_group
        step 5  exporter.write_financial_effect_file()
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

### Directory layout

```
skill/                  core package (no I/O side effects outside what's listed below)
  config.py             every path/threshold a deployment needs to change lives here
  models.py              PilotRequest, SplitResult, PilotResult, ...
  inn_utils.py           step 1: file format + INN checksum validation
  registries.py           the 3 prerequisite CSV tables from the spec + step 2 logic
  metrics/runner.py       dispatches metric codes to metric_scripts/*
  splitter.py             step 4: stratified split + financial balance check
  exporter.py             xlsx/csv writers (falls back to csv without openpyxl)
  connectors/              pluggable email + Navigator upload (mock by default)
  pipeline.py              orchestrates steps 1-5 (run_intake)
  monitoring.py            step 6 (run_recalculation) + step 7 helper (is_due)
  cli.py                   `python -m skill.cli run|recalc|metrics`
metric_scripts/           demo "bank of PySpark scripts", one file per metric
  manifest.json            catalog: code, label, value_type, usable_as, script
sample_data/               demo reference data + empty prerequisite tables
web/
  _template.html           source template (edit this, not index.html)
  build_form.py            regenerates index.html's metric checkboxes from manifest.json
  index.html               generated MVP intake form — open directly in a browser
tests/                     pytest suite (27 tests), all I/O redirected into tmp_path
docs/original_spec_ru.md   the original spec, verbatim, for traceability
data/pilots/               runtime output — one folder per pilot (gitignored contents)
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
| Per-INN attributes (OKVED/OPF/TB/tenure/ЧОД/ЧЭП/...) | `metric_scripts/*.py` read `sample_data/attributes_reference.csv` | Point `MetricScriptConfig.scripts_dir` at the real PySpark script bank (same `run(inn_list, as_of_date, spark)` signature) and set `AB_SKILL_USE_SPARK=true` |
| Email | `LoggingEmailConnector` writes `.eml.txt` files to `data/pilots/_outbox/` | `SmtpEmailConnector` in `skill/connectors/email_connector.py` (fill in host/port/sender) |
| Navigator dashboard upload | `LocalDropzoneDashboardConnector` copies the workbook to `data/navigator_dropzone/` | `HttpNavigatorConnector` stub — raises `NotImplementedError` until Navigator's real upload API is known |

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
- **A fully malformed submission blocks the whole file**, not just the bad
  rows (`IntakeRejected`), matching "агент пишет заказчику с просьбой
  переделать входной файл в нужном формате" read literally.
- **`metric_requests` backlog table** (step 3's "нужной проверки нет ...
  высылается команде разработки") isn't one of the spec's 3 prerequisite
  tables; added as a 4th CSV so requests are queryable instead of a
  one-off email that's easy to lose.

## Known limitation: over-stratification on small candidate lists

Stratifying on 4 categorical dimensions (OKVED × OPF × TB × tenure bucket)
needs enough candidates per combination for the 50/50 split to actually
land near 50/50 — with a few hundred distinct strata and a candidate list
in the low hundreds, many strata end up with 1–2 members each, which can
skew the overall CG/TG ratio even though each stratum itself is correctly
balanced. For small pilots, either select fewer grouping metrics in step 3
or expect a real overall ratio (not the requested `target_ratio`) and rely
on the balance report per stratum instead of the aggregate count.
