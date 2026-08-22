"""Compile-time warning for the flat cols: >4-unsized-cells anti-pattern.

The count is over *growable* cells only: KPI cards are height-stable, so a row
of them is a deliberate scorecard, not the unpredictable-height anti-pattern the
warning targets. KPI cells are carved out of the count regardless of how they are
referenced (bare name, inline dict, or named-chart shorthand).
"""

from __future__ import annotations

from dbt_charts.core.compile import compile

# Two charts sharing one values query: a growable bar and a height-stable KPI.
_QUERIES_AND_CHARTS = """
queries:
  q:
    type: values
    rows:
      - {x: 1, y: 2}
charts:
  bar_c:
    query: q
    type: bar
    x: x
    y: y
  kpi_c:
    query: q
    type: kpi
    value: x
"""


def _warning_codes(yaml: str) -> set[str]:
    result = compile(yaml)
    assert result.success, result.errors
    return {w.code for w in result.warnings}


def test_flat_cols_with_six_unsized_chart_cells_warns() -> None:
    yaml = f"""
{_QUERIES_AND_CHARTS}
cols: [bar_c, bar_c, bar_c, bar_c, bar_c, bar_c]
"""
    result = compile(yaml)

    assert result.success, result.errors
    warnings = [
        w for w in result.warnings if w.code == "WARN-FLAT-COLS-UNSIZED-OVERFLOW"
    ]
    assert len(warnings) == 1
    assert warnings[0].path == "cols"
    assert "6 unsized" in warnings[0].message
    assert "rows-in-cols" in warnings[0].fix.lower()


def test_flat_cols_with_four_unsized_chart_cells_does_not_warn() -> None:
    yaml = f"""
{_QUERIES_AND_CHARTS}
cols: [bar_c, bar_c, bar_c, bar_c]
"""
    assert "WARN-FLAT-COLS-UNSIZED-OVERFLOW" not in _warning_codes(yaml)


def test_flat_cols_with_five_unsized_chart_cells_warns() -> None:
    """Boundary test: 5 growable cells is 1 over the threshold (max 4)."""
    yaml = f"""
{_QUERIES_AND_CHARTS}
cols: [bar_c, bar_c, bar_c, bar_c, bar_c]
"""
    assert "WARN-FLAT-COLS-UNSIZED-OVERFLOW" in _warning_codes(yaml)


def test_flat_cols_with_five_sized_cells_does_not_warn() -> None:
    yaml = f"""
{_QUERIES_AND_CHARTS}
cols:
  - width: "20%"
    rows: [bar_c]
  - width: "20%"
    rows: [bar_c]
  - width: "20%"
    rows: [bar_c]
  - width: "20%"
    rows: [bar_c]
  - width: "20%"
    rows: [bar_c]
"""
    assert "WARN-FLAT-COLS-UNSIZED-OVERFLOW" not in _warning_codes(yaml)


def test_nested_rows_in_cols_density_recipe_does_not_warn() -> None:
    yaml = f"""
{_QUERIES_AND_CHARTS}
rows:
  - cols:
      - width: "17%"
        rows: [bar_c, bar_c]
      - width: "55%"
        rows: [bar_c]
"""
    assert "WARN-FLAT-COLS-UNSIZED-OVERFLOW" not in _warning_codes(yaml)


def test_flat_cols_of_six_kpis_does_not_warn() -> None:
    """The carve-out: a row of KPI cards is a scorecard, not the anti-pattern."""
    yaml = f"""
{_QUERIES_AND_CHARTS}
cols: [kpi_c, kpi_c, kpi_c, kpi_c, kpi_c, kpi_c]
"""
    assert "WARN-FLAT-COLS-UNSIZED-OVERFLOW" not in _warning_codes(yaml)


def test_flat_cols_of_inline_kpis_does_not_warn() -> None:
    """KPIs authored inline (no named-chart ref) are carved out too."""
    yaml = """
queries:
  q:
    type: values
    rows:
      - {x: 1}
cols:
  - {type: kpi, query: q, value: x}
  - {type: kpi, query: q, value: x}
  - {type: kpi, query: q, value: x}
  - {type: kpi, query: q, value: x}
  - {type: kpi, query: q, value: x}
  - {type: kpi, query: q, value: x}
"""
    assert "WARN-FLAT-COLS-UNSIZED-OVERFLOW" not in _warning_codes(yaml)


def test_flat_cols_of_named_shorthand_kpis_does_not_warn() -> None:
    """The single-key named-chart shorthand KPI shape is carved out too."""
    yaml = """
queries:
  q:
    type: values
    rows:
      - {x: 1}
cols:
  - {k1: {type: kpi, query: q, value: x}}
  - {k2: {type: kpi, query: q, value: x}}
  - {k3: {type: kpi, query: q, value: x}}
  - {k4: {type: kpi, query: q, value: x}}
  - {k5: {type: kpi, query: q, value: x}}
  - {k6: {type: kpi, query: q, value: x}}
"""
    assert "WARN-FLAT-COLS-UNSIZED-OVERFLOW" not in _warning_codes(yaml)


def test_flat_cols_kpis_not_counted_toward_threshold() -> None:
    """Only growable cells count: 4 bars + 4 KPIs stays under the max."""
    yaml = f"""
{_QUERIES_AND_CHARTS}
cols: [bar_c, bar_c, bar_c, bar_c, kpi_c, kpi_c, kpi_c, kpi_c]
"""
    assert "WARN-FLAT-COLS-UNSIZED-OVERFLOW" not in _warning_codes(yaml)


def test_flat_cols_mixed_row_counts_only_growable_cells() -> None:
    """5 growable bars trip the warning even alongside exempt KPIs."""
    yaml = f"""
{_QUERIES_AND_CHARTS}
cols: [bar_c, bar_c, bar_c, bar_c, bar_c, kpi_c, kpi_c]
"""
    result = compile(yaml)

    assert result.success, result.errors
    warnings = [
        w for w in result.warnings if w.code == "WARN-FLAT-COLS-UNSIZED-OVERFLOW"
    ]
    assert len(warnings) == 1
    assert "5 unsized" in warnings[0].message
