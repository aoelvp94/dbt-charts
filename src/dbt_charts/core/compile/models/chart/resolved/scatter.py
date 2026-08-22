"""Resolved scatter chart model."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from dbt_charts.core.compile.models.chart.resolved._layer import ResolvedLayer
from dbt_charts.core.compile.models.style.resolved import ResolvedScatterStyle

from ._base import _CartesianResolvedChartFields


class ResolvedScatterChart(_CartesianResolvedChartFields):
    """Render-ready scatter chart."""

    # Narrows base y from str | list[str] | None to str | None — scatter has
    # no fold/multi-measure render path, unlike heatmap (which keeps the
    # base's wider type for its real one-rect-layer-per-measure path).
    y: str | None = Field(default=None, description="Y-axis data column.")
    chart_type: Literal["scatter"] = Field(
        description="Discriminator key; always 'scatter'.",
    )
    size: str | None = Field(
        default=None,
        description="Data column driving point size.",
    )
    shape: str | None = Field(
        default=None,
        description="Data column driving point shape.",
    )
    style: ResolvedScatterStyle = Field(
        description="Scatter family style slice.",
    )
    layers: tuple[ResolvedLayer, ...] = Field(
        default=(),
        description="Typed overlay layers, each carrying its own resolved mark style.",
    )
