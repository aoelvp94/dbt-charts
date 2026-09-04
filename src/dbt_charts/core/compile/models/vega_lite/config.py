"""Hand-owned VegaLiteConfig surface contract.

Stage: COMPILE
Purpose: Define the explicit set of Vega-Lite config fields dbt charts supports.

DESIGN DECISIONS
================

1. CLOSED CONTRACT — NO PASS-THROUGH
   ----------------------------------
   VegaLiteConfig rejects unknown fields. Every supported field is explicitly
   declared.

   This is the starting contract for the new chart style architecture.
   If a new Vega-Lite field needs support, add it here with a comment
   explaining whether it is:
   - SHIPPED: already present in a built-in default, theme, or style preset
   - COMMON: intentionally added as a common high-value option

2. DERIVATION
   ----------
   This model was derived by auditing every Vega-facing field emitted by
   style_to_vega_lite() across the production themes/*.yaml set.

   See test_vegalite_config_surface.py for the contract test that compiles
   every shipped theme through style_to_vega_lite() and asserts the output
   validates against this model.

3. COMMON ADDITIONS
   ----------------
   Beyond what is already shipped, the following fields were intentionally
   added because they are high-value options users commonly need:

   Top-level:
   - numberFormat, timeFormat — common global format overrides

   Mark configs:
   - color — shorthand for fill/stroke depending on mark type
   - cursor — pointer cursor for interactive marks
   - tooltip — mark-level tooltip toggle

   View:
   - strokeWidth — view border width
   - cornerRadius — rounded view corners

   Header:
   - labelFontSize, titleFontSize — facet header sizing
   - labelColor, titleColor — facet header colors
   - labelFont, titleFont — facet header fonts

Dependencies:
    - pydantic (BaseModel, ConfigDict)

See also:
    - test_vegalite_config_surface.py: Contract enforcement tests
    - defaults/themes/*.yaml: Shipped surface (compiled via style_to_vega_lite)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

# =============================================================================
# AXIS CONFIG
# =============================================================================


class AxisConfig(BaseModel):
    """Vega-Lite axis configuration.

    Not part of the VegaLiteConfig closed contract — axis style is emitted at
    encoding level by the cartesian emitters (``render/chart/emitters/_cartesian.py``)
    via the per-variant axis/scale style models.

    Ref: https://vega.github.io/vega-lite/docs/axis.html
    """

    model_config = ConfigDict(extra="forbid")

    # Domain
    domain: bool | None = None
    domainColor: str | None = None
    domainWidth: float | None = None

    # Grid
    grid: bool | None = None
    gridColor: str | None = None
    gridDash: list[float] | None = None
    gridOpacity: float | None = None
    gridWidth: float | None = None

    # Labels
    labelColor: str | None = None
    labelFont: str | None = None
    labelFontSize: float | None = None
    labelFontWeight: str | float | None = None
    labelPadding: float | None = None
    labelExpr: str | None = None
    labelAngle: float | None = None
    labelAlign: str | None = None
    labelBaseline: str | None = None
    labelOverlap: bool | str | None = None
    labelSeparation: float | None = None
    labelFlush: bool | float | None = None
    labels: bool | None = None
    labelLimit: float | None = None
    labelBound: bool | float | None = None
    labelOffset: float | None = None
    labelLineHeight: float | None = None
    labelAnchor: str | None = None

    # Ticks
    ticks: bool | None = None
    tickColor: str | None = None
    tickSize: float | None = None
    tickWidth: float | None = None
    tickCount: float | dict[str, Any] | None = None
    tickExtra: bool | None = None

    # Title
    titleColor: str | None = None
    titleFont: str | None = None
    titleFontSize: float | None = None
    titleFontWeight: str | float | None = None
    titlePadding: float | None = None
    titleAlign: str | None = None
    titleAngle: float | None = None
    titleX: float | None = None
    titleY: float | None = None

    # Orientation / layout
    orient: str | None = None
    maxExtent: float | None = None
    minExtent: float | None = None
    bandPosition: float | None = None
    offset: float | None = None

    # COMMON additions
    format: str | None = None
    values: list[Any] | None = None


# =============================================================================
# LEGEND CONFIG
# =============================================================================


class LegendConfig(BaseModel):
    """Vega-Lite legend configuration.

    Not part of the VegaLiteConfig closed contract — legend style is emitted at
    encoding level by ``render/chart/emitters/_channels.py:apply_color_legend``
    via LegendStyle.

    Ref: https://vega.github.io/vega-lite/docs/legend.html
    """

    model_config = ConfigDict(extra="forbid")

    # Labels
    labelColor: str | None = None
    labelFont: str | None = None
    labelFontSize: float | None = None
    labelFontWeight: str | float | None = None
    labelBaseline: str | None = None

    # Title
    titleColor: str | None = None
    titleFont: str | None = None
    titleFontSize: float | None = None
    titleFontWeight: str | float | None = None
    titlePadding: float | None = None

    # Layout
    orient: str | None = None
    direction: str | None = None
    columns: int | None = None
    offset: float | None = None
    padding: float | None = None

    # Symbols
    symbolSize: float | None = None
    symbolType: str | None = None
    symbolStrokeColor: str | None = None
    symbolShape: str | None = None  # COMMON

    # COMMON additions
    disable: bool | None = None
    gradientLength: float | None = None
    gradientThickness: float | None = None
    clipHeight: float | None = None


# =============================================================================
# TITLE CONFIG
# =============================================================================


class TitleConfig(BaseModel):
    """Vega-Lite title configuration.

    Ref: https://vega.github.io/vega-lite/docs/title.html
    """

    model_config = ConfigDict(extra="forbid")

    color: str | None = None
    font: str | None = None
    fontSize: float | None = None
    fontWeight: str | float | None = None
    anchor: str | None = None
    offset: float | None = None
    angle: float | None = None
    baseline: str | None = None
    subtitleColor: str | None = None
    subtitleFont: str | None = None
    subtitleFontSize: float | None = None
    subtitleFontWeight: str | float | None = None
    subtitlePadding: float | None = None


# =============================================================================
# VIEW CONFIG
# =============================================================================


class ViewConfig(BaseModel):
    """Vega-Lite view configuration.

    Ref: https://vega.github.io/vega-lite/docs/spec.html#config
    """

    model_config = ConfigDict(extra="forbid")

    fill: str | None = None
    stroke: str | None = None
    strokeWidth: float | None = None  # COMMON
    continuousWidth: float | None = None
    continuousHeight: float | None = None
    discreteWidth: float | None = None
    discreteHeight: float | None = None
    cornerRadius: float | None = None  # COMMON


# =============================================================================
# RANGE CONFIG
# =============================================================================


class RangeConfig(BaseModel):
    """Vega-Lite scale range configuration.

    Ref: https://vega.github.io/vega-lite/docs/scale.html#range-config
    """

    model_config = ConfigDict(extra="forbid")

    category: list[str] | None = None
    diverging: list[str] | None = None
    heatmap: list[str] | None = None
    ramp: list[str] | None = None


# =============================================================================
# MARK CONFIG
# =============================================================================


class MarkConfig(BaseModel):
    """Vega-Lite mark configuration.

    Used for per-mark-type config sections: bar, line, area, arc, point,
    rect, tick, circle, geoshape, image, rule, square, text, trail, symbol,
    shape, path.

    Ref: https://vega.github.io/vega-lite/docs/mark.html#config
    """

    model_config = ConfigDict(extra="forbid")

    # Core visual
    fill: str | None = None
    stroke: str | None = None
    strokeWidth: float | None = None
    strokeCap: str | None = None
    strokeJoin: str | None = None
    color: str | None = None  # COMMON: shorthand for fill/stroke
    opacity: float | None = None
    size: float | None = None
    filled: bool | None = None

    # Shape / interpolation
    shape: str | None = None
    interpolate: str | None = None

    # Geometry
    cornerRadius: float | None = None
    cornerRadiusTopLeft: float | None = None
    cornerRadiusTopRight: float | None = None
    cornerRadiusEnd: float | None = None
    innerRadius: float | None = None
    padAngle: float | None = None
    binSpacing: float | None = None
    continuousBandSize: float | None = None
    discreteBandSize: float | None = None

    # Line-specific
    point: bool | None = None
    line: bool | None = None

    # Text-specific
    align: str | None = None
    font: str | None = None
    fontSize: float | None = None
    fontWeight: str | float | None = None
    limit: float | None = None
    lineHeight: float | None = None

    # Image-specific
    aspect: bool | None = None

    # Interaction
    tooltip: bool | None = None
    cursor: str | None = None  # COMMON


# =============================================================================
# COMPOSITION CONFIG
# =============================================================================


class CompositionConfig(BaseModel):
    """Facet/concat composition configuration.

    Ref: https://vega.github.io/vega-lite/docs/facet.html
    """

    model_config = ConfigDict(extra="forbid")

    spacing: float | None = None
    columns: int | None = None


class HeaderConfig(BaseModel):
    """Facet header configuration.

    Ref: https://vega.github.io/vega-lite/docs/header.html
    """

    model_config = ConfigDict(extra="forbid")

    labelOrient: str | None = None
    labelPadding: float | None = None
    labelFontSize: float | None = None  # COMMON
    labelColor: str | None = None  # COMMON
    labelFont: str | None = None  # COMMON
    titleOrient: str | None = None
    titlePadding: float | None = None
    titleFontSize: float | None = None  # COMMON
    titleColor: str | None = None  # COMMON
    titleFont: str | None = None  # COMMON


# =============================================================================
# GROUP CONFIG
# =============================================================================


class GroupConfig(BaseModel):
    """Vega-Lite group mark configuration."""

    model_config = ConfigDict(extra="forbid")

    fill: str | None = None


# =============================================================================
# AUTOSIZE CONFIG
# =============================================================================


class AutosizeConfig(BaseModel):
    """Vega-Lite autosize configuration.

    Ref: https://vega.github.io/vega-lite/docs/size.html#autosize
    """

    model_config = ConfigDict(extra="forbid")

    type: str | None = None
    contains: str | None = None
    resize: bool | None = None


class PaddingConfig(BaseModel):
    """Vega-Lite directional padding configuration."""

    model_config = ConfigDict(extra="forbid")

    top: float | None = None
    right: float | None = None
    bottom: float | None = None
    left: float | None = None


# =============================================================================
# MARK (top-level) CONFIG
# =============================================================================


class TopLevelMarkConfig(BaseModel):
    """Top-level mark config (the `mark` key in config, not mark-type sections)."""

    model_config = ConfigDict(extra="forbid")

    tooltip: bool | None = None


# =============================================================================
# MAIN VEGA-LITE CONFIG
# =============================================================================


class VegaLiteConfig(BaseModel):
    """Hand-owned VegaLiteConfig surface contract.

    This model defines every Vega-Lite config field dbt charts explicitly
    supports. It is a CLOSED contract — unknown fields are rejected.

    Field provenance:
    - SHIPPED: present in at least one built-in default, theme, or style preset
    - COMMON: intentionally added as a high-value option not yet in presets

    To add a new field:
    1. Add it to the appropriate nested config class
    2. Comment it with SHIPPED or COMMON and justification
    3. Run test_vegalite_config_surface.py to verify coverage
    """

    model_config = ConfigDict(extra="forbid")

    # -------------------------------------------------------------------------
    # Top-level config
    # -------------------------------------------------------------------------
    background: str | None = None
    font: str | None = None
    padding: float | PaddingConfig | None = None

    # COMMON: global number/time formatting
    numberFormat: str | None = None
    timeFormat: str | None = None

    # -------------------------------------------------------------------------
    # Autosize
    # -------------------------------------------------------------------------
    autosize: AutosizeConfig | None = None

    # -------------------------------------------------------------------------
    # Top-level mark config
    # -------------------------------------------------------------------------
    mark: TopLevelMarkConfig | None = None

    # -------------------------------------------------------------------------
    # Title, view
    # -------------------------------------------------------------------------
    title: TitleConfig | None = None
    view: ViewConfig | None = None

    # -------------------------------------------------------------------------
    # Range
    # -------------------------------------------------------------------------
    range: RangeConfig | None = None

    # -------------------------------------------------------------------------
    # Mark-type configs (generic marks emitted by style_to_vega_lite)
    # bar/line/area/arc/point: emitted at spec.mark level — not here.
    # geoshape/image: no emit path in style_to_vega_lite — not here.
    # -------------------------------------------------------------------------
    rect: MarkConfig | None = None
    tick: MarkConfig | None = None
    circle: MarkConfig | None = None
    rule: MarkConfig | None = None
    square: MarkConfig | None = None
    text: MarkConfig | None = None
    trail: MarkConfig | None = None
    symbol: MarkConfig | None = None
    shape: MarkConfig | None = None
    path: MarkConfig | None = None

    # -------------------------------------------------------------------------
    # Composition
    # -------------------------------------------------------------------------
    facet: CompositionConfig | None = None
    concat: CompositionConfig | None = None
    header: HeaderConfig | None = None

    # -------------------------------------------------------------------------
    # Group
    # -------------------------------------------------------------------------
    group: GroupConfig | None = None
