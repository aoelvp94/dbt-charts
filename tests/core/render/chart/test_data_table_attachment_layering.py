"""Boundary smoke test: data_table VL emission lives render-side.

``attach_data_table`` builds Vega-Lite spec fragments for the
``chart.data_table`` attachment — a render concern (translating a resolved
Dataface value into a foreign target's vocabulary). It must be importable
from ``render.chart``, not ``compile``.
"""

from dbt_charts.core.render.chart.data_table_attachment import attach_data_table


def test_attach_data_table_importable_from_render_chart() -> None:
    assert callable(attach_data_table)
