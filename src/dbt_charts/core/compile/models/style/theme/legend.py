"""Theme-stage style classes: legend."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from dbt_charts.core.compile.models.markers import (
    InheritSlot,
    Merge,
    Strategy,
)
from dbt_charts.core.compile.models.primitives import (
    FontStyle,
)

# Vega-Lite legend orient values (encoding.color.legend.orient), minus VL's
# own "none" — that value means "no automatic placement, position me with
# legendX/legendY", which with no coordinates floats the legend inside the
# plot. Nothing here sets those coordinates, and an author spelling "none"
# means "no legend": that is `legend.visible: false`.
# Ref: https://vega.github.io/vega-lite/docs/legend.html
LegendPosition = Literal[
    "left",
    "right",
    "top",
    "bottom",
    "top-left",
    "top-right",
    "bottom-left",
    "bottom-right",
]
# Vega-Lite legend direction values (encoding.color.legend.direction).
LegendDirection = Literal["horizontal", "vertical"]


class LegendElementStyle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    font: Annotated[FontStyle, InheritSlot(from_path="Style.charts.font")] = Field(
        default_factory=FontStyle,
        description="Legend element font style overrides.",
    )
    padding: float = Field(
        description="Padding between legend symbol and element text in pixels."
    )


class LegendLabelStyle(LegendElementStyle):
    max_width: float | None = Field(
        default=None,
        description="Maximum label width in pixels; maps to VL labelLimit. None uses Vega-Lite's default.",
    )


class LegendTitleStyle(LegendElementStyle):
    visible: bool | None = Field(
        default=None,
        description="Show the legend title; None = shown, False = suppressed (VL legend.title: null).",
    )


class LegendStyle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    position: LegendPosition = Field(description="Legend position (VL legend orient).")
    direction: LegendDirection = Field(description="Legend layout direction.")
    columns: int = Field(
        ge=0,
        description=(
            "Legend entry columns. Zero keeps the renderer default; positive values "
            "set Vega-Lite legend columns."
        ),
    )
    compact_columns: int = Field(
        ge=1,
        description="Entry columns for an automatic compact top-horizontal legend.",
    )
    label: LegendLabelStyle = Field(description="Legend label style.")
    title: LegendTitleStyle = Field(description="Legend title style.")
    visible: bool | None = Field(
        default=None,
        description="Show the legend. None = legend visible; False = explicitly suppressed.",
    )
    symbol_limit: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Maximum number of legend entries to display; maps to VL symbolLimit. "
            "None uses Vega-Lite's default (no cap). "
            "Set to a positive integer to prevent legend overflow on high-cardinality series."
        ),
    )
    # Cascade tier sentinel: None means "not specified at this tier"; the render
    # layer infers entry order from the color scale domain (data + layer order).
    # Authored as a list to pin/reorder legend entries explicitly (maps to VL
    # legend.values). No theme default — ordering is an author decision.
    values: Annotated[list[str] | None, Merge(Strategy.OVERRIDE)] = Field(
        default=None,
        description=(
            "Explicit legend entry order/filter; maps to VL legend.values. "
            "None lets the renderer infer order from the data."
        ),
    )
    # Author override for the legend glyph shape (VL symbolType). None means
    # "let the renderer pick the mark-aware glyph"; a string (e.g. 'stroke',
    # 'square', 'diamond') emits a constant symbolType that wins over the
    # mark-derived Vega expression. No theme default.
    symbol_shape: str | None = Field(
        default=None,
        description=(
            "Override the legend glyph shape; maps to VL legend.symbolType. "
            "None uses the mark-aware glyph derived from the chart's mark type."
        ),
    )
    # Author override for symbol fill. False → symbolFillColor='transparent'
    # in the emitted VL legend, which makes hollow (stroke-only) glyphs. None
    # means "use Vega-Lite's default" (filled). No theme default.
    symbol_fill: bool | None = Field(
        default=None,
        description=(
            "When False, emits symbolFillColor='transparent' to produce a hollow "
            "legend glyph. None uses Vega-Lite's default (filled symbol)."
        ),
    )
