"""Authored point_map / bubble_map chart."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from dbt_charts.core.compile.models.markers import Channel
from dbt_charts.core.compile.models.style.authored import PointMapChartStylePatch

from ._base import BasemapConfig, _GeoChartFields


class PointMapChart(_GeoChartFields):
    """Authored patch for point_map and bubble_map charts; the two type spellings are synonyms."""

    model_config = ConfigDict(extra="forbid")

    type: Annotated[
        Literal["point_map", "bubble_map"],
        Field(description="Selects the chart family."),
    ]
    # None = lat/lon not specified. point_map/bubble_map-only: geoshape has no
    # render support for them, so they live here rather than on the shared
    # _GeoChartFields base — extra="forbid" rejects them on geoshape for free.
    latitude: Annotated[
        str | None,
        Channel(),
        Field(
            default=None,
            description="Column containing latitude values for point/bubble maps.",
        ),
    ]
    longitude: Annotated[
        str | None,
        Channel(),
        Field(
            default=None,
            description="Column containing longitude values for point/bubble maps.",
        ),
    ]
    # None = no size encoding; bubbles use a fixed radius.
    size: Annotated[
        str | None,
        Channel(),
        Field(
            default=None,
            description="Quantitative column that scales point area. Mutually exclusive with `collapse`.",
        ),
    ]
    # Opt-in aggregation: collapses marks sharing an exact latitude/longitude
    # into one mark sized by count (area-proportional). Mutually exclusive
    # with `size` — both bind the mark's size channel. Never a silent default;
    # the render-time co-located-marks warning is the automatic half of this
    # affordance pair.
    collapse: Annotated[
        bool,
        Field(
            default=False,
            description="Collapse marks sharing an exact latitude/longitude into one mark sized by count. Mutually exclusive with `size` and with any color channel.",
        ),
    ]
    basemap: Annotated[
        BasemapConfig | None,
        Field(default=None, description="Styled geographic background layer."),
    ]
    style: Annotated[
        PointMapChartStylePatch | None,
        Field(default=None, description="Appearance overrides for this chart alone."),
    ]

    @model_validator(mode="after")
    def _reject_collapse_with_size(self) -> PointMapChart:
        if self.collapse and self.size is not None:
            raise ValueError(
                f"{self.type}: `collapse: true` and `size: <column>` both bind "
                "the mark's size channel — they cannot be combined. Drop `size` "
                "to size collapsed points by count, or drop `collapse` to keep "
                "`size` as a bubble_map measure encoding."
            )
        return self

    @model_validator(mode="after")
    def _reject_collapse_with_color(self) -> PointMapChart:
        """Refuse `collapse` alongside a field-mode `color`.

        `collapse` emits VL's native `size: {aggregate: "count"}`, which VL
        groups by every other non-aggregated encoded field. Field-mode
        `color` widens that groupby to (lat, lon, category) — re-creating
        the exact pile `collapse` exists to remove.
        """
        if not self.collapse:
            return self
        sql_resolution = (
            "aggregate per-category counts in SQL (`GROUP BY <lat>, <lon>, "
            "<category>` producing a count column), then use `bubble_map` "
            "with `size: <count column>, color: <category column>`."
        )
        if self.color is not None:
            raise ValueError(
                f"{self.type}: `collapse: true` and `color: <column>` cannot be "
                "combined — VL's size:{aggregate: count} groups by every "
                "other non-aggregated encoded field, so an authored `color` "
                "reintroduces the exact pile `collapse` exists to remove. "
                f"Drop `color` to keep collapsed counts, or drop `collapse` "
                f"and {sql_resolution}"
            )
        return self
