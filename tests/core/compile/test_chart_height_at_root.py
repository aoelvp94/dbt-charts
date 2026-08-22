"""Tests for chart sizing fields.

- height and width live at chart root
- aspect_ratio, min_height, max_height live in style: (promoted to compiled Chart root)
"""

from __future__ import annotations

import pytest

from dbt_charts.core.compile.compiler import compile as compile_board
from dbt_charts.core.compile.models.chart.authored import BarChart

# ============================================================================
# Authoring surface: chart-root fields (height, width)
# ============================================================================


def test_chart_patch_accepts_height() -> None:
    """chart.height: 400 parses and is accessible on BarChart."""
    patch = BarChart(type="bar", x="month", y="revenue", height=400)
    assert patch.height == 400


def test_chart_patch_accepts_float_height() -> None:
    """chart.height accepts float (e.g. 400.5)."""
    patch = BarChart(type="bar", x="month", y="revenue", height=400.5)
    assert patch.height == 400.5


def test_chart_patch_accepts_width() -> None:
    """chart.width: 800 parses and is accessible on BarChart."""
    patch = BarChart(type="bar", x="month", y="revenue", width=800)
    assert patch.width == 800


def test_compiled_chart_has_height() -> None:
    """chart.height: 400 compiles and Chart.height == 400."""
    result = compile_board(
        """
title: T
queries:
  q:
    source: db
    sql: SELECT 'Jan' AS month, 100 AS revenue
charts:
  revenue:
    query: q
    type: bar
    x: month
    y: revenue
    height: 400
rows:
  - revenue
"""
    )
    assert result.success, f"Compile failed: {result.errors}"
    assert result.board is not None
    chart = result.board.charts["revenue"]
    assert chart.height == 400


def test_compiled_chart_has_width() -> None:
    """chart.width: 800 compiles and Chart.width == 800."""
    result = compile_board(
        """
title: T
queries:
  q:
    source: db
    sql: SELECT 'Jan' AS month, 100 AS revenue
charts:
  revenue:
    query: q
    type: bar
    x: month
    y: revenue
    width: 800
rows:
  - revenue
"""
    )
    assert result.success, f"Compile failed: {result.errors}"
    assert result.board is not None
    chart = result.board.charts["revenue"]
    assert chart.width == 800


# ============================================================================
# Authoring surface: style fields (aspect_ratio, min_height, max_height)
# ============================================================================


def test_style_aspect_ratio_compiles_to_chart() -> None:
    """style.aspect_ratio: 2.0 is promoted to Chart.aspect_ratio at compile time."""
    result = compile_board(
        """
title: T
queries:
  q:
    source: db
    sql: SELECT 'Jan' AS month, 100 AS revenue
charts:
  revenue:
    query: q
    type: bar
    x: month
    y: revenue
    style:
      aspect_ratio: 2.0
rows:
  - revenue
"""
    )
    assert result.success, f"Compile failed: {result.errors}"
    assert result.board is not None
    chart = result.board.charts["revenue"]
    assert chart.aspect_ratio == 2.0


def test_style_min_height_compiles_to_chart() -> None:
    """style.min_height: 100.0 is promoted to Chart.min_height at compile time."""
    result = compile_board(
        """
title: T
queries:
  q:
    source: db
    sql: SELECT 'Jan' AS month, 100 AS revenue
charts:
  revenue:
    query: q
    type: bar
    x: month
    y: revenue
    style:
      min_height: 100.0
rows:
  - revenue
"""
    )
    assert result.success, f"Compile failed: {result.errors}"
    assert result.board is not None
    chart = result.board.charts["revenue"]
    assert chart.min_height == 100.0


def test_style_max_height_compiles_to_chart() -> None:
    """style.max_height: 600.0 is promoted to Chart.max_height at compile time."""
    result = compile_board(
        """
title: T
queries:
  q:
    source: db
    sql: SELECT 'Jan' AS month, 100 AS revenue
charts:
  revenue:
    query: q
    type: bar
    x: month
    y: revenue
    style:
      max_height: 600.0
rows:
  - revenue
"""
    )
    assert result.success, f"Compile failed: {result.errors}"
    assert result.board is not None
    chart = result.board.charts["revenue"]
    assert chart.max_height == 600.0


# ============================================================================
# aspect_ratio at chart root must raise validation error (moved to style:)
# ============================================================================


def test_aspect_ratio_at_chart_root_raises_error() -> None:
    """aspect_ratio at chart root raises a validation error (it belongs in style:)."""
    result = compile_board(
        """
title: T
queries:
  q:
    source: db
    sql: SELECT 'Jan' AS month, 100 AS revenue
charts:
  bad:
    query: q
    type: bar
    x: month
    y: revenue
    aspect_ratio: 2.0
rows:
  - bad
"""
    )
    assert not result.success


# ============================================================================
# style.height must still raise error with chart-root hint
# ============================================================================


def test_style_height_raises_error_with_migration_hint() -> None:
    """style.height on a chart raises an error with chart-root migration hint."""
    result = compile_board(
        """
title: T
queries:
  q:
    source: db
    sql: SELECT 'Jan' AS month, 100 AS revenue
charts:
  bad:
    query: q
    type: bar
    x: month
    y: revenue
    style:
      height: 400
rows:
  - bad
"""
    )
    assert not result.success
    all_text = " ".join((e.message or "") + " " + (e.hint or "") for e in result.errors)
    assert "height" in all_text
    assert "chart root" in all_text.lower()


def test_style_width_raises_error_with_migration_hint() -> None:
    """style.width on a chart raises an error with chart-root migration hint."""
    result = compile_board(
        """
title: T
queries:
  q:
    source: db
    sql: SELECT 'Jan' AS month, 100 AS revenue
charts:
  bad:
    query: q
    type: bar
    x: month
    y: revenue
    style:
      width: 800
rows:
  - bad
"""
    )
    assert not result.success
    all_text = " ".join((e.message or "") + " " + (e.hint or "") for e in result.errors)
    assert "width" in all_text
    assert "chart root" in all_text.lower()


# ============================================================================
# height/width rejected on renderer-owned types (kpi, table, callout,
# spark_bar) — their renderers own sizing; these fields would be silent no-ops.
# ============================================================================


def test_height_rejected_on_kpi() -> None:
    """chart.height not declared on KpiChart — extra_forbidden rejects it."""
    from pydantic import ValidationError

    from dbt_charts.core.compile.models.chart.authored import KpiChart

    with pytest.raises(ValidationError):
        KpiChart(type="kpi", value="x", height=500)  # type: ignore[call-arg]


def test_height_rejected_on_table() -> None:
    """chart.height not declared on TableChart — extra_forbidden rejects it."""
    from pydantic import ValidationError

    from dbt_charts.core.compile.models.chart.authored import TableChart

    with pytest.raises(ValidationError):
        TableChart(type="table", height=300)  # type: ignore[call-arg]


def test_width_rejected_on_spark_bar() -> None:
    """chart.width not declared on SparkBarChart — extra_forbidden rejects it."""
    from pydantic import ValidationError

    from dbt_charts.core.compile.models.chart.authored import SparkBarChart

    with pytest.raises(ValidationError):
        SparkBarChart(type="spark_bar", width=400)  # type: ignore[call-arg]


# ============================================================================
# Positive-value validation: height and width must be > 0
# ============================================================================


def test_height_zero_rejected() -> None:
    """chart.height: 0 is rejected (must be > 0)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="greater than 0"):
        BarChart(type="bar", x="x", y="y", height=0)


def test_height_negative_rejected() -> None:
    """chart.height: -50 is rejected (must be > 0)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="greater than 0"):
        BarChart(type="bar", x="x", y="y", height=-50)


def test_width_zero_rejected() -> None:
    """chart.width: 0 is rejected (must be > 0)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="greater than 0"):
        BarChart(type="bar", x="x", y="y", width=0)


def test_width_negative_rejected() -> None:
    """chart.width: -50 is rejected (must be > 0)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="greater than 0"):
        BarChart(type="bar", x="x", y="y", width=-50)


# ============================================================================
# chart-root min_height / max_height now in style: only
# ============================================================================


def test_chart_patch_min_height_not_at_root() -> None:
    """chart.min_height at root raises a validation error (it belongs in style:)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BarChart(type="bar", x="month", y="revenue", min_height=80)  # type: ignore[call-arg]


def test_chart_patch_max_height_not_at_root() -> None:
    """chart.max_height at root raises a validation error (it belongs in style:)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BarChart(type="bar", x="month", y="revenue", max_height=200)  # type: ignore[call-arg]


def test_compiled_chart_has_min_height() -> None:
    """style.min_height: 80 compiles and Chart.min_height == 80."""
    result = compile_board(
        """
title: T
queries:
  q:
    source: db
    sql: SELECT 'Jan' AS month, 100 AS revenue
charts:
  revenue:
    query: q
    type: bar
    x: month
    y: revenue
    style:
      aspect_ratio: 1.5
      min_height: 80
rows:
  - revenue
"""
    )
    assert result.success, f"Compile failed: {result.errors}"
    assert result.board is not None
    chart = result.board.charts["revenue"]
    assert chart.min_height == 80


def test_compiled_chart_has_max_height() -> None:
    """style.max_height: 200 compiles and Chart.max_height == 200."""
    result = compile_board(
        """
title: T
queries:
  q:
    source: db
    sql: SELECT 'Jan' AS month, 100 AS revenue
charts:
  revenue:
    query: q
    type: bar
    x: month
    y: revenue
    style:
      aspect_ratio: 1.5
      max_height: 200
rows:
  - revenue
"""
    )
    assert result.success, f"Compile failed: {result.errors}"
    assert result.board is not None
    chart = result.board.charts["revenue"]
    assert chart.max_height == 200


# ============================================================================
# Non-cartesian families: aspect_ratio/min_height/max_height excluded from style
# ============================================================================


def test_kpi_style_aspect_ratio_raises_error() -> None:
    """kpi.style.aspect_ratio is invalid — KPI uses a fixed-height sizing contract."""
    result = compile_board(
        """
title: T
queries:
  q:
    source: db
    sql: SELECT 100 AS revenue
charts:
  revenue:
    query: q
    type: kpi
    value: revenue
    style:
      aspect_ratio: 2.0
rows:
  - revenue
"""
    )
    assert not result.success
    assert result.errors


def test_table_style_aspect_ratio_raises_error() -> None:
    """table.style.aspect_ratio is invalid — table uses row-count sizing."""
    result = compile_board(
        """
title: T
queries:
  q:
    source: db
    sql: SELECT 'a' AS name, 1 AS val
charts:
  t:
    query: q
    type: table
    style:
      aspect_ratio: 1.5
rows:
  - t
"""
    )
    assert not result.success
    assert result.errors


def test_geoshape_style_aspect_ratio_accepted() -> None:
    """geoshape.style.aspect_ratio is valid and gets promoted to chart root."""
    result = compile_board(
        """
title: T
queries:
  q:
    source: db
    sql: SELECT 'US' AS iso_code, 100 AS value
charts:
  map:
    query: q
    type: geoshape
    geo: iso_code
    color: value
    style:
      aspect_ratio: 1.8
rows:
  - map
"""
    )
    assert result.success, f"Compile failed: {result.errors}"
    assert result.board is not None
    chart = result.board.charts["map"]
    assert chart.aspect_ratio == 1.8
