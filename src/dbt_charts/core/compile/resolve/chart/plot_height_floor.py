"""Height floor for narrow cartesian cards: a measurement, not a mutation.

Extends the ``pie`` family's ``wheel_dominance_min_ratio`` precedent
(``compile/resolve/chart/pie_attachment.py``) to cartesian charts: below a
calibrated fraction of the card's own height, the plot is starved. Shared by
every cartesian family that estimates a plot-height floor -- currently
``bar.py``'s own ``WARN-PLOT-HEIGHT-BELOW-MINIMUM`` measurement and this
module's ``legend_wrap_fits_height_budget`` (``_axes.py``), which asks this
same floor whether a candidate wrapped legend still leaves the plot clear,
rather than carrying a second, independently-calibrated budget.

Two invariants hold this together:

- **The floor is a fraction of the card's own height**, so card width cannot
  gate it. A short, wide card carrying heavy chrome is starved the same way a
  narrow one is.
- **``card_height`` is the card the renderer will actually build** —
  ``get_item_content_height`` (render/sizing.py), which is the aspect-ratio
  content height *plus* ``2 * style.frame.card_padding``. Measuring the
  content box alone put the floor on a card two paddings shorter than the
  drawn one. Card padding is therefore charged here as chrome, where it
  belongs, rather than netted out of the card.

Nothing in this module removes chrome. An earlier version also chose what to
drop (axis titles, then the subtitle) to keep the plot clear of the floor;
that ladder was retired because for a bar the legend is typically the only
thing naming a series, so it can never be a candidate to give way, and a
ladder sparing the legend fires almost never. ``bar.py`` surfaces the
measurement as ``WARN-PLOT-HEIGHT-BELOW-MINIMUM`` instead.

The chrome figures are calibrated constants
(``ChartRenderingConfig.PlotHeightFloorConfig`` in ``compile/models/config.py``),
not live measurements: Vega-Lite's ``autosize:fit`` divides a card's height
between chrome and plot at render time, and replicating that at compile time
is neither tractable nor how the sibling ``_stack_legend_should_yield``
estimator does it. They carry a known bias, recorded beside them in
config.py. ``legend_height_px`` is the one input this module does NOT read
off config itself -- it is a caller-computed fact (a family- and
layout-specific legend estimate), passed in rather than read here, so this
module stays legend-shape-agnostic.
"""

from __future__ import annotations

from dbt_charts.core.compile.config import get_chart_rendering

__all__ = ["estimate_plot_height", "plot_height_floor_px"]


def estimate_plot_height(
    card_height: float,
    *,
    card_padding_px: float,
    legend_height_px: float,
    subtitle_present: bool,
    axis_title_costs_height: bool,
) -> float:
    """Estimate the plot's own height once its known chrome is subtracted.

    Args:
        card_height: Total card height, matching what the renderer builds for
            this chart — an aspect-ratio estimate, not a live measurement.
        card_padding_px: ``style.frame.card_padding``, charged on both sides.
        legend_height_px: The legend's own estimated height. 0.0 when no
            legend renders, including when a series-naming rail replaces it —
            that rail sits beside the plot and costs width, not height.
        subtitle_present: Whether the chart has subtitle text authored.
        axis_title_costs_height: Whether the axis title on the horizontal
            rail shows. Only that one costs the plot height; the other is
            rotated and costs width.

    Returns:
        The estimated plot height in px. Can be negative for a severely
        squeezed card — callers compare it against a floor, not zero.
    """
    cfg = get_chart_rendering().plot_height_floor
    estimate = (
        card_height - 2 * card_padding_px - cfg.irreducible_height_px - legend_height_px
    )
    if axis_title_costs_height:
        estimate -= cfg.axis_titles_height_px
    if subtitle_present:
        estimate -= cfg.subtitle_height_px
    return estimate


def plot_height_floor_px(card_height: float) -> float:
    """The height this card's plot must clear to stay readable.

    The single definition of the floor, shared by the resolver that decides,
    the detector that reports the number to the author, and the tests. A
    second copy anywhere would let the two disagree silently.
    """
    return card_height * get_chart_rendering().plot_height_floor.ratio
