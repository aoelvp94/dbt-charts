"""End-to-end: FACET_PANEL_WIDTH_BELOW_MINIMUM surfaces from render() for a
small-multiples chart whose column-facet cardinality shrinks each panel
below the legibility floor.

Proves the full seam — compile -> render() -> RenderResult.warnings — not a
hand-built WarningContext. A hand-built context can pass while the real
pipeline never produces the faceted spec shape the detector reads.

This is also the regression pin for `facet_panel_width()`'s floor bug: before
the fix, `usable = max(width - chrome, min_panel_px * panel_cols)` let the
floor win over the card boundary and the facet painted past its declared box
instead of shrinking below the floor and firing this warning.
"""

from __future__ import annotations

from unittest.mock import Mock

from dbt_charts.core.compile import compile
from dbt_charts.core.execute import Executor
from dbt_charts.core.render import render

_CODE = "WARN-FACET-PANEL-WIDTH-BELOW-MINIMUM"


def _rows(n_groups: int) -> list[dict[str, object]]:
    return [
        {"grp": f"g{g:02d}", "cat": f"c{i:02d}", "val": i + 1}
        for g in range(n_groups)
        for i in range(3)
    ]


def _make_executor(
    board: object, query_registry: object, rows: list[dict[str, object]]
):
    ok = Mock()
    ok.is_success = True
    ok.data = rows
    ok.column_descriptions = None
    ok.resolved_relations = None
    ok.truncated_reason = None
    mock_registry = Mock()
    mock_registry.execute.return_value = ok
    return Executor(
        board, adapter_registry=mock_registry, query_registry=query_registry
    )


def _board_yaml(*, width: int) -> str:
    return f"""
title: Probe
charts:
  facet_bar:
    query: q
    type: bar
    x: cat
    y: val
    multiples:
      columns: grp
queries:
  q:
    sql: SELECT * FROM t
    source: test_source
rows:
  - cols:
      - width: {width}
        rows:
          - facet_bar
"""


def _render(yaml_source: str, n_groups: int) -> list[object]:
    result = compile(yaml_source)
    assert result.success and result.board is not None, result.errors
    executor = _make_executor(result.board, result.query_registry, _rows(n_groups))
    render_result = render(result.board, executor, format="svg")
    return list(render_result.warnings)


def test_fires_when_the_card_is_too_narrow_for_the_panel_count() -> None:
    """3 column panels in a 200px card: (200 - 120px chrome) / 3 = 26.7px —
    well under the 120px floor."""
    warnings = _render(_board_yaml(width=200), n_groups=3)
    codes = {w.code for w in warnings}
    assert _CODE in codes, codes
    w = next(w for w in warnings if w.code == _CODE)
    assert w.chart == "facet_bar"
    assert "3" in w.message
    assert w.fix


def test_silent_when_the_card_comfortably_fits_the_panel_count() -> None:
    """3 column panels in a 1800px card: (1800 - 120) / 3 = 560px — far above
    the floor."""
    warnings = _render(_board_yaml(width=1800), n_groups=3)
    codes = {w.code for w in warnings}
    assert _CODE not in codes


def test_silent_when_the_chart_is_not_faceted() -> None:
    yaml_source = """
title: Probe
charts:
  plain_bar:
    query: q
    type: bar
    x: cat
    y: val
queries:
  q:
    sql: SELECT * FROM t
    source: test_source
rows:
  - cols:
      - width: 200
        rows:
          - plain_bar
"""
    warnings = _render(yaml_source, n_groups=3)
    codes = {w.code for w in warnings}
    assert _CODE not in codes
