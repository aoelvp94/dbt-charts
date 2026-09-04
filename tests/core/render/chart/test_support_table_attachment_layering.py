"""Boundary smoke test: support_table VL emission lives render-side.

``attach_support_table`` builds Vega-Lite spec fragments for the
``chart.support_table`` attachment — a render concern (translating a resolved
dbt charts value into a foreign target's vocabulary). It must be importable
from ``render.chart``, not ``compile``.
"""

from dbt_charts.core.render.chart.support_table_attachment import attach_support_table


def test_attach_support_table_importable_from_render_chart() -> None:
    assert callable(attach_support_table)
