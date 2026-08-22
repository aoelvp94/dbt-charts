"""FacetFeature — record small-multiples intent from ``chart.multiples``.

Records the facet row/column fields and scale on the ``ChartSpec``; the actual
structural wrap into a Vega-Lite ``facet`` operator happens in ``translate_to_vl``
(mirroring how ``EndpointLabelFeature`` records composition intent that
``translate.py`` later realizes as hconcat/vconcat).

The both-edge y-axis for a wide grid is NOT decided here — it is already baked
into the resolved ``axis_y.mirror`` flag at resolve time, so ``MirrorAxisFeature``
(which runs before this) has already appended the ghost overlay to the unit spec.
"""

from __future__ import annotations

from typing import Any

from dbt_charts.core.compile.models.chart.resolved import (
    LayeredResolvedChart,
    ResolvedChart,
)
from dbt_charts.core.compile.models.chart.resolved._base import (
    _CartesianResolvedChartFields,
)
from dbt_charts.core.compile.models.chart.resolved.bar import ResolvedBarChart
from dbt_charts.core.diagnostics.chart_data import ChartDataError
from dbt_charts.core.diagnostics.codes_render import (
    ERR_MULTIPLES_DATA_TABLE,
    ERR_MULTIPLES_ENDPOINT_LABELS,
    ERR_MULTIPLES_LAYER_PARTITION,
)
from dbt_charts.core.render.chart.spec import ChartSpec, RenderBox


class FacetFeature:
    """``chart.multiples`` → facet row/column/scale recorded on the spec."""

    def applies_to(self, chart: ResolvedChart) -> bool:
        return (
            isinstance(chart, _CartesianResolvedChartFields)
            and chart.multiples is not None
        )

    def apply(
        self,
        spec: ChartSpec,
        chart: ResolvedChart,
        box: RenderBox,
        datasets: dict[str | None, list[dict[str, Any]]],
    ) -> ChartSpec:
        assert isinstance(chart, _CartesianResolvedChartFields)  # applies_to guard
        # Endpoint labels compose the chart into an hconcat/vconcat pane; faceting
        # a concat is nonsensical. Refuse rather than emit a broken spec. A
        # multi-column set usually raises this same code earlier, from
        # MirrorAxisFeature, because it auto-mirrors the y-axis — but only when
        # the auto-mirror actually applies (shared scale, unset axis_y.mirror,
        # quantitative y). A multi-column set missing any of those lands here.
        if spec.endpoint_label_layout is not None:
            raise ChartDataError.from_code(
                ERR_MULTIPLES_ENDPOINT_LABELS, chart_id=chart.id
            )
        if chart.data_table is not None:
            raise ChartDataError.from_code(ERR_MULTIPLES_DATA_TABLE, chart_id=chart.id)
        multiples = chart.multiples
        assert multiples is not None  # applies_to guarantees this
        # The "resolved without data, rendered with real rows" check lives in
        # BoardRenderSession.emit_chart, before the emitter runs — an emitter
        # that regroups by panel_axes (gap-fill, per-panel validation) would
        # otherwise see axes=() as the ordinary N=1 case and raise a
        # misleading duplicate-rows error before this feature ever runs.
        # An own-query overlay layer whose query returns the partition
        # column(s) means the author wants per-panel layer data, which
        # Vega-Lite cannot express: the facet operator only ever partitions
        # the root dataset, never a layer's own inline dataset.
        # Keyed on column presence only — row content/cardinality never
        # matters, and an empty layer dataset has no key to test, so it is
        # allowed (nothing to repeat wrongly in every panel).
        if isinstance(chart, LayeredResolvedChart):
            partition_fields = [
                field
                for field in (multiples.rows, multiples.columns)
                if field is not None
            ]
            for layer in chart.layers:
                if layer.query_name is None or layer.query_name == chart.query_name:
                    continue
                # Unlike chart_rows() in feature.py, a missing key here is
                # NOT necessarily a caller bug: two real, non-production
                # callers pass an incomplete datasets map on purpose — the
                # board-level warning-detection pass (renderer.py, which
                # only threads the base chart's own rows) and
                # generate_vega_lite_spec() (a standalone dev/test entry
                # point with no per-query datasets concept at all). Neither
                # can supply this layer's own rows, so there is nothing to
                # validate for it here — the same tolerant lookup
                # render_cartesian_overlay uses (_overlay.py). A
                # present-but-empty layer dataset is the same "nothing to
                # repeat wrongly in any panel" story, so both share one
                # early-continue.
                layer_rows = datasets.get(layer.query_name)
                if not layer_rows:
                    continue
                layer_columns = set(layer_rows[0].keys())
                offending = [
                    field for field in partition_fields if field in layer_columns
                ]
                if offending:
                    raise ChartDataError.from_code(
                        ERR_MULTIPLES_LAYER_PARTITION,
                        chart_id=chart.id,
                        fields=offending,
                    )
        spec.facet_row = multiples.rows
        spec.facet_column = multiples.columns
        spec.facet_scale = multiples.scale
        # A horizontal bar flips its axes — the measure rides VL x, the category
        # y — so an independent facet scale has to free x there. Decided here
        # rather than in the emitter because an authored `layers:` overlay
        # returns a fresh ChartSpec, dropping anything the emitter stamped on
        # the one it was handed.
        spec.measure_channel = (
            "x"
            if isinstance(chart, ResolvedBarChart) and chart.orientation == "horizontal"
            else "y"
        )
        return spec
