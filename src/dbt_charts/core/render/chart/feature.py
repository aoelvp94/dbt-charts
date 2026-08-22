"""ChartFeature protocol and FeaturePipeline.

Cross-family chart overlays (zero baseline, endpoint labels, reference lines, …)
are ``ChartFeature`` implementations.  They are applied in list order after the
family emitter produces the initial ``ChartSpec``.

Ordering mechanism
------------------
``FeaturePipeline`` applies features in the exact order of the list it is given —
no sorting.  ``DEFAULT_FEATURES`` (in ``features/__init__.py``) is the single
source of truth for that order: to change when a feature runs relative to its
peers, reorder the list. There is no separate priority value to keep in sync.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from dbt_charts.core.compile.models.chart.resolved import ResolvedChart
from dbt_charts.core.compile.models.chart.resolved._base import (
    _CartesianResolvedChartFields,
)
from dbt_charts.core.compile.resolve.chart._chart_rows import ChartDataset, regroup
from dbt_charts.core.render.chart.spec import ChartSpec, RenderBox


def chart_rows(
    chart: ResolvedChart, datasets: dict[str | None, list[dict[str, Any]]]
) -> ChartDataset:
    """The chart's own query rows from ``datasets``, regrouped by the chart's
    baked ``panel_axes`` — keyed by ``chart.query_name``.

    ``datasets`` (built by ``layout_sizing.build_chart_datasets``) always
    carries an entry for the base chart's own key — including the ``None``
    key for a blank/placeholder chart with no named query, whose rows are
    always ``[]``. A missing key is a genuine caller bug (an incomplete
    ``datasets`` map), so this indexes directly rather than silently
    defaulting to ``[]``.

    Only a cartesian chart can facet (``panel_axes`` lives on
    ``_CartesianResolvedChartFields`` only); every other chart regroups
    against ``axes=()`` — the N=1 case, one panel holding every row.
    """
    axes = chart.panel_axes if isinstance(chart, _CartesianResolvedChartFields) else ()
    return regroup(axes, datasets[chart.query_name])


@runtime_checkable
class ChartFeature(Protocol):
    """Protocol for a cross-family chart overlay."""

    def applies_to(self, chart: ResolvedChart) -> bool:
        """Return True if this feature should run for ``chart``.

        Implementations typically check ``chart.chart_type`` or use ``isinstance``.
        """
        ...

    def apply(
        self,
        spec: ChartSpec,
        chart: ResolvedChart,
        box: RenderBox,
        datasets: dict[str | None, list[dict[str, Any]]],
    ) -> ChartSpec:
        """Apply the overlay to ``spec`` and return the (possibly mutated) spec.

        Implementations may mutate ``spec`` in place and return it, or return a new
        ``ChartSpec``.  Either is acceptable; mutation is idiomatic for performance.

        ``box`` is render-time slot geometry (``box.height`` etc.) passed through
        for layout decisions (e.g. endpoint-label overlap avoidance).

        ``datasets`` maps every query_name this chart references to its rows —
        the base chart's own rows (resolve via ``chart_rows(chart, datasets)``)
        plus, for a cartesian chart with typed overlay layers, each layer's own
        query override (``layer.query_name``, defaulting to the base chart's
        query_name when the layer authored none — see ``_resolve_one_layer``).
        """
        ...


class FeaturePipeline:
    """Applies an ordered list of ``ChartFeature``s to a ``ChartSpec``.

    Features are applied in the exact order given — the list order IS the
    application order, with no re-sorting.

    Args:
        features: The features to apply, in application order.
    """

    def __init__(self, features: list[ChartFeature]) -> None:
        self._features = list(features)

    def apply(
        self,
        spec: ChartSpec,
        chart: ResolvedChart,
        box: RenderBox,
        datasets: dict[str | None, list[dict[str, Any]]],
    ) -> ChartSpec:
        """Run all applicable features in list order.

        Args:
            spec: Initial spec from the family emitter.
            chart: The resolved chart model (used by features for type guards).
            box: Render-time slot geometry; features read ``box.height`` for
                overlap avoidance and similar layout decisions.
            datasets: Every query this chart references, keyed by query_name
                (see ``ChartFeature.apply``).

        Returns:
            The spec after all applicable features have been applied.
        """
        result = spec
        for feature in self._features:
            if feature.applies_to(chart):
                result = feature.apply(result, chart, box, datasets)
        return result
