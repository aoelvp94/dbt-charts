"""Rendered-geometry regression test for band-aware ``curve: step``.

``dbt-charts/tests/core/render/chart/test_step_band_curve.py`` pins the
compiled Vega-Lite *spec* — doubled rows, the ``xOffset`` channel, range
exprs. None of that can see a renderer-side vertex transposition: Vega
sorts line/area vertices by x, and band i's right edge pixel
(``x[i] + bandwidth``) versus band i+1's left edge pixel (``x[i+1]``) are two
different float expressions that occasionally land one ULP apart. At that
tie, Vega swaps the pair, and ``step-after`` draws a zero-width spike into
the next band instead of the plateau — one band's plateau silently disappears
and its neighbor's is drawn twice.

This test renders the spec to SVG through vl-convert and parses geometry
PER MARK PATH, not unioned across the whole SVG. That distinction matters: a
fix that drops an area's filled path entirely (leaving only its stroke
outline) still reads "correct" under a union scan, because the surviving
stroke path alone carries every plateau. Scoring fill and stroke
independently — and asserting a nonzero count of real filled area paths —
catches that failure mode; a plain union does not.
"""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Generator

import pytest
import vl_convert as vlc

from dbt_charts.core.compile.config import reset_config
from dbt_charts.core.compile.models.chart.normalized import (
    AreaChart,
    Chart,
    LineChart,
)
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.models.style.context import ChartStyleContext
from dbt_charts.core.compile.models.style.resolved import ResolvedStyle
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

from ._svg_render import board_with_mark

# 10 bands, all-distinct y values so a legitimate equal-value merge can never
# be confused with the reordering bug (which also produces two same-valued
# plateaus, but at a DIFFERENT x than a real duplicate would).
_CATEGORIES = [f"c{i:02d}" for i in range(10)]
_VALUES = [11, 27, 8, 34, 19, 42, 5, 30, 23, 16]
_DATA = [{"cat": c, "val": v} for c, v in zip(_CATEGORIES, _VALUES, strict=True)]
_N = len(_DATA)

# Widths that trigger the float-tie fault pre-fix (found by empirical sweep),
# plus a couple of clean widths to prove the invariant isn't width-dependent
# on the fixed code.
_WIDTH_SWEEP = [363, 483, 563, 663, 763, 863, 1063]

_POINT_RE = re.compile(r"[ML]([-\d.e]+),([-\d.e]+)")
_PATH_TAG_RE = re.compile(r"<path[^>]*>")
_PATH_D_RE = re.compile(r'd="([^"]+)"')
_PATH_FILL_RE = re.compile(r'fill="([^"]+)"')
_PATH_STROKE_RE = re.compile(r'stroke="([^"]+)"')


@pytest.fixture(autouse=True)
def _reset() -> Generator[None]:
    reset_config()
    yield
    reset_config()


def _parse_points(path_d: str) -> list[tuple[float, float]]:
    """Every (x, y) vertex an SVG path's M/L commands carry, in order.

    Deliberately ignores other command letters (A, C, Z, ...): a point
    symbol's arc commands would otherwise inject spurious coordinates, and
    an area's closing "return along the baseline" is handled by
    ``_forward_sweep`` instead of being excluded here.
    """
    return [(float(x), float(y)) for x, y in _POINT_RE.findall(path_d)]


def _forward_sweep(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Points up to (not including) the first x-decrease.

    Drops an area path's return trip along the baseline back to its start —
    that trip is never part of the plateau geometry under test.
    """
    swept = [points[0]]
    max_x = points[0][0]
    for point in points[1:]:
        if point[0] < max_x - 1e-9:
            break
        max_x = max(max_x, point[0])
        swept.append(point)
    return swept


def _horizontal_runs(
    points: list[tuple[float, float]], eps: float = 1e-6
) -> list[tuple[float, float, float]]:
    """Merge adjacent same-y segments into (y, x_start, x_end) plateau runs."""
    runs: list[tuple[float, float, float]] = []
    for (x0, y0), (x1, y1) in itertools.pairwise(points):
        if abs(y1 - y0) > eps or x1 - x0 <= eps:
            continue
        if runs and abs(runs[-1][0] - y0) <= eps and abs(runs[-1][2] - x0) <= eps:
            runs[-1] = (y0, runs[-1][1], x1)
        else:
            runs.append((y0, x0, x1))
    return runs


def _path_plateaus(path_d: str) -> set[float]:
    """Distinct y pixels this ONE path carries as a non-zero-width run."""
    points = _parse_points(path_d)
    if len(points) < 2:
        return set()
    return {
        round(y, 1)
        for y, x_start, x_end in _horizontal_runs(_forward_sweep(points))
        if x_end - x_start > 1e-6
    }


def _path_kind(path_tag: str) -> str | None:
    """Classify a ``<path>`` element as "fill" or "stroke", or None to skip.

    A filled area path carries a real fill color and a closed ``d`` (ends in
    Z) — Vega-Lite always closes an area mark's own path back along the
    baseline. A stroke path (a line, or an area's own top-edge line) has no
    real fill and a real stroke color. This is a *classification*, not a
    geometry check — a point-symbol mark (arc-based, fill + closed) also
    matches "fill" here, but ``_path_plateaus`` naturally scores it empty
    (a symbol's arc commands parse to under 2 M/L points), so it never
    contributes a false plateau.
    """
    d_match = _PATH_D_RE.search(path_tag)
    if d_match is None:
        return None
    fill_match = _PATH_FILL_RE.search(path_tag)
    stroke_match = _PATH_STROKE_RE.search(path_tag)
    has_fill = fill_match is not None and fill_match.group(1) not in (
        "none",
        "transparent",
    )
    has_stroke = stroke_match is not None and stroke_match.group(1) not in (
        "none",
        "transparent",
    )
    if has_fill and d_match.group(1).rstrip().endswith(("Z", "z")):
        return "fill"
    if has_stroke:
        return "stroke"
    return None


def _mark_paths(svg: str) -> list[tuple[str, str]]:
    """(kind, d) for every fill/stroke mark path in the SVG."""
    paths = []
    for tag in _PATH_TAG_RE.findall(svg):
        kind = _path_kind(tag)
        if kind is None:
            continue
        d_match = _PATH_D_RE.search(tag)
        assert d_match is not None
        paths.append((kind, d_match.group(1)))
    return paths


def _render_svg(
    chart: Chart,
    board_rs: ResolvedStyle,
    board_ctx: ChartStyleContext,
    width: float,
) -> str:
    """Render straight through the emitter, sidestepping production's autosize.

    The width sweep this feeds pins the emitter's own output — the code path
    production renders through — across widths where the float-tie fault
    reproduced pre-fix; it does not pin production's actual rendered widths,
    since production uses ``autosize: fit`` rather than the ``pad`` swapped in
    below. The production-path pin is the ``step-band-curve-connected``
    fixture golden.
    """
    spec = generate_vega_lite_spec(
        chart, _DATA, width=width, board_style=board_rs, chart_style_context=board_ctx
    )
    # The default "fit" autosize can pick a width that hides the fault; "pad"
    # with an explicit width reproduces the ULP tie deterministically.
    spec["autosize"] = {"type": "pad", "contains": "padding", "resize": True}
    return vlc.vegalite_to_svg(json.dumps(spec))


def _assert_plateau_coverage(
    svg: str, *, require_fill: bool, per_path_single_plateau: bool = False
) -> None:
    """Assert fill and stroke paths independently carry every data plateau.

    ``require_fill``: the family must emit at least one filled area path
    whose own geometry (not a point symbol's) carries a real plateau — a
    disappeared fill (path count right, geometry empty) fails loudly here
    instead of being masked by a healthy stroke union.

    ``per_path_single_plateau``: for ``connect: false``, each band draws its
    own path (the ``detail`` channel splits them) — the reordering bug's
    signature is a path with a zero-width spike instead of its own plateau
    while a NEIGHBOR's path shows two. Checking per-path count == 1 catches
    that even when the total union still happens to cover all N values.
    """
    paths = _mark_paths(svg)
    by_kind: dict[str, list[set[float]]] = {"fill": [], "stroke": []}
    for kind, d in paths:
        by_kind[kind].append(_path_plateaus(d))

    stroke_plateau_sets = [s for s in by_kind["stroke"] if s]
    assert stroke_plateau_sets, (
        "expected at least one stroke path with plateau geometry"
    )
    stroke_union: set[float] = set().union(*stroke_plateau_sets)
    assert len(stroke_union) == _N, (
        f"stroke paths cover {len(stroke_union)}/{_N} distinct plateaus: "
        f"{sorted(stroke_union)}"
    )

    if require_fill:
        fill_plateau_sets = [s for s in by_kind["fill"] if s]
        assert fill_plateau_sets, (
            "expected at least one FILLED area path with real plateau geometry "
            "(fill unexpectedly dropped — a surviving stroke path is not enough)"
        )
        fill_union: set[float] = set().union(*fill_plateau_sets)
        assert len(fill_union) == _N, (
            f"filled area paths cover {len(fill_union)}/{_N} distinct plateaus: "
            f"{sorted(fill_union)}"
        )

    if per_path_single_plateau:
        for kind, d in paths:
            if kind != "stroke":
                continue
            plateaus = _path_plateaus(d)
            if not plateaus:
                continue
            assert len(plateaus) == 1, (
                f"expected exactly one plateau per disconnected band path, "
                f"got {len(plateaus)}: {sorted(plateaus)} (d={d!r})"
            )


@pytest.mark.parametrize("width", _WIDTH_SWEEP)
@pytest.mark.parametrize("connect", [True, False])
def test_line_step_band_plateau_per_value(width: int, connect: bool) -> None:
    board_rs, board_ctx = board_with_mark("line", curve="step", connect=connect)
    chart = LineChart(
        id="stepband",
        type="line",
        x="cat",
        y="val",
        query=SqlQuery(sql="SELECT 1", source="test"),
        query_name="q",
    )
    svg = _render_svg(chart, board_rs, board_ctx, float(width))
    _assert_plateau_coverage(
        svg, require_fill=False, per_path_single_plateau=not connect
    )


@pytest.mark.parametrize("width", _WIDTH_SWEEP)
def test_area_step_band_plateau_per_value(width: int) -> None:
    # Area always renders as a continuous silhouette (connect is a line-only
    # toggle) — see emitters/area.py's _apply_area_step_band.
    board_rs, board_ctx = board_with_mark("area", curve="step")
    chart = AreaChart(
        id="stepband",
        type="area",
        x="cat",
        y="val",
        query=SqlQuery(sql="SELECT 1", source="test"),
        query_name="q",
    )
    svg = _render_svg(chart, board_rs, board_ctx, float(width))
    _assert_plateau_coverage(svg, require_fill=True)
