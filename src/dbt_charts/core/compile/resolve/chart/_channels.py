"""Channel classification and bar-orientation inference shared across cartesian resolvers."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from dbt_charts.core.compile.models.chart.normalized import (
    BarChart,
)
from dbt_charts.core.compile.models.chart.normalized._base import (
    _BaseChartFields,
)
from dbt_charts.core.compile.models.chart.resolved import (
    ResolvedStyleChannel,
)
from dbt_charts.core.compile.resolve.chart.channel import (
    normalize_chart_channels,
)
from dbt_charts.core.compile.resolve.chart.enrich import (
    classify_column_type,
    first_non_null_samples,
    is_column_discrete_for_bar_orientation,
)
from dbt_charts.core.utils import is_year_shaped

__all__ = [
    "_bar_orientation",
    "_channels_for",
    "_classify_to_channel_type",
]


def _channels_for(
    normalized: _BaseChartFields,
    data: list[dict[str, Any]],
) -> dict[str, ResolvedStyleChannel]:
    """Resolve channel bindings from normalized chart + data column names."""
    available = set(data[0].keys()) if data else set()
    # Pass style.color so normalize_chart_channels can upgrade the series channel
    # to gradient mode when color.gradient is set.
    # style is declared on every concrete chart model but not the _BaseChartFields
    # annotation, so read it structurally.
    style = getattr(normalized, "style", None)
    style_color = getattr(style, "color", None) if style is not None else None
    return normalize_chart_channels(normalized, available, style_color=style_color)


def _bar_orientation(
    normalized: BarChart,
    data: list[dict[str, Any]],
    bucketed_time: bool,
) -> Literal["vertical", "horizontal"] | None:
    """Resolve bar orientation: authored > bucketed-time > column-type inference > None.

    Priority:
    1. Authored orientation ("horizontal"/"vertical") from chart-local style.
    2. Overlay layers → vertical. The overlay renderer draws every layer with the
       measure on y (vertical), so a horizontal base would put its measure on x
       and desync from the overlays. A bar base with layers is always vertical.
    3. Bucketed time (``bucketed_time=True``, e.g. axis_x.time_unit set) → vertical.
       monthofyear-style buckets emit nominal-looking labels but ride a temporal
       scale, so they must not flip to horizontal.
    4. Column-type inference via is_column_discrete_for_bar_orientation (strict):
       categorical/string x → horizontal; numeric/temporal x → vertical.
    5. No data or no x → None (theme default, which is vertical).
    """
    authored = normalized.style.orientation if normalized.style is not None else None
    if authored in ("horizontal", "vertical"):
        return authored  # type: ignore[return-value]
    if normalized.layers:
        return "vertical"
    if bucketed_time:
        return "vertical"
    if not data or normalized.x is None:
        return None
    samples = first_non_null_samples(normalized.x, data)
    if not samples:
        return None
    return (
        "horizontal" if is_column_discrete_for_bar_orientation(samples) else "vertical"
    )


def _classify_to_channel_type(
    field: str | None, data: list[dict[str, Any]], is_dimension: bool
) -> str:
    """Map compile.enrich column classification to cascade channel_type.

    Returns "quantitative", "temporal", or "nominal" — the three values that
    resolved_axis_style dispatches on (ordinal/nominal both hit the band path).

    Strict: Python str values are never quantitative regardless of content.
    Only native int/float Python types qualify as quantitative — the database
    returned those types, so the DB declared this column numeric.

    ``is_dimension`` gates the year-shape check to dimension/x callers only —
    a measure is never a year, so a scatter y (or any other measure channel)
    must pass ``is_dimension=False`` and stay quantitative even when its
    values happen to fall in the year range.
    """
    if not field or not data:
        return "nominal"
    samples = first_non_null_samples(field, data)
    if not samples:
        return "nominal"
    # Year-shaped INTEGER/VARCHAR x bakes the same band/temporal axis-style
    # cascade as a genuine DATE column — otherwise the quantitative-axis SI
    # suffix default (.3~s) leaks onto year ticks even though orientation and
    # vl_type already agree the column is continuous-temporal.
    if is_dimension and is_year_shaped(samples):
        return "temporal"
    # Native numeric check first — str "123" is not quantitative.
    if all(
        isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)
        for v in samples
    ):
        return "quantitative"
    ct = classify_column_type(field, samples)
    return "temporal" if ct == "temporal" else "nominal"
