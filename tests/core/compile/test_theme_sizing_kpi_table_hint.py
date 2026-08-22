"""Tests for the actionable error hint on theme-level sizing fields for kpi/table.

``style.charts.kpi.aspect_ratio`` / ``min_height`` / ``max_height`` and the
equivalent ``style.charts.table.*`` fields were never part of the declared
KpiChartStylePatch / TableChartStylePatch schema. A @cache-divergence bug in
the old pipeline accidentally accepted them. The fix closes that hole and
provides a clear compile-time hint naming the field, explaining the fixed
sizing contract, and directing the author to remove it.

These paths cannot be expressed as a Deletion (no structural schema history
to migrate from), so there is no ``dct migrate`` path -- only fail-loud.

Coverage includes meta.yaml and extends fragment paths — the hint must reach
authors regardless of where the invalid field is authored.
"""

from __future__ import annotations

from pathlib import Path

from dbt_charts.core.compile.compiler import compile as compile_board, compile_file


def _theme_board_kpi_min_height() -> str:
    return """
title: T
queries:
  q:
    source: db
    sql: SELECT 100 AS revenue
charts:
  k:
    type: kpi
    query: q
    value: revenue
rows:
  - k
style:
  charts:
    kpi:
      min_height: 200
"""


def _theme_board_table_aspect_ratio() -> str:
    return """
title: T
queries:
  q:
    source: db
    sql: SELECT 1 AS a
charts:
  t:
    type: table
    query: q
    columns: [a]
rows:
  - t
style:
  charts:
    table:
      aspect_ratio: 1.5
"""


def test_theme_kpi_min_height_raises_with_hint() -> None:
    """style.charts.kpi.min_height raises with a hint naming the field and fix."""
    result = compile_board(_theme_board_kpi_min_height())

    assert not result.success
    all_text = " ".join((e.message or "") + " " + (e.hint or "") for e in result.errors)
    assert "kpi" in all_text
    assert "min_height" in all_text
    assert "remove" in all_text.lower()


def test_theme_table_aspect_ratio_raises_with_hint() -> None:
    """style.charts.table.aspect_ratio raises with a hint naming the field and fix."""
    result = compile_board(_theme_board_table_aspect_ratio())

    assert not result.success
    all_text = " ".join((e.message or "") + " " + (e.hint or "") for e in result.errors)
    assert "table" in all_text
    assert "aspect_ratio" in all_text
    assert "remove" in all_text.lower()


# ---------------------------------------------------------------------------
# Regression: same hints must fire when the invalid field is in meta.yaml or
# in an extends fragment — the compiler must not swallow them as ERR-INTERNAL.
# ---------------------------------------------------------------------------

_VALID_KPI_BOARD = """\
title: T
queries:
  q:
    source: db
    sql: SELECT 100 AS revenue
charts:
  k:
    type: kpi
    query: q
    value: revenue
rows:
  - k
"""

_META_WITH_KPI_MIN_HEIGHT = """\
style:
  charts:
    kpi:
      min_height: 200
"""

_EXTENDS_FRAGMENT_WITH_TABLE_ASPECT_RATIO = """\
style:
  charts:
    table:
      aspect_ratio: 1.5
"""


def test_meta_yaml_kpi_sizing_hint(in_memory_project: type) -> None:
    """style.charts.kpi.min_height in meta.yaml raises with a hint, not ERR-INTERNAL."""
    project = in_memory_project(
        Path("/tmp/test"),
        {
            "charts/board.yml": _VALID_KPI_BOARD,
            "charts/meta.yaml": _META_WITH_KPI_MIN_HEIGHT,
        },
    )
    result = compile_file(project.path("charts/board.yml").read_board())

    assert not result.success
    # The hint (not ERR-INTERNAL) must reach the caller.
    all_text = " ".join((e.message or "") + " " + (e.hint or "") for e in result.errors)
    assert "kpi" in all_text
    assert "min_height" in all_text
    assert "remove" in all_text.lower()
    # The error must point at the fragment file, not at the board.
    assert result.errors[0].range is not None
    assert result.errors[0].range.file == "charts/meta.yaml"


def test_extends_fragment_table_sizing_hint(in_memory_project: type) -> None:
    """style.charts.table.aspect_ratio in an extends fragment raises with a hint, not ERR-INTERNAL."""
    board_yaml = (
        _VALID_KPI_BOARD.replace(
            "type: kpi\n    query: q\n    value: revenue",
            "type: table\n    query: q\n    columns: [revenue]",
        )
        + "extends:\n  - ./_style_base.yml\n"
    )
    project = in_memory_project(
        Path("/tmp/test"),
        {
            "charts/board.yml": board_yaml,
            "charts/_style_base.yml": _EXTENDS_FRAGMENT_WITH_TABLE_ASPECT_RATIO,
        },
    )
    result = compile_file(project.path("charts/board.yml").read_board())

    assert not result.success
    all_text = " ".join((e.message or "") + " " + (e.hint or "") for e in result.errors)
    assert "table" in all_text
    assert "aspect_ratio" in all_text
    assert "remove" in all_text.lower()
    # The error must point at the fragment file, not at the board.
    assert result.errors[0].range is not None
    assert result.errors[0].range.file == "charts/_style_base.yml"
