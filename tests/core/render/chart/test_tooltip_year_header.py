"""Regression: a year-shaped integer x's structured-tooltip header must render
the year, not a raw epoch-millisecond integer.

Root cause (confirmed on a real render of the playground's bump chart, x:
``2019 + y`` -- a plain integer year, color-coded ranks): the base cartesian
family emitters (bar/line/area) run ``normalize_labeled_temporal`` on their own
copy of the data before building the x encoding -- for a year-shaped integer
column this rewrites each value to an ISO date string, and Vega-Lite then
encodes that field as ``type: temporal`` (with a ``timeUnit``), coercing every
runtime reference to that field -- INCLUDING our own structured-tooltip
``description`` expression's ``datum[field]`` -- to its internal epoch-ms
representation.

``StructuredTooltipFeature`` (``features/structured_tooltip.py``), however,
reads its OWN fresh copy of the rows straight from ``chart_rows(chart,
datasets)`` -- never the emitter's mutated copy (deliberately, so a sibling
gap-filled/non-gap-filled layer can't leak into this decision; see the module
docstring). ``header_tooltip_field`` (``emitters/_tooltip.py``) then infers the
header's kind from that UNNORMALIZED data: a plain int column classifies as
"quantitative", never reaches the temporal branch, and falls through to a raw
``datum[field]`` passthrough -- which Vega then evaluates against its
internally-coerced (epoch-ms) representation of that same field, producing the
observed ``1546300800000``-style header.

Fix: ``_cartesian_roles`` (``features/structured_tooltip.py``) runs the same
``normalize_labeled_temporal`` canonicalization on its own header data before
calling ``header_tooltip_field`` -- the exact same primitive the emitter
already ran (successfully, on the same field, earlier in this same render
pass) to decide the x encoding, so the header's kind decision can no longer
diverge from it.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from dbt_charts.core.compile.config import reset_config
from dbt_charts.core.compile.models.chart.authored._layer import LineLayer
from dbt_charts.core.compile.models.chart.normalized import (
    AreaChart,
    BarChart,
    LineChart,
)
from dbt_charts.core.render.chart.emitters._tooltip import ROLE_HEADER
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

_EPOCH_MS_RE = re.compile(r"\b1\d{12}\b")


@pytest.fixture(autouse=True)
def reset():
    reset_config()
    yield
    reset_config()


def _svg_aria_labels(spec: dict[str, Any]) -> list[str]:
    import vl_convert as vlc

    svg = vlc.vegalite_to_svg(spec)
    return re.findall(r'aria-label="([^"]+)"', svg)


def _structured_tooltip_labels(labels: list[str]) -> list[str]:
    """Data-mark labels only -- excludes Vega's own axis/legend descriptions,
    which legitimately narrate the domain in whatever form the scale carries
    (e.g. an ordinal x-axis's own ISO-date domain values) and are not this
    bug's concern."""
    return [lb for lb in labels if lb.startswith(ROLE_HEADER)]


def _headline_years(labels: list[str]) -> set[str]:
    """The bare header value of each structured label.

    Asserting on this set rather than on the absence of an epoch/ISO pattern
    is what stops a header of "1970" -- the epoch rendered as a year, which is
    exactly what a half-fix would produce -- from passing silently.
    """
    return {lb.lstrip(ROLE_HEADER).split(";")[0].strip() for lb in labels}


_BUMP_DATA = [
    {"year": 2019, "rank": 3, "entity": "Region A"},
    {"year": 2020, "rank": 1, "entity": "Region A"},
    {"year": 2021, "rank": 2, "entity": "Region A"},
    {"year": 2019, "rank": 1, "entity": "Region B"},
    {"year": 2020, "rank": 2, "entity": "Region B"},
    {"year": 2021, "rank": 3, "entity": "Region B"},
]


def test_line_year_x_header_renders_year_not_epoch_ms():
    """A year-shaped integer x's tooltip header must read '2019', not an epoch int."""
    chart = LineChart(
        id="bump",
        type="line",
        source_path="charts.bump",
        x="year",
        y="rank",
        color="entity",
    )
    spec = generate_vega_lite_spec(chart, _BUMP_DATA, width=400)
    labels = _structured_tooltip_labels(_svg_aria_labels(spec))
    assert labels, "Expected at least one structured-tooltip aria-label in rendered SVG"

    epoch_labels = [lb for lb in labels if _EPOCH_MS_RE.search(lb)]
    assert not epoch_labels, (
        f"Expected no aria-label to contain a raw epoch-ms header; "
        f"found: {epoch_labels!r}\nAll labels: {labels!r}"
    )
    assert _headline_years(labels) == {"2019", "2020", "2021"}, (
        f"Expected the fixture's own years as headers; got: {labels!r}"
    )


_BAR_YEAR_DATA = [
    {"year": 2019, "revenue": 100, "segment": "SMB"},
    {"year": 2020, "revenue": 150, "segment": "SMB"},
    {"year": 2019, "revenue": 80, "segment": "Enterprise"},
    {"year": 2020, "revenue": 120, "segment": "Enterprise"},
]


_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def test_bar_year_x_header_renders_year_not_iso_date():
    """The same shared cartesian header path (bar) must not regress either.

    Bar's small-cardinality year domain resolves an ordinal (not temporal) x
    scale, so Vega never coerces the field to epoch-ms -- the un-fixed bug's
    raw ``datum[field]`` passthrough instead surfaces the emitter's OWN
    canonicalized ISO date string (``2019-01-01``) rather than the bare year
    the axis itself labels.
    """
    chart = BarChart(
        id="rev",
        type="bar",
        source_path="charts.rev",
        x="year",
        y="revenue",
        color="segment",
    )
    spec = generate_vega_lite_spec(chart, _BAR_YEAR_DATA, width=400)
    labels = _structured_tooltip_labels(_svg_aria_labels(spec))
    assert labels, "Expected at least one structured-tooltip aria-label in rendered SVG"

    epoch_labels = [lb for lb in labels if _EPOCH_MS_RE.search(lb)]
    assert not epoch_labels, (
        f"Expected no aria-label to contain a raw epoch-ms header; "
        f"found: {epoch_labels!r}\nAll labels: {labels!r}"
    )
    iso_date_labels = [lb for lb in labels if _ISO_DATE_RE.search(lb)]
    assert not iso_date_labels, (
        f"Expected no aria-label to contain a raw ISO date header; "
        f"found: {iso_date_labels!r}\nAll labels: {labels!r}"
    )
    # Absence alone is a weak assertion -- a header rendering "1970" (the epoch
    # itself) satisfies it. Pin that the fixture's own years are what shows.
    assert _headline_years(labels) == {"2019", "2020"}, (
        f"Expected the fixture's own years as headers; got: {labels!r}"
    )


def test_area_year_x_header_renders_year_not_epoch_ms():
    """Area shares the cartesian header path and was affected identically.

    Probing every x-consuming surface with a year-shaped integer x (line, bar,
    area, scatter, value labels, an attached support table, and a combo
    overlay) showed six of the seven emitting a bad header before the fix --
    the defect was never specific to the one chart it was reported on. Area
    resolves a temporal scale like line, so its pre-fix header was the epoch
    integer rather than bar's ISO string.
    """
    chart = AreaChart(
        id="area",
        type="area",
        source_path="charts.area",
        x="year",
        y="revenue",
        color="segment",
    )
    spec = generate_vega_lite_spec(chart, _BAR_YEAR_DATA, width=400)
    labels = _structured_tooltip_labels(_svg_aria_labels(spec))
    assert labels, "Expected at least one structured-tooltip aria-label in rendered SVG"

    bad = [lb for lb in labels if _EPOCH_MS_RE.search(lb) or _ISO_DATE_RE.search(lb)]
    assert not bad, (
        f"Expected no aria-label headlined with a raw epoch-ms or ISO date; "
        f"found: {bad!r}\nAll labels: {labels!r}"
    )
    assert _headline_years(labels) == {"2019", "2020"}, (
        f"Expected the fixture's own years as headers; got: {labels!r}"
    )


def test_combo_overlay_header_matches_its_base_for_the_same_x():
    """A combo overlay's header must agree with its base's, string for string.

    ``chart_interactivity.js`` folds base and overlay marks into one x-unified
    bubble by matching header STRINGS, not field identity (see
    ``header_tooltip_field``'s docstring). The overlay layer builds its own
    header in ``emitters/_overlay.py``, so a fix applied only to the base path
    would split every year into two bubbles instead of one -- a worse failure
    than the raw integer it replaced. Pin the agreement, not just the format.
    """
    chart = BarChart(
        id="combo",
        type="bar",
        source_path="charts.combo",
        x="year",
        y="revenue",
        layers=[LineLayer(type="line", y="target", label="Target")],
    )
    data = [
        {"year": 2019, "revenue": 100, "target": 90},
        {"year": 2020, "revenue": 150, "target": 130},
        {"year": 2021, "revenue": 120, "target": 140},
    ]
    spec = generate_vega_lite_spec(chart, data, width=400)
    labels = _structured_tooltip_labels(_svg_aria_labels(spec))
    assert labels, "Expected at least one structured-tooltip aria-label in rendered SVG"

    bad = [lb for lb in labels if _EPOCH_MS_RE.search(lb) or _ISO_DATE_RE.search(lb)]
    assert not bad, (
        f"Expected no aria-label headlined with a raw epoch-ms or ISO date; "
        f"found: {bad!r}\nAll labels: {labels!r}"
    )
    assert _headline_years(labels) == {"2019", "2020", "2021"}, (
        f"Expected the fixture's own years as headers; got: {labels!r}"
    )

    # Every header string must be shared by BOTH the base and the overlay --
    # a header only one of them emits means the bubble would split.
    by_header: dict[str, set[str]] = {}
    for lb in labels:
        parts = lb.split(";")
        header = parts[0].lstrip(ROLE_HEADER).strip()
        series = parts[1].strip() if len(parts) > 1 else ""
        by_header.setdefault(header, set()).add(series)
    unshared = {h: s for h, s in by_header.items() if len(s) < 2}
    assert not unshared, (
        f"Every x header should be emitted by both the base and the overlay so "
        f"the two fold into one bubble; these carry only one series: {unshared!r}"
    )
