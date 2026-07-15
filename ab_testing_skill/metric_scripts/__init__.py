"""Demo "bank" of per-metric scripts.

In production this whole directory is replaced by pointing
`MetricScriptConfig.scripts_dir` at the real PySpark script bank. Every
script here is intentionally tiny and follows one contract:

    def run(inn_list: list[str], as_of_date: date, spark=None) -> dict[str, Any]

returning one value per INN (or None if the client isn't found for that
metric). skill/metrics/runner.py loads whichever script the manifest maps
a metric code to and calls it -- it does not care whether the body reads
a local CSV (as these demo scripts do) or runs a real spark.sql(...) job.
"""
