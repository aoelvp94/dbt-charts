"""Regression: FontStylePatch renamed to FontStyle.

These imports fail before the rename (ImportError) and pass after.
"""

from dbt_charts.core.compile.models.chart.authored import BarLayer
from dbt_charts.core.compile.models.primitives import FontStyle


def test_font_style_importable() -> None:
    """FontStyle (née FontStylePatch) must be importable from primitives."""
    f = FontStyle(family="Inter", size=14.0)
    assert f.family == "Inter"
    assert f.size == 14.0


def test_bar_layer_importable() -> None:
    """BarLayer must be importable from chart.authored."""
    layer = BarLayer(type="bar", y="revenue")
    assert layer.type == "bar"
    assert layer.y == "revenue"
