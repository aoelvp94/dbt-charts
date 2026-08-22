"""Authored point_map / bubble_map chart."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from dbt_charts.core.compile.models.markers import Channel
from dbt_charts.core.compile.models.style.authored import PointMapChartStylePatch

from ._base import BasemapConfig, _ConditionalFormattingField, _GeoChartFields


class PointMapChart(_GeoChartFields, _ConditionalFormattingField):
    """Authored patch for point_map and bubble_map charts."""

    model_config = ConfigDict(extra="forbid")

    type: Annotated[
        Literal["point_map", "bubble_map"],
        Field(description="Point map or bubble map chart type."),
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
            description="Data column used to scale bubble radius (quantitative). Only meaningful on bubble_map.",
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
        Field(default=None, description="Chart-local style overrides."),
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
        """Refuse `collapse` alongside either color mode.

        `collapse` emits VL's native `size: {aggregate: "count"}`, which VL
        groups by every other non-aggregated encoded field. Field-mode
        `color` widens that groupby to (lat, lon, category) — re-creating
        the exact pile `collapse` exists to remove. Conditional-mode color
        compiles to `datum["<col>"] > x`, but the aggregated mark carries
        only the groupby fields plus the count, so the field is undefined
        and every rule silently evaluates false.
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
        if self.conditional_formatting is not None:
            drives_color = any(
                rule.background is not None
                for entry in self.conditional_formatting.values()
                for rule in entry.when
            )
            if drives_color:
                raise ValueError(
                    f"{self.type}: `collapse: true` with `conditional_formatting` "
                    "driving color cannot be combined — the aggregated mark "
                    "datum carries only the groupby fields plus the count, so "
                    "every rule test evaluates false and the color channel "
                    "goes inert. Drop the color-driving `conditional_formatting` "
                    f"rules to keep collapsed counts, or drop `collapse` and "
                    f"{sql_resolution}"
                )
        return self
