"""Tests for authored ``layer.x`` on cartesian overlay layers.

``TypedLayerBase.x`` validates fine on YAML input but, before this fix, was
never read by the overlay renderer (``render_cartesian_overlay``) — every
layer silently inherited the base chart's ``x`` field. Covers:

- An authored ``layer.x`` drives that layer's own x encoding field name.
- A layer's own x categories that aren't a subset of the base's still appear
  in the shared x-scale domain (ordered union, not just the base's domain).
- Default/unset ``layer.x`` is unchanged: the layer inherits the base's x
  encoding verbatim (no explicit ``x`` on the layer wrapper).
- A step-band chart with a layer whose x diverges from the base still renders
  the full unioned category grid, no gaps.
"""

from __future__ import annotations

import datetime
import json
import re

import pytest
import vl_convert as vlc

from dbt_charts.core.compile.models.chart.authored._layer import LineLayer
from dbt_charts.core.compile.models.chart.normalized import BarChart as NBarChart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.chart._chart_rows import regroup
from dbt_charts.core.diagnostics.chart_data import ChartDataError
from dbt_charts.core.render.chart._types import VLDict
from dbt_charts.core.render.chart.emitters._overlay import _reconcile_x_domain
from dbt_charts.core.render.chart.emitters.bar import BarEmitter
from dbt_charts.core.render.chart.spec import RenderBox
from dbt_charts.core.render.chart.translate import translate_to_vl

_DEFAULT_BOX = RenderBox(width=600.0, height=300.0)

_BAR_DATA: list[dict] = [
    {"month": "Jan", "revenue": 100.0, "target": 90.0},
    {"month": "Feb", "revenue": 200.0, "target": 180.0},
]


def _sql(sql: str = "SELECT 1"):
    return SqlQuery(sql=sql, source="t")


def _default_board_style():
    from dbt_charts.core.compile.config import get_default_theme_name, get_theme_style
    from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context

    return resolve_chart_style_context(get_theme_style(get_default_theme_name()))


def _bar_normalized(**kwargs):  # type: ignore[no-untyped-def]
    defaults = {
        "id": "bar1",
        "type": "bar",
        "x": "month",
        "y": "revenue",
        "query": _sql(),
        "query_name": "q",
        "variable_dependencies": set(),
    }
    defaults.update(kwargs)
    return NBarChart(**defaults)


def _line_layer_wrapper(vl, y_field):  # type: ignore[no-untyped-def]
    """Return the overlay wrapper's own top-level dict for the given y field."""
    for layer in vl.get("layer", []):
        enc = layer.get("encoding", {})
        if enc.get("y", {}).get("field") == y_field:
            return layer
    raise AssertionError(f"no overlay layer with y field {y_field!r}")


def test_layer_own_x_drives_its_own_field() -> None:
    """A layer authoring x: quarter must encode against quarter, not month."""
    data = [
        {"month": "Jan", "revenue": 100.0, "quarter": "Q1", "target": 90.0},
        {"month": "Feb", "revenue": 200.0, "quarter": "Q1", "target": 180.0},
    ]
    layer = LineLayer(type="line", x="quarter", y="target")
    chart = _bar_normalized(layers=[layer])
    resolved = resolve(chart, data, _default_board_style())
    assert resolved.layers[0].x == "quarter"

    vl = translate_to_vl(BarEmitter().emit(resolved, _DEFAULT_BOX, regroup((), data)))
    wrapper = _line_layer_wrapper(vl, "target")
    assert wrapper["encoding"]["x"]["field"] == "quarter"


def test_layer_without_x_inherits_base_x_exactly() -> None:
    """Regression guard: default/unset layer.x must not add an x encoding —
    the layer keeps inheriting the base's x channel verbatim, as before."""
    layer = LineLayer(type="line", y="target")
    chart = _bar_normalized(layers=[layer])
    resolved = resolve(chart, _BAR_DATA, _default_board_style())
    assert resolved.layers[0].x is None

    vl = translate_to_vl(
        BarEmitter().emit(resolved, _DEFAULT_BOX, regroup((), _BAR_DATA))
    )
    wrapper = _line_layer_wrapper(vl, "target")
    assert "x" not in wrapper["encoding"]


def test_layer_x_categories_not_subset_appear_in_union_domain() -> None:
    """A layer's own x values disjoint from the base's must still show up in
    the shared x-scale domain — the union, not just the base's own domain."""
    layer = LineLayer(type="line", x="quarter", y="target", query="targets")
    chart = _bar_normalized(layers=[layer])
    resolved = resolve(chart, _BAR_DATA, _default_board_style())

    targets_rows = [
        {"quarter": "Q1", "target": 90.0},
        {"quarter": "Q2", "target": 95.0},
    ]
    vl = translate_to_vl(
        BarEmitter().emit(
            resolved,
            _DEFAULT_BOX,
            regroup((), _BAR_DATA),
            datasets={"targets": targets_rows},
        )
    )
    domain = vl["encoding"]["x"]["scale"]["domain"]
    assert set(domain) == {"Jan", "Feb", "Q1", "Q2"}


def test_reconcile_x_domain_preserves_base_row_order_not_reordered() -> None:
    """_reconcile_x_domain must preserve the base's OWN row order —
    reflecting the base query's ORDER BY (or an authored chart.sort already
    applied upstream) — never silently re-sort it, even when every value
    happens to be date-shaped. Regression: a prior fix sorted a uniformly
    date-shaped union domain ascending, which is exactly wrong for a base
    ordered most-recent-first (DESC) — it silently flipped the axis order
    and overrode any authored chart.sort with a data-driven guess.

    Exercises _reconcile_x_domain directly rather than through the full bar
    emitter pipeline, since the emitter's own (separate, legitimate)
    calendar bucket-gap-fill also reorders true day-level dates
    chronologically upstream of this reconciliation, which would confound a
    black-box assertion on final row order.
    """
    x_enc: VLDict = {"field": "period", "type": "ordinal"}
    base_data: list[VLDict] = [
        {"period": "2024-01-01"},
        {"period": "2023-12-01"},
    ]
    layer_x_columns: list[tuple[str, list[VLDict]]] = [
        ("period", [{"period": "2024-02-01"}])
    ]
    _reconcile_x_domain(x_enc, base_data, layer_x_columns)
    assert x_enc["scale"]["domain"] == ["2024-01-01", "2023-12-01", "2024-02-01"]


def test_layer_own_date_x_reconciles_against_bucket_gated_ordinal_base() -> None:
    """A layer's own well-formed-ISO-date x column must reconcile against a
    base whose x resolved to ordinal via the bar density gate — not raise
    just because the per-field naive classifier independently calls
    date-shaped data "temporal" while the base (few distinct buckets) is
    "ordinal". Both the outer encoding's type AND the overlay sublayer's own
    x encoding must be repinned to "ordinal" (else Vega-Lite parses the
    layer's values as a real Date against a string-label domain). The
    unioned domain preserves the base's own row order first, then appends
    any layer-only categories in the layer's own first-seen order — never
    re-sorted, which would silently override the base query's ordering or
    an authored chart.sort.
    """
    data = [
        {"month": "2025-08-01", "revenue": 100.0},
        {"month": "2025-09-01", "revenue": 200.0},
    ]
    layer = LineLayer(type="line", x="month", y="target", query="targets")
    chart = _bar_normalized(layers=[layer], x="month")
    resolved = resolve(chart, data, _default_board_style())

    targets_rows = [
        {"month": "2024-01-01", "target": 10.0},
        {"month": "2025-08-01", "target": 90.0},
    ]
    vl = translate_to_vl(
        BarEmitter().emit(
            resolved,
            _DEFAULT_BOX,
            regroup((), data),
            datasets={"targets": targets_rows},
        )
    )
    assert vl["encoding"]["x"]["type"] == "ordinal"
    domain = vl["encoding"]["x"]["scale"]["domain"]
    assert domain == ["2025-08-01", "2025-09-01", "2024-01-01"]

    wrapper = _line_layer_wrapper(vl, "target")
    assert wrapper["encoding"]["x"]["type"] == "ordinal"


def test_layer_nominal_x_reconciles_against_bucket_gated_ordinal_base() -> None:
    """A layer's own plain non-date-like x column (classifying "nominal"
    standalone) must still union against a base whose x resolved to
    "ordinal" via the bar density gate — nominal and ordinal are both
    discrete-label types, and Vega-Lite's union only cares that both sides
    share ONE pinned type, not that the two independent per-field
    classifications happened to match exactly. Requiring exact equality
    (rather than "both categorical") would reject real dashboards where a
    goal/target layer's own field resolves nominal while the base's
    same-shaped-but-bucket-gated field resolves ordinal.
    """
    data = [
        {"month": "2025-08-01", "revenue": 100.0},
        {"month": "2025-09-01", "revenue": 200.0},
    ]
    layer = LineLayer(type="line", x="team", y="target", query="targets")
    chart = _bar_normalized(layers=[layer], x="month")
    resolved = resolve(chart, data, _default_board_style())

    targets_rows = [
        {"team": "Sales", "target": 10.0},
        {"team": "Marketing", "target": 90.0},
    ]
    vl = translate_to_vl(
        BarEmitter().emit(
            resolved,
            _DEFAULT_BOX,
            regroup((), data),
            datasets={"targets": targets_rows},
        )
    )
    assert vl["encoding"]["x"]["type"] == "ordinal"
    wrapper = _line_layer_wrapper(vl, "target")
    assert wrapper["encoding"]["x"]["type"] == "ordinal"
    domain = vl["encoding"]["x"]["scale"]["domain"]
    assert set(domain) == {"2025-08-01", "2025-09-01", "Sales", "Marketing"}


def test_layer_own_date_x_renders_without_nan_or_scrambled_positions() -> None:
    """End-to-end regression: the reconciled spec from the test above must
    actually render correctly through vl-convert, not just carry the right
    dict shape — no phantom "NaN" axis entries, exactly the unioned domain's
    categories on the axis."""
    data = [
        {"month": "2025-08-01", "revenue": 100.0},
        {"month": "2025-09-01", "revenue": 200.0},
    ]
    layer = LineLayer(type="line", x="month", y="target", query="targets")
    chart = _bar_normalized(layers=[layer], x="month")
    resolved = resolve(chart, data, _default_board_style())

    targets_rows = [
        {"month": "2024-01-01", "target": 10.0},
        {"month": "2025-08-01", "target": 90.0},
    ]
    vl = translate_to_vl(
        BarEmitter().emit(
            resolved,
            _DEFAULT_BOX,
            regroup((), data),
            datasets={"targets": targets_rows},
        )
    )
    svg = vlc.vegalite_to_svg(json.dumps(vl))
    assert "NaN" not in svg
    domain = vl["encoding"]["x"]["scale"]["domain"]
    assert len(domain) == 3, f"expected exactly 3 axis categories, got: {domain}"
    aria_labels = re.findall(r'aria-label="([^"]*)"', svg)
    axis_label = next(a for a in aria_labels if a.startswith("X-axis"))
    assert "NaN" not in axis_label
    for value in domain:
        assert value in axis_label, f"{value!r} missing from axis: {axis_label}"


def test_layer_own_date_x_union_domain_is_json_safe() -> None:
    """The union domain built for a shared categorical x scale must contain
    JSON-safe scalars (str/int/float/bool/None), never raw ``datetime.date``
    objects — even though those are valid, well-formed values in the row data
    itself (e.g. BigQuery DATE columns come back from the executor as native
    ``datetime.date`` objects)."""
    data = [
        {"month": datetime.date(2025, 8, 1), "revenue": 100.0},
        {"month": datetime.date(2025, 9, 1), "revenue": 200.0},
    ]
    layer = LineLayer(type="line", x="month", y="target", query="targets")
    chart = _bar_normalized(layers=[layer], x="month")
    resolved = resolve(chart, data, _default_board_style())

    targets_rows = [
        {"month": datetime.date(2024, 1, 1), "target": 10.0},
        {"month": datetime.date(2025, 8, 1), "target": 90.0},
    ]
    vl = translate_to_vl(
        BarEmitter().emit(
            resolved,
            _DEFAULT_BOX,
            regroup((), data),
            datasets={"targets": targets_rows},
        )
    )
    domain = vl["encoding"]["x"]["scale"]["domain"]
    assert all(isinstance(v, str) for v in domain)
    assert domain == ["2025-08-01", "2025-09-01", "2024-01-01"]


def test_step_band_layer_with_own_x_unions_full_category_grid() -> None:
    """A step-band overlay whose x diverges from the base must still render
    the full unioned category grid on the shared x scale — no gaps."""
    layer = LineLayer(
        type="line",
        x="quarter",
        y="target",
        query="targets",
        style={"marks": {"line": {"curve": "step", "connect": True}}},
    )
    chart = _bar_normalized(layers=[layer])
    resolved = resolve(chart, _BAR_DATA, _default_board_style())

    targets_rows = [
        {"quarter": "Q1", "target": 90.0},
        {"quarter": "Q2", "target": 95.0},
    ]
    vl = translate_to_vl(
        BarEmitter().emit(
            resolved,
            _DEFAULT_BOX,
            regroup((), _BAR_DATA),
            datasets={"targets": targets_rows},
        )
    )
    domain = vl["encoding"]["x"]["scale"]["domain"]
    assert set(domain) == {"Jan", "Feb", "Q1", "Q2"}

    wrapper = _line_layer_wrapper(vl, "target")
    assert "xOffset" in wrapper["encoding"]


def test_layer_quantitative_x_raises_against_categorical_base() -> None:
    """A layer's own genuinely quantitative x column must raise against a
    categorical base — the union mechanism only accepts discrete-label
    layers (nominal/ordinal/date-shaped-temporal), never continuous numeric
    data sharing a category axis."""
    layer = LineLayer(type="line", x="amount", y="target", query="targets")
    chart = _bar_normalized(layers=[layer])
    resolved = resolve(chart, _BAR_DATA, _default_board_style())

    targets_rows = [
        {"amount": 1.0, "target": 90.0},
        {"amount": 2.0, "target": 95.0},
    ]
    with pytest.raises(ChartDataError, match="quantitative"):
        translate_to_vl(
            BarEmitter().emit(
                resolved,
                _DEFAULT_BOX,
                regroup((), _BAR_DATA),
                datasets={"targets": targets_rows},
            )
        )


def test_layer_temporal_x_raises_against_non_date_categorical_base() -> None:
    """A layer's own well-formed-date x column must still raise against a
    categorical base whose domain is NOT itself date-shaped — the
    union-compatible widening for a standalone-"temporal" layer only covers
    a base that is date-shaped too (just density-gated to ordinal/nominal),
    never an arbitrary nominal base like plain month-name labels."""
    layer = LineLayer(type="line", x="signup_date", y="target", query="targets")
    chart = _bar_normalized(layers=[layer])
    resolved = resolve(chart, _BAR_DATA, _default_board_style())

    targets_rows = [
        {"signup_date": "2025-08-01", "target": 90.0},
        {"signup_date": "2025-09-01", "target": 95.0},
    ]
    with pytest.raises(ChartDataError, match="temporal"):
        translate_to_vl(
            BarEmitter().emit(
                resolved,
                _DEFAULT_BOX,
                regroup((), _BAR_DATA),
                datasets={"targets": targets_rows},
            )
        )


def test_step_band_layer_with_date_shaped_x_gets_xoffset() -> None:
    """A step-band overlay whose own x is well-formed dates, sharing a
    date-shaped base bucket-gated to ordinal, must still get the band
    xOffset — its type must be resolved against the base BEFORE step-band
    curve detection runs, not classified standalone (as "temporal", which
    fails the band-step gate) and repinned only afterward."""
    data = [
        {"month": "2025-08-01", "revenue": 100.0},
        {"month": "2025-09-01", "revenue": 200.0},
    ]
    layer = LineLayer(
        type="line",
        x="month",
        y="target",
        query="targets",
        style={"marks": {"line": {"curve": "step", "connect": True}}},
    )
    chart = _bar_normalized(layers=[layer], x="month")
    resolved = resolve(chart, data, _default_board_style())

    targets_rows = [
        {"month": "2024-01-01", "target": 10.0},
        {"month": "2025-08-01", "target": 90.0},
    ]
    vl = translate_to_vl(
        BarEmitter().emit(
            resolved,
            _DEFAULT_BOX,
            regroup((), data),
            datasets={"targets": targets_rows},
        )
    )
    wrapper = _line_layer_wrapper(vl, "target")
    assert "xOffset" in wrapper["encoding"]


def test_layer_nominal_x_raises_against_quantitative_base() -> None:
    """A layer's own genuinely non-numeric x column must raise against a
    quantitative base — a numeric month-number base sharing its scale with a
    string month-name layer produces NaN pixel positions for that layer's
    marks (Vega-Lite cannot resolve a nominal value against a quantitative
    scale)."""
    data = [
        {"month_num": 1, "revenue": 100.0},
        {"month_num": 2, "revenue": 200.0},
    ]
    layer = LineLayer(type="line", x="month_name", y="target", query="targets")
    chart = _bar_normalized(layers=[layer], x="month_num")
    resolved = resolve(chart, data, _default_board_style())

    targets_rows = [
        {"month_name": "January", "target": 90.0},
        {"month_name": "February", "target": 95.0},
    ]
    with pytest.raises(ChartDataError, match="nominal"):
        translate_to_vl(
            BarEmitter().emit(
                resolved,
                _DEFAULT_BOX,
                regroup((), data),
                datasets={"targets": targets_rows},
            )
        )


def test_layer_temporal_x_raises_against_quantitative_base() -> None:
    """A layer's own well-formed-date x column must also raise against a
    quantitative base — sharing a numeric scale with temporal (epoch-ms)
    values does NOT get a correct native domain union from Vega-Lite: the
    base's small numeric domain (1, 2) forces the shared scale's number
    format onto the layer's near-zero epoch-ms values, producing garbled
    tick labels rather than a valid rendering."""
    data = [
        {"month_num": 1, "revenue": 100.0},
        {"month_num": 2, "revenue": 200.0},
    ]
    layer = LineLayer(type="line", x="signup_date", y="target", query="targets")
    chart = _bar_normalized(layers=[layer], x="month_num")
    resolved = resolve(chart, data, _default_board_style())

    targets_rows = [
        {"signup_date": "2025-08-01", "target": 90.0},
        {"signup_date": "2025-09-01", "target": 95.0},
    ]
    with pytest.raises(ChartDataError, match="temporal"):
        translate_to_vl(
            BarEmitter().emit(
                resolved,
                _DEFAULT_BOX,
                regroup((), data),
                datasets={"targets": targets_rows},
            )
        )


def test_layer_quantitative_x_does_not_raise_against_quantitative_base() -> None:
    """A layer's own genuinely quantitative x column must NOT raise against a
    quantitative base — both resolve to the same continuous type, and
    Vega-Lite's native domain union across sub-layers handles that
    combination correctly."""
    data = [
        {"month_num": 1, "revenue": 100.0},
        {"month_num": 2, "revenue": 200.0},
    ]
    layer = LineLayer(type="line", x="week_num", y="target", query="targets")
    chart = _bar_normalized(layers=[layer], x="month_num")
    resolved = resolve(chart, data, _default_board_style())

    targets_rows = [
        {"week_num": 1.0, "target": 90.0},
        {"week_num": 2.0, "target": 95.0},
    ]
    vl = translate_to_vl(
        BarEmitter().emit(
            resolved,
            _DEFAULT_BOX,
            regroup((), data),
            datasets={"targets": targets_rows},
        )
    )
    wrapper = _line_layer_wrapper(vl, "target")
    assert wrapper["encoding"]["x"]["field"] == "week_num"


def test_layer_with_empty_own_query_against_quantitative_base_does_not_raise() -> None:
    """A layer whose own query returned zero rows must not spuriously raise
    against a quantitative base. ``infer_vega_type_from_data`` classifies an
    empty dataset as "nominal" — an absence sentinel, not a real
    classification — so the quantitative-base guard must require a
    data-backed type before rejecting, or an ordinary empty targets/goals
    overlay (a transient, unremarkable state) would error the whole tile."""
    data = [
        {"month_num": 1, "revenue": 100.0},
        {"month_num": 2, "revenue": 200.0},
    ]
    layer = LineLayer(type="line", x="month_num", y="target", query="targets")
    chart = _bar_normalized(layers=[layer], x="month_num")
    resolved = resolve(chart, data, _default_board_style())

    vl = translate_to_vl(
        BarEmitter().emit(
            resolved, _DEFAULT_BOX, regroup((), data), datasets={"targets": []}
        )
    )
    wrapper = _line_layer_wrapper(vl, "target")
    assert wrapper["encoding"]["x"]["field"] == "month_num"
