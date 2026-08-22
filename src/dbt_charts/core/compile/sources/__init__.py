"""Data-source and dbt-profile detection.

`detection.py` infers a project's database type and connection settings from
dbt profiles/artifacts; `dbt_jinja.py` renders Jinja inside source and
profile config values, a sources concern that happens to use Jinja rather
than a templating one.
"""
