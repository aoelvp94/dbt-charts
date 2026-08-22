"""Tests for removed authored VL passthrough fields.

Raw chart-level `mark`, `encoding`, `spec`, and the eight formerly-passthrough
fields (`config`, `transform`, `params`, `resolve`, `hconcat`, `vconcat`,
`concat`, `repeat`) are all off-limits on the authored surface. Authors must
use top-level Dataface fields and the typed `style:` object exclusively.

PR #1053 removed config/transform/params/spec. PR #1058 accidentally re-added
them (plus four composition fields) during a rebase. This file pins the
correct rejection policy for all eleven fields so future rebases cannot silently
re-instate the escape hatches.
"""

from __future__ import annotations

import pytest

from dbt_charts.core.compile.compiler import CompileResult, compile

REMOVED_VL_FIELDS = (
    "mark",
    "encoding",
    "spec",
    "config",
    "transform",
    "params",
    "resolve",
    "hconcat",
    "vconcat",
    "concat",
    "repeat",
)


def _compile_chart_yaml(chart_fields: str) -> CompileResult:
    """Helper: compile a minimal board with one chart."""
    yaml_content = f"""\
title: Test
queries:
  q1:
    sql: SELECT 1
    source: test_db
charts:
  mychart:
    query: q1
    type: bar
    x: col_a
    y: col_b
{chart_fields}
rows:
  - mychart
"""
    return compile(yaml_content)


class TestRemovedVLPassthroughFields:
    """All removed VL fields are rejected unconditionally."""

    @pytest.mark.parametrize("field", REMOVED_VL_FIELDS)
    def test_passthrough_field_rejected(self, field):
        """Each removed VL field is rejected by Pydantic's extra='forbid'."""
        yaml_snippet = f"    {field}:\n      foo: bar"
        result = _compile_chart_yaml(yaml_snippet)
        assert not result.success

    def test_typed_fields_still_allowed(self):
        """Typed Dataface fields compile normally."""
        result = _compile_chart_yaml("")
        assert result.success, result.errors

    def test_multiple_removed_fields_rejected(self):
        """Multiple removed VL fields are each rejected."""
        result = _compile_chart_yaml(
            "    mark:\n      type: bar\n    spec:\n      foo: bar"
        )
        assert not result.success


class TestChartFiltersRejected:
    """Chart-level `filters:` (the post-query row filter) was deleted.

    Data transformations live in the query (inline or named), not on the chart.
    Authored `filters:` on a chart is now rejected by `extra="forbid"`; the
    surviving `filters:` grammar is query-level (sqlglot injection), unrelated.
    """

    def test_chart_filters_rejected(self):
        """A `filters:` block on an authored chart raises extra_forbidden."""
        result = _compile_chart_yaml("    filters:\n      region: selected_region")
        assert not result.success
        assert any("filters" in str(e) for e in result.errors)

    def test_chart_operator_dict_filters_rejected(self):
        """The operator-dict form of chart `filters:` is rejected too."""
        result = _compile_chart_yaml(
            "    filters:\n      revenue:\n        gte: min_revenue"
        )
        assert not result.success
        assert any("filters" in str(e) for e in result.errors)


class TestKpiSubtitleRejectedInYaml:
    """KPI dropped `subtitle:` in favor of `support: {value, label}`.

    KpiChart declares `extra="forbid"` and does not declare `subtitle:`, so the field
    is rejected structurally. The YAML compile path catches it before render.
    """

    def test_kpi_subtitle_yaml_rejected_with_migration_hint(self):
        yaml_content = """\
title: Test
queries:
  q1:
    sql: SELECT 1
    source: test_db
charts:
  mykpi:
    query: q1
    type: kpi
    value: revenue
    label: Revenue
    subtitle: caption that should never silently render
rows:
  - mykpi
"""
        result = compile(yaml_content)
        assert not result.success
        msg = str(result.errors[0])
        assert "subtitle" in msg
        assert "support" in msg

    def test_non_kpi_subtitle_still_allowed(self):
        """Non-KPI charts can still author subtitle (it renders)."""
        yaml_content = """\
title: Test
queries:
  q1:
    sql: SELECT 1
    source: test_db
charts:
  mybar:
    query: q1
    type: bar
    x: col_a
    y: col_b
    subtitle: A real subtitle
rows:
  - mybar
"""
        result = compile(yaml_content)
        assert result.success, result.errors

    def test_empty_subtitle_on_kpi_is_rejected(self):
        """`subtitle` is not a valid field on KPI charts; even empty string is rejected.

        KpiChart inherits from _BaseChartFields (no subtitle) so extra="forbid"
        rejects subtitle regardless of its value.
        """
        yaml_content = """\
title: Test
queries:
  q1:
    sql: SELECT 1
    source: test_db
charts:
  mykpi:
    query: q1
    type: kpi
    value: revenue
    label: Revenue
    subtitle: ""
rows:
  - mykpi
"""
        result = compile(yaml_content)
        assert not result.success
        assert any("subtitle" in str(e) for e in result.errors)
