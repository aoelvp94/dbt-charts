"""LAYER PATCH — per-layer authored input for layered charts."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dbt_charts.core.compile.models.markers import Format
from dbt_charts.core.compile.models.schema_names import FormatAlias


class LayerAxisYScale(BaseModel):
    """Per-layer y-axis scale patch."""

    model_config = ConfigDict(extra="forbid")

    domain: list[float] | None = Field(
        default=None, description="Explicit [min, max] domain for this layer's y scale."
    )


class LayerAxisYTicks(BaseModel):
    """Per-layer y-axis tick patch."""

    model_config = ConfigDict(extra="forbid")

    count: int | None = Field(
        default=None, description="Requested number of y-axis ticks for this layer."
    )


class LayerAxisYGrid(BaseModel):
    """Per-layer y-axis grid patch."""

    model_config = ConfigDict(extra="forbid")

    visible: bool | None = Field(
        default=None, description="Whether to show grid lines on this layer's y axis."
    )


class LayerAxisYLabel(BaseModel):
    """Per-layer y-axis label format patch."""

    model_config = ConfigDict(extra="forbid")

    format: Annotated[FormatAlias | str | None, Format()] = Field(
        default=None,
        description="d3 format string for this layer's y-axis tick labels.",
    )


class LayerAxisYStyle(BaseModel):
    """Per-layer y-axis settings on a layered chart."""

    model_config = ConfigDict(extra="forbid")

    position: Literal["left", "right"] | None = Field(
        default=None, description="Y-axis side for this layer (left or right)."
    )
    title: str | None = Field(
        default=None, description="Y-axis title override for this layer."
    )
    scale: LayerAxisYScale | None = Field(
        default=None, description="Scale overrides for this layer's y axis."
    )
    ticks: LayerAxisYTicks | None = Field(
        default=None, description="Tick overrides for this layer's y axis."
    )
    grid: LayerAxisYGrid | None = Field(
        default=None, description="Grid overrides for this layer's y axis."
    )
    label: LayerAxisYLabel | None = Field(
        default=None, description="Label format override for this layer's y axis."
    )


# ── typed layer union (BarLayer / LineLayer / AreaLayer / ScatterLayer) ────────
#
# Each typed layer carries its own marks-group style so per-layer style fields
# are validated against the correct family's mark patches at authored time.
# Validators are shared via TypedLayerBase.

from dbt_charts.core.compile.models.style.authored._base import (
    AreaLayerStylePatch,
    BarLayerStylePatch,
    LineLayerStylePatch,
    ScatterLayerStylePatch,
)


class TypedLayerBase(BaseModel):
    """Common identity fields and validators shared by all typed layer variants."""

    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(
        default=None,
        description="Query name for this layer's data (overrides chart-level query).",
    )
    x: str | None = Field(
        default=None, description="X-axis column name for this layer."
    )
    y: str | None = Field(
        default=None, description="Y-axis column name for this layer."
    )
    label: str | None = Field(
        default=None, description="Label column name for this layer."
    )
    color: str | None = Field(
        default=None,
        description="Color data channel for this layer: bare column name only.",
    )
    axis_y: LayerAxisYStyle | None = Field(
        default=None, description="Y-axis settings for this layer (orientation, title)."
    )

    @field_validator("color", mode="before")
    @classmethod
    def _reject_non_column_color(cls, v: Any) -> Any:
        if isinstance(v, str) and v.startswith("#"):
            raise ValueError(
                "Layer.color is a data channel (bare field name only). Paint "
                f"belongs under the layer's `style.marks`, and '{v}' should be "
                "a palette token there (`category[1]`, `negative.solid`) — the "
                "mark key differs per layer type, so see `dct docs charts`."
            )
        if isinstance(v, dict):
            raise ValueError(
                "Layer.color only accepts a bare field name (string). "
                "Dicts (value, scale, when forms) are not supported on layers."
            )
        return v

    @model_validator(mode="before")
    @classmethod
    def _reject_vl_passthrough_fields(cls, data: Any) -> Any:
        if isinstance(data, dict) and "encoding" in data:
            raise ValueError(
                "`encoding` is not part of the authored Dataface layer surface. "
                "Use typed layer channels (`color`) instead."
            )
        return data


class BarLayer(TypedLayerBase):
    """A bar-type layer on a cartesian chart."""

    type: Annotated[Literal["bar"], Field(description="Bar mark layer.")]
    style: Annotated[
        BarLayerStylePatch | None,
        Field(default=None, description="Bar layer mark style overrides."),
    ] = None


class LineLayer(TypedLayerBase):
    """A line-type layer on a cartesian chart."""

    type: Annotated[Literal["line"], Field(description="Line mark layer.")]
    style: Annotated[
        LineLayerStylePatch | None,
        Field(default=None, description="Line layer mark style overrides."),
    ] = None


class AreaLayer(TypedLayerBase):
    """An area-type layer on a cartesian chart."""

    type: Annotated[Literal["area"], Field(description="Area mark layer.")]
    style: Annotated[
        AreaLayerStylePatch | None,
        Field(default=None, description="Area layer mark style overrides."),
    ] = None


class ScatterLayer(TypedLayerBase):
    """A scatter-type layer on a cartesian chart."""

    type: Annotated[
        Literal["scatter"], Field(description="Scatter (point) mark layer.")
    ]
    style: Annotated[
        ScatterLayerStylePatch | None,
        Field(default=None, description="Scatter layer mark style overrides."),
    ] = None


# Discriminated union for the typed layer list on cartesian charts.
# Field(discriminator="type") lets Pydantic pick the right class from the
# `type` key before validating the rest of the fields.
CartesianLayer = Annotated[
    BarLayer | LineLayer | AreaLayer | ScatterLayer,
    Field(discriminator="type"),
]
