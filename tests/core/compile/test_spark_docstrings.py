"""Regression tests for spark field descriptions (item 5 of PR #2637 design-debt cleanup).

The `progress`, `bars`, and `histogram` type names were renamed to `bar`,
`bar-normalize`, and `columns` respectively. Field descriptions must use the
current vocabulary — stale descriptions lie to authors and AI assistants.
"""

from dbt_charts.core.compile.models.chart.authored import SparkConfig


def test_spark_type_description_uses_current_names():
    """SparkConfig.type description must list current accepted names, not renamed-away ones."""
    desc = SparkConfig.model_fields["type"].description
    assert desc is not None

    for stale in ("progress", "bars", "histogram"):
        assert stale not in desc, (
            f"SparkConfig.type description still mentions renamed-away type "
            f"'{stale}': {desc!r}"
        )

    for current in ("bar", "bar-normalize", "columns"):
        assert current in desc, (
            f"SparkConfig.type description missing current type '{current}': {desc!r}"
        )


def test_spark_bar_field_descriptions_use_bar_vocabulary():
    """Bar / bar-normalize field descriptions must not say 'progress bar'."""
    stale_fields = ["max", "thresholds", "background", "border_radius"]
    for fname in stale_fields:
        desc = SparkConfig.model_fields[fname].description or ""
        assert "progress" not in desc.lower(), (
            f"SparkConfig.{fname} description still says 'progress': {desc!r}"
        )
