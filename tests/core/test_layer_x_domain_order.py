"""Regression: the shared categorical x domain assembled across layer datasets.

Two bar layers backed by different queries (the shape the deterministic
migrator emits — one query per layer) each contribute their own x values to
one shared band scale. The union was built strictly by order of appearance:
every base row first, then each layer's own categories. For a domain with a
defined ascending order (date-like buckets, numbers) that silently renders a
false trend — ``2024-01, 2024-03, 2024-05, 2024-02, 2024-04, 2024-06`` reads
as chronological and is not. For a domain with no defined order it is not
fixable by sorting, so it warns instead of guessing.
"""

from __future__ import annotations

from dbt_charts.core.render.chart.x_domain import rendered_x_domain


def _rows(field: str, values: list[object]) -> list[dict]:
    return [{field: v} for v in values]


def _domain(base: list[object], *layers: list[object]) -> list:
    return rendered_x_domain(
        {"field": "x", "type": "ordinal"},
        _rows("x", base),
        [("x", _rows("x", lv)) for lv in layers],
        chart_id=None,
    )


def test_date_like_union_across_layers_is_chronological() -> None:
    """Complementary month buckets split across two layer queries."""
    assert _domain(
        ["2024-01", "2024-03", "2024-05"], ["2024-02", "2024-04", "2024-06"]
    ) == ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06"]


def test_iso_day_union_across_layers_is_chronological() -> None:
    assert _domain(["2024-01-03"], ["2024-01-02"], ["2024-01-01"]) == [
        "2024-01-01",
        "2024-01-02",
        "2024-01-03",
    ]


def test_numeric_union_across_layers_is_numeric_order() -> None:
    """Numeric categories must not read 1, 3, 5, 2, 4 — and not 1, 10, 2 either."""
    assert _domain([1, 3, 5], [2, 4, 10]) == [1, 2, 3, 4, 5, 10]


def test_unorderable_union_keeps_first_seen_order() -> None:
    """No defined order → no guess. Sorting month names lexically is worse."""
    assert _domain(["Jan", "Mar", "May"], ["Feb", "Apr", "Jun"]) == [
        "Jan",
        "Mar",
        "May",
        "Feb",
        "Apr",
        "Jun",
    ]


def test_base_query_order_is_untouched_when_layers_add_nothing() -> None:
    """The query owns the order of the categories it returns."""
    assert _domain(["2024-05", "2024-01", "2024-03"], ["2024-01"]) == [
        "2024-05",
        "2024-01",
        "2024-03",
    ]


def test_single_dataset_date_order_is_untouched() -> None:
    """No layers at all: a deliberate SQL ORDER BY survives verbatim."""
    assert _domain(["2024-05", "2024-01", "2024-03"]) == [
        "2024-05",
        "2024-01",
        "2024-03",
    ]


def test_authored_sort_still_wins_over_the_defined_order() -> None:
    """An authored ``sort:`` describes the rendered order; it is not overridden."""
    base = [
        {"x": "2024-01", "amt": 1.0},
        {"x": "2024-03", "amt": 3.0},
        {"x": "2024-05", "amt": 2.0},
    ]
    domain = rendered_x_domain(
        {
            "field": "x",
            "type": "ordinal",
            "sort": {"field": "amt", "order": "descending"},
        },
        base,
        [("x", _rows("x", ["2024-02"]))],
        chart_id=None,
    )
    assert domain[:3] == ["2024-03", "2024-05", "2024-01"]


def test_orderable_values_but_a_base_that_does_not_follow_them_are_left_alone() -> None:
    """The guard the whole design rests on: extend the base's order, never impose one.

    These months sort perfectly well; the base query does not return them in
    that order, because it ordered by a measure. Sorting the union here would
    override that ``ORDER BY`` — the exact regression
    ``test_layer_x_union.py``'s docstring recounts. The layer-only value goes
    on the end and the chart earns WARN-LAYER-X-DOMAIN-PAINT-ORDER instead.
    """
    assert _domain(["2024-05", "2024-01", "2024-03"], ["2024-02"]) == [
        "2024-05",
        "2024-01",
        "2024-03",
        "2024-02",
    ]


def test_a_band_anchor_reads_the_same_domain_the_axis_pins() -> None:
    """One layer's caption cannot resolve against a domain the axis never draws.

    ``_layer_band_anchor`` captions the leading/trailing band of the RENDERED
    axis, which ``_reconcile_x_domain`` pins from every layer's contribution.
    Given only its own contribution, a layer whose values are orderable places
    them into the base's order, while a sibling contributing an unorderable
    value tips the real union into paint order — the two then disagree about
    which value renders first, and the caption paints off the far plot edge.
    """
    from dbt_charts.core.render.chart.emitters._overlay import _layer_band_anchor

    base = _rows("x", ["2024-02", "2024-03"])
    orderable_layer = [{"x": "2024-01", "y": 1.0}]
    unorderable_layer = [{"x": "Mar", "y": 1.0}]
    columns = [("x", orderable_layer), ("x", unorderable_layer)]
    x_enc = {"field": "x", "type": "ordinal"}

    axis_domain = rendered_x_domain(x_enc, base, columns, chart_id=None)
    anchor = _layer_band_anchor("x", "y", x_enc, base, orderable_layer, columns)

    assert axis_domain == ["2024-02", "2024-03", "2024-01", "Mar"]
    # 2024-01 renders LAST on that axis, so it is the trailing band, not the
    # leading one — and this layer draws no mark on the leading band at all.
    assert anchor.leading_edge is None
    assert anchor.trailing_edge is None
