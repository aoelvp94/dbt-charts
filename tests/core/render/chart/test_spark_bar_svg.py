"""spark_bar SVG regression guard: render output must stay byte-identical.

spark_bar is a typed SVG renderer (not a VL emitter). Both sides resolve
from the SAME authored fixture through the real pipeline —
``normalize_chart → resolve()`` — so this test exercises
``_resolve_spark_bar`` and ``normalize_chart`` for real, not a
hand-constructed ``ResolvedSparkBarChart``. See ``test_render_parity.py``
for the same pattern applied to VL families.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from dbt_charts.core.compile.config import get_default_theme_name, get_theme_style
from dbt_charts.core.compile.models.query.normalized import ValuesQuery
from dbt_charts.core.compile.normalize.charts import normalize_chart
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style,
)
from dbt_charts.core.render.chart.spark_bar import render_spark_bar_svg

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "parity"
_BOARD_STYLE = resolve_style(get_theme_style(get_default_theme_name()))
_CHART_CTX = resolve_chart_style_context(get_theme_style(get_default_theme_name()))


def _load_fixture(
    path: Path,
) -> tuple[str, dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Load a parity fixture YAML. Returns (chart_id, chart_def, query_registry, data)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    chart_id: str = raw["chart_id"]
    chart_def: dict[str, Any] = raw["chart"]

    query_registry: dict[str, Any] = {}
    for qname, qdef in (raw.get("queries") or {}).items():
        query_registry[qname] = ValuesQuery(
            columns=qdef.get("columns"),
            values=qdef.get("values"),
            rows=qdef.get("rows") or [],
        )

    query_name: str = chart_def.get("query") or next(iter(query_registry))
    data: list[dict[str, Any]] = query_registry[query_name].rows
    return chart_id, chart_def, query_registry, data


def _v1_svg(
    chart_id: str,
    chart_def: dict[str, Any],
    query_registry: dict[str, Any],
    data: list[dict[str, Any]],
    *,
    is_placeholder: bool = False,
) -> str:
    """Reference path: authored dict → normalize_chart → resolve() →
    render_spark_bar_svg."""
    flat = normalize_chart(chart_id, chart_def, query_registry, sources={})
    resolved = resolve(flat, data, chart_style_context=_CHART_CTX)
    return render_spark_bar_svg(
        resolved, data, is_placeholder=is_placeholder, board_style=_BOARD_STYLE
    )


def _v2_svg(
    chart_id: str,
    chart_def: dict[str, Any],
    query_registry: dict[str, Any],
    data: list[dict[str, Any]],
    *,
    is_placeholder: bool = False,
) -> str:
    """V2: authored dict → normalize_chart → resolve() → render_spark_bar_svg."""
    from dbt_charts.core.compile.models.chart.resolved.spark_bar import (
        ResolvedSparkBarChart,
    )

    compiled = normalize_chart(chart_id, chart_def, query_registry, sources={})
    resolved = resolve(compiled, data, chart_style_context=_CHART_CTX)
    assert isinstance(resolved, ResolvedSparkBarChart)
    return render_spark_bar_svg(
        resolved, data, is_placeholder=is_placeholder, board_style=_BOARD_STYLE
    )


@pytest.mark.parametrize(
    "fixture_name",
    [
        "spark_bar",  # explicit x/y, title
        "spark_bar_auto",  # auto-detected x/y, no title
        "spark_bar_truncated",  # more rows than max_bars -> "+N more" indicator
    ],
)
def test_v2_spark_bar_byte_identical(fixture_name: str) -> None:
    """v2 spark_bar SVG (via real resolve()) must be byte-identical to v1."""
    chart_id, chart_def, query_registry, data = _load_fixture(
        _FIXTURE_DIR / f"{fixture_name}.yml"
    )

    v1_svg = _v1_svg(chart_id, chart_def, query_registry, data)
    v2_svg = _v2_svg(chart_id, chart_def, query_registry, data)

    assert v2_svg == v1_svg


def test_v2_spark_bar_byte_identical_placeholder() -> None:
    """Placeholder-mode v2 output (via real resolve()) matches v1 byte-for-byte."""
    chart_id, chart_def, query_registry, data = _load_fixture(
        _FIXTURE_DIR / "spark_bar.yml"
    )

    v1_svg = _v1_svg(chart_id, chart_def, query_registry, data, is_placeholder=True)
    v2_svg = _v2_svg(chart_id, chart_def, query_registry, data, is_placeholder=True)

    assert v2_svg == v1_svg
