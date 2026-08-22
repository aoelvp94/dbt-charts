"""Theme-stage style classes: chart-family style base class hierarchy."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

if TYPE_CHECKING:
    # These authored types are injected into theme/__init__.py's module globals at
    # runtime by dbt_charts.core.compile.models.style.authored (after authored.py
    # finishes executing). The import here is TYPE_CHECKING-only to give mypy and
    # ruff the static definitions they need without creating a circular import.
    from dbt_charts.core.compile.models.style.authored import (  # noqa: PLC0415
        AxisXStylePatch,
        AxisYStylePatch,
        BandAxisStylePatch,
        BaseAxisStylePatch,
        DataTableStylePatch,
        QuantitativeAxisStylePatch,
    )

from pydantic import BaseModel, ConfigDict, Field

from dbt_charts.core.compile.models.factories import (
    build_patch_model_ext,
)
from dbt_charts.core.compile.models.markers import (
    Color,
    Format,
    Inherit,
    InheritSlot,
    SkipInheritSlots,
)
from dbt_charts.core.compile.models.primitives import (
    BorderStyle,
    ColorStyle,
    FontStyle,
    StaticGradientColorStyle,
)
from dbt_charts.core.compile.models.schema_names import FormatAlias
from dbt_charts.core.compile.models.style.theme.board import (
    PaddingStyle,
    TitleStyle,
)
from dbt_charts.core.compile.models.style.theme.legend import (
    LegendStyle,
)
from dbt_charts.core.compile.models.style.theme.marks import (
    BasemapStyle,
    ProjectionStyle,
    TotalStyle,
)


class _ChartStyleBase(BaseModel):
    """Required geometry/frame fields — the cascade source for all chart families.

    ``ChartsStyle`` inherits this class to supply the authoritative global values.
    ``_ChartStyleBaseAllOptional`` (generated via ``build_patch_model``) is used as
    the per-family base for kpi/table, where ``None`` on any field means "inherit from
    ``ChartsStyle`` via the cascade".  Painting families inherit
    ``_PaintedChartStyleBaseAllOptional`` instead, which additionally carries
    ``legend`` and the three sizing fields.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    font: FontStyle = Field(
        default_factory=FontStyle,
        description="Chart-level font overrides.",
    )
    preferred_width: Annotated[
        float, Inherit(from_path="Style.charts.preferred_width")
    ] = Field(description="Preferred chart width in pixels.")
    # InheritSlot: per-family padding inherits per-side from Style.charts.padding.
    # ChartsStyle (the board-level slot) overrides this with SkipInheritSlots to
    # break the self-loop the InheritSlot would otherwise create at the top of
    # the chain.
    padding: Annotated[PaddingStyle, InheritSlot(from_path="Style.charts.padding")] = (
        Field(description="Per-chart-type padding override; 4 sides in pixels.")
    )
    border: BorderStyle = Field(description="Chart card border style.")

    # Cascade-managed sentinels — chart-local paint and typography overrides.
    # None propagates unchanged through the cascade; no theme-level default
    # exists for these per-chart fields. ChartsStyle inherits these as optional
    # fields that theme YAML may omit.
    background: Annotated[str | None, Color()] = Field(
        default=None,
        description="Chart-local background color override; None inherits from theme.",
    )
    # Unified color config: static ink, categorical palette, and gradient scale.
    # Required at ChartsStyle level (theme must supply color.categorical).
    # Per-family patches (derived via build_patch_model_ext) get ColorStyle | None.
    # No Merge marker: ColorStyle is a BaseModel, so merge_patches uses Strategy.DEEP by
    # default. This lets theme patches contribute individual color sub-fields
    # (e.g. one layer sets categorical.palette, another sets categorical.single_series_palette)
    # without the later layer wiping out the earlier one.
    color: ColorStyle = Field(
        description="Chart color: static mark paint, categorical palette, and/or gradient scale."
    )
    title: Annotated[TitleStyle | None, SkipInheritSlots()] = Field(
        default=None,
        description="Chart-level title style override; None inherits the theme title style.",
    )


if TYPE_CHECKING:

    class _ChartStyleBaseAllOptional(_ChartStyleBase):
        # At runtime build_patch_model_ext makes every _ChartStyleBase field Optional;
        # declare color | None so callers on _ChartStyleBaseAllOptional subclasses
        # know they must guard before accessing .static/.gradient.
        # The assignment is narrowing (ColorStyle → ColorStyle | None) — intentional.
        color: ColorStyle | None  # type: ignore[assignment]

else:
    _ChartStyleBaseAllOptional = build_patch_model_ext(
        _ChartStyleBase, is_recursive=True
    )


class _PaintedChartStyleBase(_ChartStyleBase):
    """Fields for families with their own geometry and a legend: cartesian, radial, and geo.

    KPI and table use a fixed sizing contract and paint no legend — they inherit
    ``_ChartStyleBaseAllOptional`` directly, so ``extra="forbid"`` rejects these
    fields structurally.  No family (including these nine) declares ``tooltip`` at
    the per-family level — the only authoritative tooltip slot is ``ChartsStyle.tooltip``
    (global, board-wide), which is how every real tooltip consumer reads it.
    """

    # Inherit markers on scalars: picked up by build_patch_model_ext and forwarded
    # to _PaintedChartStyleBaseAllOptional so per-family None sentinels resolve from ChartsStyle.
    aspect_ratio: Annotated[float, Inherit(from_path="Style.charts.aspect_ratio")] = (
        Field(description="Chart aspect ratio (width/height).")
    )
    min_height: Annotated[float, Inherit(from_path="Style.charts.min_height")] = Field(
        description="Minimum chart height in pixels."
    )
    max_height: Annotated[float, Inherit(from_path="Style.charts.max_height")] = Field(
        description="Maximum chart height in pixels."
    )
    legend: LegendStyle = Field(description="Chart legend style.")


if TYPE_CHECKING:

    class _PaintedChartStyleBaseAllOptional(_PaintedChartStyleBase):
        # At runtime build_patch_model_ext makes every _PaintedChartStyleBase field Optional;
        # declare color | None so callers on _PaintedChartStyleBaseAllOptional subclasses
        # know they must guard before accessing .static/.gradient.
        # The assignment is narrowing (ColorStyle → ColorStyle | None) — intentional.
        color: ColorStyle | None  # type: ignore[assignment]

else:
    _PaintedChartStyleBaseAllOptional = build_patch_model_ext(
        _PaintedChartStyleBase, is_recursive=True
    )


class _CartesianChartStyle(_PaintedChartStyleBaseAllOptional):
    """Cartesian families: bar, line, area, scatter, histogram, heatmap.

    Shared axis tier — theme YAML populates per-family axis overrides here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # SkipInheritSlots: per-family axis overrides are sparse patches — only the
    # fields a theme explicitly authors for the family are set; every other field
    # inherits the global axis at render time via resolved_axis_style's merge over
    # the fully-resolved base axis. Without this, apply_inherit slot-fills these
    # patches from the generic charts.font (prose ink) — so merely authoring an
    # unrelated field like bar.axis_x.labels.padding materializes labels.font and
    # drags prose ink into the label color, overriding the theme's muted axis
    # color at the merge. Mirrors the `title` sentinel above (chart-local title
    # is likewise a skip-slots sparse patch). The axis element font/color/family
    # cascade is owned by the global axis nodes, not the per-family override.
    axis: Annotated[BaseAxisStylePatch | None, SkipInheritSlots()] = Field(
        default=None,
        description="Override applied to both x and y axes; None inherits the global axis at render.",
    )
    axis_x: Annotated[AxisXStylePatch | None, SkipInheritSlots()] = Field(
        default=None,
        description="Per-chart-type x-axis style overrides; None inherits the global axis_x at render.",
    )
    axis_y: Annotated[AxisYStylePatch | None, SkipInheritSlots()] = Field(
        default=None,
        description="Per-chart-type y-axis style overrides; None inherits the global axis_y at render.",
    )
    axis_quantitative: Annotated[
        QuantitativeAxisStylePatch | None, SkipInheritSlots()
    ] = Field(
        default=None,
        description="Per-chart-type quantitative-axis overrides; None inherits the global axis_quantitative at render.",
    )
    axis_band: Annotated[BandAxisStylePatch | None, SkipInheritSlots()] = Field(
        default=None,
        description="Per-chart-type categorical (band) axis overrides; None inherits the global band axis at render.",
    )
    number_format: Annotated[FormatAlias | str | None, Format()] = Field(
        default=None,
        description="Default number format for axes and tooltips (D3 format string); None inherits from theme.",
    )
    time_format: Annotated[FormatAlias | str | None, Format()] = Field(
        default=None,
        description="Default time format for temporal axes (D3 time format string); None inherits from theme.",
    )
    # InheritSlot: per-family data_table inherits from Style.charts.data_table.
    # Field stays nullable so theme YAML can omit it; inherit_graph.py emits a
    # container-level copy link for nullable InheritSlot fields so apply_inherit
    # copies the whole parent when None (and fills sub-fields when partially set).
    data_table: Annotated[
        DataTableStylePatch | None, InheritSlot(from_path="Style.charts.data_table")
    ] = Field(
        default=None,
        description="Per-chart-type data_table style override.",
    )


class _RadialChartStyle(_PaintedChartStyleBaseAllOptional):
    """Radial families: pie, donut."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Optional sentinel: None means 'no inner radius' (solid pie); float means donut.
    # The None state is meaningful in the resolved model — NOT a 'theme failed to populate'
    # fallback. Cascade preserves None through merge so the renderer can branch on solid
    # vs. donut without re-reading raw YAML.
    inner_radius: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Hole-to-disk ratio 0–1 (inner radius / outer radius). None = solid pie (no hole).",
    )
    total: TotalStyle = Field(description="Donut center total paint (value and label).")


class _GeoChartStyle(_PaintedChartStyleBaseAllOptional):
    """Geo families: geoshape (choropleth), point_map.

    ``geo_source`` is intentionally absent — it is a chart-root channel field
    (on ``_GeoChartFields``), not a style concern.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Override: geo families do not support categorical color (extra_forbidden via StaticGradientColorStyle).
    color: StaticGradientColorStyle | None = Field(  # type: ignore[assignment]
        default=None,
        description="Geo color: static paint or gradient scale only (no categorical arm).",
    )
    projection: ProjectionStyle = Field(
        description="Vega-Lite projection configuration for this geo family."
    )
    basemap: BasemapStyle = Field(
        default_factory=BasemapStyle,
        description="Background map layer; None source = no topo layer.",
    )
