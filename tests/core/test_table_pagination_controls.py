"""Tests for interactive table pagination controls and URL state.

Proves:
1. _resolve_visible_rows slices data by page number (not just first page).
2. render_table_svg emits a right-aligned paginator <g> when data overflows
   the page_rows or the height budget.
3. The paginator uses chevrons + a windowed sequence of page numbers, with
   the active page emphasised and disabled chevrons shown in a muted tone.
4. The chart's page variable name is used in the click handlers.
5. No paginator when all data fits or pagination is disabled.
6. Page number extracted from variables dict drives which rows render.
"""

from __future__ import annotations

import re
from collections.abc import Generator

import pytest

from dbt_charts.core.compile.config import (
    get_theme_style,
)
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style,
)
from dbt_charts.core.render.chart.table import render_table_svg as render_table_svg
from dbt_charts.core.render.controls import interactive_controls

_BOARD_STYLE = resolve_chart_style_context(get_theme_style())


def _make_data(n: int) -> list[dict[str, str]]:
    """Generate n rows of test data."""
    return [{"name": f"row_{i}", "value": str(i)} for i in range(1, n + 1)]


def _find_paginator_group(svg: str, var_name: str) -> str:
    """Return the inner SVG of the paginator <g> for the given page-var."""
    m = re.search(
        rf'<g class="dbt-paginator" data-paginator="{re.escape(var_name)}">'
        r"(.*?)</g>",
        svg,
        re.DOTALL,
    )
    assert m, f"paginator group for {var_name!r} not found"
    return m.group(1)


def _find_active_page_text(svg: str, var_name: str) -> str:
    """Return the <text> element marked as the current/active page."""
    m = re.search(
        rf'<text[^>]*data-pagination-current="{re.escape(var_name)}"[^>]*>'
        r"[^<]*</text>",
        svg,
    )
    assert m, f"active-page text for {var_name!r} not found"
    return m.group(0)


class TestResolveVisibleRowsPaging:
    """_resolve_visible_rows should respect the page parameter."""

    def test_page_1_returns_first_page(self) -> None:
        from dbt_charts.core.compile.models.style.authored import PaginationConfig
        from dbt_charts.core.render.chart.table import _resolve_visible_rows

        data = _make_data(50)
        _, visible, _, _, _, _, _ = _resolve_visible_rows(
            data,
            height=None,
            title_height=0,
            header_height=30,
            padding=10,
            row_height=24,
            bottom_padding=10,
            pagination=PaginationConfig(enabled=True, page_rows=10),
            page=1,
        )
        assert len(visible) == 10
        assert visible[0]["name"] == "row_1"
        assert visible[-1]["name"] == "row_10"

    def test_page_2_returns_second_page(self) -> None:
        from dbt_charts.core.compile.models.style.authored import PaginationConfig
        from dbt_charts.core.render.chart.table import _resolve_visible_rows

        data = _make_data(50)
        _, visible, _, _, _, _, _ = _resolve_visible_rows(
            data,
            height=None,
            title_height=0,
            header_height=30,
            padding=10,
            row_height=24,
            bottom_padding=10,
            pagination=PaginationConfig(enabled=True, page_rows=10),
            page=2,
        )
        assert len(visible) == 10
        assert visible[0]["name"] == "row_11"
        assert visible[-1]["name"] == "row_20"

    def test_last_page_partial(self) -> None:
        from dbt_charts.core.compile.models.style.authored import PaginationConfig
        from dbt_charts.core.render.chart.table import _resolve_visible_rows

        data = _make_data(25)
        _, visible, _, _, _, _, _ = _resolve_visible_rows(
            data,
            height=None,
            title_height=0,
            header_height=30,
            padding=10,
            row_height=24,
            bottom_padding=10,
            pagination=PaginationConfig(enabled=True, page_rows=10),
            page=3,
        )
        assert len(visible) == 5
        assert visible[0]["name"] == "row_21"

    def test_page_beyond_range_clamps_to_last(self) -> None:
        from dbt_charts.core.compile.models.style.authored import PaginationConfig
        from dbt_charts.core.render.chart.table import _resolve_visible_rows

        data = _make_data(25)
        _, visible, _, _, _, _, _ = _resolve_visible_rows(
            data,
            height=None,
            title_height=0,
            header_height=30,
            padding=10,
            row_height=24,
            bottom_padding=10,
            pagination=PaginationConfig(enabled=True, page_rows=10),
            page=99,
        )
        # Should clamp to last page (page 3)
        assert len(visible) == 5
        assert visible[0]["name"] == "row_21"

    def test_page_0_treated_as_page_1(self) -> None:
        from dbt_charts.core.compile.models.style.authored import PaginationConfig
        from dbt_charts.core.render.chart.table import _resolve_visible_rows

        data = _make_data(50)
        _, visible, _, _, _, _, _ = _resolve_visible_rows(
            data,
            height=None,
            title_height=0,
            header_height=30,
            padding=10,
            row_height=24,
            bottom_padding=10,
            pagination=PaginationConfig(enabled=True, page_rows=10),
            page=0,
        )
        assert visible[0]["name"] == "row_1"

    def test_grow_by_2_short_circuit_uniform_rows(self) -> None:
        """When the slot fits 22 rows at natural height and overflow vs
        page_rows=20 is within the grow-by-2 cap, render all 22 rows on one
        page with no pagination chrome — even though len(data) > page_rows.

        Regression for the case-(b) bug surfaced in playground proof:
        the layout sizer allocated room for 22 rows but the renderer used to
        cap at page_rows=20 anyway and emit pagination chrome over hidden
        rows. The short-circuit at the top of ``_resolve_visible_rows``'s
        bounded path now respects "rows fit in slot, overflow ≤ cap".
        """
        from dbt_charts.core.compile.models.style.authored import PaginationConfig
        from dbt_charts.core.render.chart.table import _resolve_visible_rows

        # Slot sized to fit exactly 22 rows + chrome at natural row_height=24:
        #   title 0 + header 30 + header_body_gap int(24*.25)=6 + pad 10
        #   + bottom 10 + 22*24=528 → total 584.
        data = _make_data(22)
        height_for_22 = 0 + 30 + 6 + 10 + 10 + 22 * 24

        _, visible, total_pages, _, _, _, eff_row_h = _resolve_visible_rows(
            data,
            height=float(height_for_22),
            title_height=0,
            header_height=30,
            padding=10,
            row_height=24,
            bottom_padding=10,
            pagination=PaginationConfig(enabled=True, page_rows=20),
            page=1,
            row_heights=None,
        )
        assert len(visible) == 22, (
            f"All 22 rows should fit on one page when slot accommodates them "
            f"(grow-by-2 short-circuit); got {len(visible)} visible. If this "
            f"fails, the bounded path is still capping at page_rows=20."
        )
        assert total_pages == 1, (
            f"No pagination chrome expected for 22-row overflow within the "
            f"grow-by-2 cap; got total_pages={total_pages}."
        )
        assert eff_row_h == 24, (
            f"Row height should NOT be squeezed when slot already fits all "
            f"rows at natural height; got {eff_row_h} (anti-dangle ran when "
            f"it shouldn't have)."
        )
        assert visible[-1]["name"] == "row_22"

    def test_grow_by_2_short_circuit_variable_rows(self) -> None:
        """Same grow-by-2 short-circuit must fire when row_heights is passed
        (wrapped or otherwise variable rows). The pre-fix renderer skipped
        anti-dangle for non-None row_heights, so this branch had no
        protection from the page_rows cap.
        """
        from dbt_charts.core.compile.models.style.authored import PaginationConfig
        from dbt_charts.core.render.chart.table import _resolve_visible_rows

        data = _make_data(22)
        # Per-row heights matching the uniform case so we can reuse the math.
        row_heights = [24] * 22
        height_for_22 = 0 + 30 + 6 + 10 + 10 + sum(row_heights)

        _, visible, total_pages, _, _, _, _ = _resolve_visible_rows(
            data,
            height=float(height_for_22),
            title_height=0,
            header_height=30,
            padding=10,
            row_height=24,
            bottom_padding=10,
            pagination=PaginationConfig(enabled=True, page_rows=20),
            page=1,
            row_heights=row_heights,
        )
        assert len(visible) == 22, (
            f"Variable-row-heights short-circuit should render all 22 rows; "
            f"got {len(visible)}."
        )
        assert total_pages == 1, (
            f"Variable-row-heights short-circuit should produce one page; "
            f"got {total_pages}."
        )

    def test_height_constrained_pages_no_row_skip(self) -> None:
        """When height limits rows below page_rows, pages still cover all rows."""
        from dbt_charts.core.compile.models.style.authored import PaginationConfig
        from dbt_charts.core.render.chart.table import _resolve_visible_rows

        data = _make_data(20)
        # page_rows=10 but height only fits ~3 rows (120 - 30 - 10 - 10 = 70 / 24 = 2)
        _, page1, total, _, _, _, _ = _resolve_visible_rows(
            data,
            height=120,
            title_height=0,
            header_height=30,
            padding=10,
            row_height=24,
            bottom_padding=10,
            pagination=PaginationConfig(enabled=True, page_rows=10),
            page=1,
        )
        _, page2, _, _, _, _, _ = _resolve_visible_rows(
            data,
            height=120,
            title_height=0,
            header_height=30,
            padding=10,
            row_height=24,
            bottom_padding=10,
            pagination=PaginationConfig(enabled=True, page_rows=10),
            page=2,
        )
        # Pages should be contiguous: page 2 starts where page 1 ended
        assert page2[0]["name"] == f"row_{len(page1) + 1}"
        # total_pages uses effective page size, not raw page_rows
        assert total > 2  # 20 rows / ~2 per page = 10 pages, not 2

    def test_height_constrained_reserves_space_for_controls(self) -> None:
        """Explicit height subtracts pagination control space from available rows."""
        from dbt_charts.core.compile.models.style.authored import PaginationConfig
        from dbt_charts.core.render.chart.table import (
            _PAGINATION_CONTROL_HEIGHT,
            _resolve_visible_rows,
        )

        data = _make_data(50)
        # Height large enough for ~10 data rows + header + padding + controls
        explicit_height = 30 + 10 + 10 + (10 * 24) + _PAGINATION_CONTROL_HEIGHT
        _, visible, total, _, _, _, _ = _resolve_visible_rows(
            data,
            height=explicit_height,
            title_height=0,
            header_height=30,
            padding=10,
            row_height=24,
            bottom_padding=10,
            pagination=PaginationConfig(enabled=True, page_rows=20),
            page=1,
        )
        # With controls reserved, visible rows should be <= 10 (not 11)
        assert len(visible) <= 10
        assert total > 1

    def test_no_page_defaults_to_first_page(self) -> None:
        """Backward compat: omitting page gives page 1 behavior."""
        from dbt_charts.core.compile.models.style.authored import PaginationConfig
        from dbt_charts.core.render.chart.table import _resolve_visible_rows

        data = _make_data(50)
        _, visible, _, _, _, _, _ = _resolve_visible_rows(
            data,
            height=None,
            title_height=0,
            header_height=30,
            padding=10,
            row_height=24,
            bottom_padding=10,
            pagination=PaginationConfig(enabled=True, page_rows=10),
        )
        assert visible[0]["name"] == "row_1"
        assert len(visible) == 10


class TestAutoShrinkOverridesTruncationFooter:
    """When pagination is enabled and the cell can't fit page_rows rows,
    the renderer must auto-shrink and paginate — never fall back to the
    "+ N more rows" truncation footer. When pagination is disabled, the
    renderer must use the table's natural height and render all rows instead.
    """

    def test_overflow_in_small_cell_paginates_not_truncates(self, make_chart) -> None:
        """30 rows, page_rows=20, cell that fits ~10 rows → paginator, no footer."""
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="autoshrink",
            style=TableChartStylePatch(pagination={"enabled": True, "page_rows": 20}),
        )
        data = _make_data(30)
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart,
            data,
            width=600,
            height=300,
            board_style=resolve_style(get_theme_style()),
        )

        assert "dbt-paginator" in svg, "small-cell overflow should paginate"
        assert "more rows" not in svg, (
            "auto-shrink path must replace the truncation footer when "
            "pagination is enabled"
        )

    def test_enabled_with_null_page_rows_auto_shrinks(self) -> None:
        """``pagination.enabled: true`` with no page_rows must still auto-shrink
        when the cell can't fit all rows. Previously the bounded path saw
        ``page_rows is None`` and silently skipped pagination, leaking the
        truncation footer despite pagination being enabled.
        """
        from dbt_charts.core.compile.models.style.authored import PaginationConfig
        from dbt_charts.core.render.chart.table import _resolve_visible_rows

        data = _make_data(30)
        _, visible, total_pages, _, _, _, _ = _resolve_visible_rows(
            data,
            height=200,
            title_height=0,
            header_height=30,
            padding=10,
            row_height=24,
            bottom_padding=10,
            pagination=PaginationConfig(enabled=True, page_rows=None),
        )
        assert len(visible) < len(data), "cell can't fit 30 rows, must page"
        assert total_pages > 1, (
            "enabled=true with overflow must produce >1 page so the renderer "
            "emits the paginator (not the truncation footer)"
        )

    def test_pagination_disabled_ignores_height_clamp_and_renders_all_rows(
        self, make_chart
    ) -> None:
        """Explicit ``pagination.enabled: false`` means no hidden rows."""
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="disabled_pagination",
            style=TableChartStylePatch(pagination={"enabled": False}),
        )
        data = _make_data(30)
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart,
            data,
            width=600,
            height=200,
            board_style=resolve_style(get_theme_style()),
        )

        assert "dbt-paginator" not in svg
        assert "more rows" not in svg
        assert "row_30" in svg

    def test_pagination_disabled_five_row_table_does_not_drop_last_row(
        self, make_chart
    ) -> None:
        """Regression for #146: a 5-row static table must not render 4 + footer."""
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="five_rows",
            style=TableChartStylePatch(pagination={"enabled": False}),
        )
        data = _make_data(5)
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart,
            data,
            width=600,
            height=150,
            board_style=resolve_style(get_theme_style()),
        )

        assert "dbt-paginator" not in svg
        assert "more rows" not in svg
        assert "row_5" in svg


class TestPaginationControlsInSvg:
    """render_table_svg should emit a right-aligned paginator.

    Visual contract: a ``<g class="dbt-paginator" data-paginator="<chart>_page">``
    group containing a leading chevron, a windowed sequence of page numbers
    (with ellipsis placeholders for hidden ranges), and a trailing chevron.
    The active page text element carries ``data-pagination-current``;
    clickable items get an invisible ``<rect>`` with
    ``onclick=updateVariable(...)`` as the hit target — the contract for a
    host that ships variables.js (dct serve, Cloud). Static exports render a
    different, JS-toggled contract (``TestStaticMultiPagePagination`` below).
    """

    @pytest.fixture(autouse=True)
    def _interactive_host(self) -> Generator[None]:
        with interactive_controls(True):
            yield

    def test_paginator_group_present_when_multi_page(self, make_chart) -> None:
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="details",
            style=TableChartStylePatch(pagination={"enabled": True, "page_rows": 5}),
        )
        data = _make_data(20)
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart,
            data,
            width=600,
            board_style=resolve_style(get_theme_style()),
        )

        inner = _find_paginator_group(svg, "details_page")
        assert "‹" in inner  # leading chevron
        assert "›" in inner  # trailing chevron
        # No "Page X of Y" prose — bare numbers + chevrons + ellipses only.
        assert "Page " not in inner

    def test_no_pagination_controls_when_single_page(self, make_chart) -> None:
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="small_table",
            style=TableChartStylePatch(pagination={"enabled": True, "page_rows": 50}),
        )
        data = _make_data(10)
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart,
            data,
            width=600,
            board_style=resolve_style(get_theme_style()),
        )

        assert "small_table_page" not in svg
        assert "dbt-paginator" not in svg

    def test_no_pagination_controls_when_disabled(self, make_chart) -> None:
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="no_pages",
            style=TableChartStylePatch(pagination={"enabled": False}),
        )
        data = _make_data(100)
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart,
            data,
            width=600,
            board_style=resolve_style(get_theme_style()),
        )

        assert "no_pages_page" not in svg
        assert "dbt-paginator" not in svg

    def test_page_from_variables_shows_correct_data(self, make_chart) -> None:
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="paged",
            style=TableChartStylePatch(pagination={"enabled": True, "page_rows": 5}),
        )
        data = _make_data(20)
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart,
            data,
            width=600,
            variables={"paged_page": "2"},
            board_style=resolve_style(get_theme_style()),
        )

        assert "row_6" in svg
        assert "row_10" in svg
        # Page 1 rows should NOT be visible (use word boundary to avoid
        # matching row_1 inside row_10/row_11/etc.)
        assert not re.search(r"\brow_1\b", svg)
        assert "row_5" not in svg

    def test_clickable_items_call_update_variable(self, make_chart) -> None:
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="nav_test",
            style=TableChartStylePatch(pagination={"enabled": True, "page_rows": 5}),
        )
        data = _make_data(20)
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart,
            data,
            width=600,
            board_style=resolve_style(get_theme_style()),
        )
        inner = _find_paginator_group(svg, "nav_test_page")

        rects = re.findall(r"<rect[^>]*/>", inner)
        clickable = [r for r in rects if "updateVariable" in r and "nav_test_page" in r]
        assert clickable, "no clickable hit-rects in paginator"
        for rect in clickable:
            assert 'fill="transparent"' in rect
            assert "cursor: pointer" in rect
            assert 'pointer-events="all"' in rect

    def test_first_page_prev_chevron_is_disabled(self, make_chart) -> None:
        """On page 1 the prev chevron renders in the disabled tone with no
        click handler — disabled state is signalled by colour, not opacity."""
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="first_page",
            style=TableChartStylePatch(pagination={"enabled": True, "page_rows": 5}),
        )
        data = _make_data(20)
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart,
            data,
            width=600,
            board_style=resolve_style(get_theme_style()),
        )
        inner = _find_paginator_group(svg, "first_page_page")

        prev = re.search(
            r'<text[^>]*data-paginator-role="prev"[^>]*>[^<]*</text>', inner
        )
        assert prev, "prev chevron <text> not found"
        assert "onclick" not in prev.group(0)
        assert not re.search(r"updateVariable\('first_page_page', '0'\)", inner), (
            "disabled prev should not emit a click handler"
        )

    def test_last_page_next_chevron_is_disabled(self, make_chart) -> None:
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="last_page",
            style=TableChartStylePatch(pagination={"enabled": True, "page_rows": 5}),
        )
        data = _make_data(20)
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart,
            data,
            width=600,
            variables={"last_page_page": "4"},
            board_style=resolve_style(get_theme_style()),
        )

        assert "row_16" in svg
        assert "row_20" in svg
        inner = _find_paginator_group(svg, "last_page_page")
        next_ch = re.search(
            r'<text[^>]*data-paginator-role="next"[^>]*>[^<]*</text>', inner
        )
        assert next_ch, "next chevron <text> not found"
        assert "onclick" not in next_ch.group(0)

    def test_active_page_has_emphasis_weight(self, make_chart) -> None:
        """Current page renders at the theme's active weight (default 600)
        and is marked with ``data-pagination-current``. Other page numbers
        render at the inactive weight (default 400)."""
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="indicator",
            style=TableChartStylePatch(pagination={"enabled": True, "page_rows": 10}),
        )
        data = _make_data(30)
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart,
            data,
            width=600,
            variables={"indicator_page": "2"},
            board_style=resolve_style(get_theme_style()),
        )

        active = _find_active_page_text(svg, "indicator_page")
        assert 'font-weight="600"' in active
        m = re.search(r">(\s*\d+\s*)</text>", active)
        assert m and m.group(1).strip() == "2"

        inner = _find_paginator_group(svg, "indicator_page")
        inactive_texts = [
            t
            for t in re.findall(r"<text[^>]*>[^<]*</text>", inner)
            if "data-pagination-current" not in t
            and re.search(r">\s*[13]\s*</text>", t)
        ]
        assert inactive_texts, "no inactive page-number text elements found"
        for t in inactive_texts:
            assert 'font-weight="400"' in t

    def test_paginator_uses_tabular_figures(self, make_chart) -> None:
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="tab",
            style=TableChartStylePatch(pagination={"enabled": True, "page_rows": 5}),
        )
        data = _make_data(20)
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart,
            data,
            width=600,
            board_style=resolve_style(get_theme_style()),
        )
        inner = _find_paginator_group(svg, "tab_page")
        text_elems = re.findall(r"<text[^>]*>[^<]*</text>", inner)
        assert text_elems
        for t in text_elems:
            assert "tabular-nums" in t

    def test_paginator_right_anchored(self, make_chart) -> None:
        """The paginator hugs the right edge of the table."""
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="ra",
            style=TableChartStylePatch(pagination={"enabled": True, "page_rows": 5}),
        )
        data = _make_data(20)
        table_width = 600.0
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart,
            data,
            width=table_width,
            board_style=resolve_style(get_theme_style()),
        )
        inner = _find_paginator_group(svg, "ra_page")
        xs = [float(m.group(1)) for m in re.finditer(r'<text x="([\d.]+)"', inner)]
        assert xs, "no paginator text centers found"
        rightmost = max(xs)
        assert table_width - 40.0 <= rightmost <= table_width, (
            f"rightmost paginator item at x={rightmost} not anchored to "
            f"table_width={table_width}"
        )


class TestAntiDangleSqueeze:
    """Anti-dangle: collapse a 1-2 row trailing page via a small row_height squeeze."""

    def test_unbounded_single_row_dangler_collapses_to_one_page(self) -> None:
        """8 rows with page_rows=7: 1-row dangler should collapse to single page."""
        from dbt_charts.core.compile.models.style.authored import PaginationConfig
        from dbt_charts.core.render.chart.table import _resolve_visible_rows

        data = _make_data(8)
        row_height = 32
        _, visible, total_pages, _, _, _, out_row_height = _resolve_visible_rows(
            data,
            height=None,
            title_height=0,
            header_height=30,
            padding=10,
            row_height=row_height,
            bottom_padding=10,
            pagination=PaginationConfig(enabled=True, page_rows=7),
        )
        assert total_pages == 1, f"expected 1 page, got {total_pages}"
        assert len(visible) == 8, f"expected all 8 rows, got {len(visible)}"
        assert out_row_height < row_height, "row_height should be squeezed"
        assert out_row_height >= 20, (
            "squeezed row_height must not fall below 20px floor"
        )

    def test_unbounded_large_overflow_does_not_collapse(self) -> None:
        """20 rows with page_rows=7: 6-row overflow exceeds max_overflow=2, no collapse."""
        from dbt_charts.core.compile.models.style.authored import PaginationConfig
        from dbt_charts.core.render.chart.table import _resolve_visible_rows

        data = _make_data(20)
        row_height = 32
        _, visible, total_pages, _, _, _, out_row_height = _resolve_visible_rows(
            data,
            height=None,
            title_height=0,
            header_height=30,
            padding=10,
            row_height=row_height,
            bottom_padding=10,
            pagination=PaginationConfig(enabled=True, page_rows=7),
        )
        assert total_pages > 1, "large overflow must NOT collapse"
        assert out_row_height == row_height, (
            "row_height must be unchanged when squeeze doesn't fire"
        )

    def test_squeeze_floor_respected_at_20px(self) -> None:
        """Many rows in tight height: geometry forces squeeze below floor, pagination must hold."""
        from dbt_charts.core.compile.models.style.authored import PaginationConfig
        from dbt_charts.core.render.chart.table import (
            _resolve_visible_rows,
        )

        # With row_height=24 and a very tight height, the geometry-driven
        # squeezed value would drop below 20px.  The anti-dangle heuristic
        # must refuse to fire and leave pagination intact.
        data = _make_data(8)
        row_height = 24
        # height chosen so 7 rows fit at 24px, but squeezing to fit all 8
        # would require 24 * (7/8) = 21px — just above the floor.
        # To force a floor violation use a tighter height so geometry gives <20px.
        # available ≈ 7 * row_height (no ctrl height because we probe without).
        # We want available / len(data) < 20px → available < 160px → pick 150.
        tight_available = 150
        height = (
            tight_available + 30 + int(24 * 0.25) + 10 + 10
        )  # header_height + gap + padding + bottom
        _, _, total_pages, _, _, _, out_row_height = _resolve_visible_rows(
            data,
            height=float(height),
            title_height=0,
            header_height=30,
            padding=10,
            row_height=row_height,
            bottom_padding=10,
            pagination=PaginationConfig(enabled=True, page_rows=7),
        )
        # The squeezed value would be below the floor, so collapse must NOT fire.
        # total_pages > 1 proves pagination is the honest answer (squeeze gave up).
        assert total_pages > 1, "floor should prevent collapse"
        # row_height unchanged proves no squeeze occurred — floor blocked the fire.
        assert out_row_height == row_height, (
            "row_height must be unchanged when floor blocks squeeze"
        )

    def test_two_row_overflow_collapses_at_boundary(self) -> None:
        """14 rows with page_rows=12: 2-row overflow at the exact _ANTI_DANGLE_MAX_OVERFLOW boundary.

        The worksheet advertises 'up to 2-row overflow collapses'. This test pins that
        boundary from the collapsing side. Parameters satisfy both gates:
          overflow = 14 - 12 = 2 == _ANTI_DANGLE_MAX_OVERFLOW
          squeeze_ratio = 12/14 ≈ 0.857 >= (1 - _ANTI_DANGLE_MAX_SQUEEZE = 0.85)
        """
        from dbt_charts.core.compile.models.style.authored import PaginationConfig
        from dbt_charts.core.render.chart.table import (
            _ANTI_DANGLE_MAX_SQUEEZE,
            _ANTI_DANGLE_MIN_ROW_H,
            _resolve_visible_rows,
        )

        data = _make_data(14)
        row_height = 28
        _, visible, total_pages, _, _, _, out_row_height = _resolve_visible_rows(
            data,
            height=None,
            title_height=0,
            header_height=30,
            padding=10,
            row_height=row_height,
            bottom_padding=10,
            pagination=PaginationConfig(enabled=True, page_rows=12),
        )
        assert total_pages == 1, "2-row overflow must collapse to a single page"
        assert len(visible) == 14, f"all 14 rows must be visible, got {len(visible)}"
        # Squeeze must be within the 15% budget and above the 20px floor.
        assert out_row_height < row_height, "row_height must be squeezed"
        assert out_row_height >= _ANTI_DANGLE_MIN_ROW_H, (
            "squeezed value must not fall below 20px"
        )
        assert out_row_height >= int(row_height * (1.0 - _ANTI_DANGLE_MAX_SQUEEZE)), (
            "squeeze must not exceed 15%"
        )


class TestPaginationViewBoxContainment:
    """Pagination controls must render within the SVG viewBox.

    Regression: when the caller passes an explicit height that doesn't
    account for pagination, the renderer previously skipped reserving
    pagination_control_height and drew pagination below the viewBox, so
    the board layout clipped the control text. The renderer must always
    reserve space when pagination will fire — height-limited or
    page_rows-limited — and shrink visible rows accordingly.
    """

    def _pagination_text_y(self, svg: str, var_name: str) -> float:
        """Return the y-baseline of the active page text element, or NaN."""
        import math

        m = re.search(
            rf'<text x="[^"]+" y="([\d.]+)"[^>]*data-pagination-current="'
            rf'{re.escape(var_name)}"',
            svg,
        )
        return float(m.group(1)) if m else math.nan

    def _viewbox_height(self, svg: str) -> float:
        m = re.search(r'<svg[^>]+viewBox="0 0 [\d.]+ ([\d.]+)"', svg)
        assert m, "SVG root viewBox not found"
        return float(m.group(1))

    def test_height_limited_pagination_fits_in_viewbox(self, make_chart) -> None:
        """Height forces pagination (data > max_rows, data <= page_rows).

        Leaderboard-shaped case: 12 rows, page_rows=20 (default), but the
        allotted height only fits 11 rows + pagination. Pagination must
        appear and stay within viewBox.
        """
        from dbt_charts.core.render.chart.table import (
            render_table_svg as render_table_svg,
        )

        chart = make_chart("table", id="ht_lim")
        chart.title = "Most Visited Museums"
        chart.subtitle = "C1 — Auto-sized, no column config"
        data = _make_data(12)
        # Use a height tight enough to force pagination regardless of the
        # current default row height (densification shrinks row.height
        # over time). 200px leaves room for only a few rows after
        # title/subtitle/header — well below 12.
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart,
            data,
            width=544,
            height=200,
            board_style=resolve_style(get_theme_style()),
        )

        # Confirm pagination actually fired (otherwise test is vacuous).
        # The paginator group is only emitted when there's >1 page, so its
        # presence is enough — we don't have to extract the page count.
        assert "dbt-paginator" in svg, "pagination expected for 12 rows in 200px"

        y = self._pagination_text_y(svg, "ht_lim_page")
        vb_h = self._viewbox_height(svg)
        # Pagination text baseline + descender headroom (~3px for 11px font)
        # must fit within the viewBox. A small margin (1px) guards against
        # sub-pixel drift from font metrics.
        assert y + 3 <= vb_h, (
            f"pagination text baseline y={y} + descender 3 exceeds viewBox "
            f"height {vb_h}; controls are clipped"
        )

    def test_pagesize_limited_pagination_fits_in_viewbox(self, make_chart) -> None:
        """Page_size forces pagination (data > page_rows) — the case the old
        code handled. This guard prevents regression."""
        from dbt_charts.core.render.chart.table import (
            render_table_svg as render_table_svg,
        )

        chart = make_chart(
            "table",
            id="ps_lim",
            style={"pagination": {"enabled": True, "page_rows": 5}},
        )
        data = _make_data(20)
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart,
            data,
            width=544,
            height=400,
            board_style=resolve_style(get_theme_style()),
        )

        assert "dbt-paginator" in svg
        y = self._pagination_text_y(svg, "ps_lim_page")
        vb_h = self._viewbox_height(svg)
        assert y + 3 <= vb_h


class TestStaticMultiPagePagination:
    """A static export (no interactive host — the default, matching ``dft
    render``) must ship pagination controls that actually work: every page's
    rows are pre-rendered into a toggle group and a small inline script
    (table_pagination.js) flips visibility on click, instead of an
    ``onclick=updateVariable(...)`` handler with no runtime present to answer
    it (ERR: ReferenceError when the exported HTML/SVG is opened standalone).

    ``render_table_svg`` called directly (as every test in this file does)
    runs outside ``interactive_controls(True)`` by default — this class pins
    that default, non-interactive behavior.
    """

    def test_no_update_variable_onclick_in_static_export(self, make_chart) -> None:
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="static1",
            style=TableChartStylePatch(pagination={"enabled": True, "page_rows": 5}),
        )
        data = _make_data(20)
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart, data, width=600, board_style=resolve_style(get_theme_style())
        )

        assert "updateVariable" not in svg, (
            "a static export must never emit a call to a runtime "
            "(variables.js) it does not ship"
        )
        assert 'data-dbt-page-target="2"' in svg

    def test_every_page_rows_present_toggled_by_display(self, make_chart) -> None:
        """All 4 pages' rows are in the DOM; only the current page is visible."""
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="static2",
            style=TableChartStylePatch(pagination={"enabled": True, "page_rows": 5}),
        )
        data = _make_data(20)  # 4 pages of 5
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart, data, width=600, board_style=resolve_style(get_theme_style())
        )

        for row_name in ("row_1", "row_10", "row_15", "row_20"):
            assert row_name in svg, f"{row_name} missing — not every page was rendered"

        groups = re.findall(
            r'<g class="dbt-table-page" data-dbt-table-page="static2" '
            r'data-page="(\d)" style="display:([^"]*)">',
            svg,
        )
        assert [p for p, _ in groups] == ["1", "2", "3", "4"]
        displays = dict(groups)
        assert displays["1"] == ""
        assert displays["2"] == "none"
        assert displays["3"] == "none"
        assert displays["4"] == "none"

    def test_variables_page_selects_initially_visible_group(self, make_chart) -> None:
        """A variables-supplied page still picks which pre-rendered group starts visible."""
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="static3",
            style=TableChartStylePatch(pagination={"enabled": True, "page_rows": 5}),
        )
        data = _make_data(20)
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart,
            data,
            width=600,
            variables={"static3_page": "3"},
            board_style=resolve_style(get_theme_style()),
        )

        groups = dict(
            re.findall(
                r'data-dbt-table-page="static3" data-page="(\d)" style="display:([^"]*)"',
                svg,
            )
        )
        assert groups["3"] == ""
        assert groups["1"] == "none"

    def test_pagination_script_embedded_when_multi_page(self, make_chart) -> None:
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="static4",
            style=TableChartStylePatch(pagination={"enabled": True, "page_rows": 5}),
        )
        data = _make_data(20)
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart, data, width=600, board_style=resolve_style(get_theme_style())
        )

        assert "<script" in svg
        assert "data-dbt-page-target" in svg
        assert "data-dbt-table-page" in svg

    def test_no_script_when_single_page(self, make_chart) -> None:
        """A table that fits on one page ships no pagination script at all."""
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="static5",
            style=TableChartStylePatch(pagination={"enabled": True, "page_rows": 50}),
        )
        data = _make_data(10)
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart, data, width=600, board_style=resolve_style(get_theme_style())
        )

        assert "<script" not in svg
        assert "dbt-table-page" not in svg

    def test_pre_rendered_pages_capped_regardless_of_total_rows(
        self, make_chart
    ) -> None:
        """Export size must not scale with total row count.

        A table whose real page count exceeds the static-export cap only
        pre-renders up to the cap; rows past it are never drawn, and the
        paginator itself never links to an unrendered page — clicking a
        capped-out target would otherwise blank the table (JS finds no
        matching toggle group)."""
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )
        from dbt_charts.core.render.chart.table import _STATIC_MULTI_PAGE_MAX_PAGES

        n_rows = (_STATIC_MULTI_PAGE_MAX_PAGES + 5) * 5
        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="static_cap",
            style=TableChartStylePatch(pagination={"enabled": True, "page_rows": 5}),
        )
        data = _make_data(n_rows)
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart, data, width=600, board_style=resolve_style(get_theme_style())
        )

        groups = re.findall(r'data-dbt-table-page="static_cap" data-page="(\d+)"', svg)
        assert [int(p) for p in groups] == list(
            range(1, _STATIC_MULTI_PAGE_MAX_PAGES + 1)
        )
        assert f"row_{n_rows}" not in svg, "rows past the cap must never render"

        targets = {int(t) for t in re.findall(r'data-dbt-page-target="(\d+)"', svg)}
        assert max(targets) <= _STATIC_MULTI_PAGE_MAX_PAGES, (
            "paginator must never link to a page beyond what was pre-rendered"
        )
        assert "static export" in svg.lower(), (
            "the artifact itself must state that pages were cut, not just "
            "silently omit them"
        )

    def test_no_cap_note_when_total_pages_within_cap(self, make_chart) -> None:
        """A table whose real page count fits the cap gets no truncation note."""
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="static_uncapped",
            style=TableChartStylePatch(pagination={"enabled": True, "page_rows": 5}),
        )
        data = _make_data(20)  # 4 pages — well under the cap
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart, data, width=600, board_style=resolve_style(get_theme_style())
        )

        assert "static export" not in svg.lower()

    def test_summary_gap_sized_from_worst_page_not_current_page(
        self, make_chart
    ) -> None:
        """``table_height`` must budget for whichever rendered page needs the
        summary-row breathing gap, not just the page ``visible_data`` happens
        to hold.

        Bug: in the static multi-page branch every page paints its own
        row-role transitions independently, but the sizing pass only counted
        gaps on the current (default: first) page. A totals row landing on a
        later page painted below the table's own background rect — nothing
        here reserved room for it.
        """
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )

        # page_rows=5 -> 3 pages of 5. The totals row is the very last row,
        # so it lands on page 3 alone; pages 1-2 have no role transition.
        n_rows = 15
        data_with_summary = [
            {"name": f"row_{i}", "value": str(i), "kind": "value"}
            for i in range(1, n_rows)
        ]
        data_with_summary.append({"name": "Total", "value": "999", "kind": "summary"})
        data_without_summary = [
            {"name": f"row_{i}", "value": str(i), "kind": "value"}
            for i in range(1, n_rows + 1)
        ]

        def _render(rows: list[dict[str, str]]) -> str:
            chart = make_chart(
                "table",
                x=None,
                y=None,
                id="static_gap",
                style=TableChartStylePatch(
                    pagination={"enabled": True, "page_rows": 5},
                    row={"role": "kind"},
                ),
            )
            resolved = resolve(chart, rows, chart_style_context=_BOARD_STYLE)
            return render_table_svg(
                resolved, rows, width=600, board_style=resolve_style(get_theme_style())
            )

        def _svg_height(svg: str) -> float:
            m = re.search(r'<svg[^>]+height="([^"]+)"', svg)
            assert m, "SVG must have a height attribute"
            return float(m.group(1))

        height_with_summary = _svg_height(_render(data_with_summary))
        height_without_summary = _svg_height(_render(data_without_summary))

        rs = resolve_style(get_theme_style())
        summary_gap = int(rs.chart_defaults.table.row.height * 0.4)

        assert height_with_summary - height_without_summary == summary_gap, (
            f"table_height must grow by the page-3 summary gap ({summary_gap}px) "
            f"regardless of which page is being sized; got a "
            f"{height_with_summary - height_without_summary}px delta"
        )


class TestStripPaginationChrome:
    """PNG/PDF (and any other rasterizer) must not show dead pagination controls.

    They rasterize the same board SVG the static-multi-page path draws, but
    can never run ``table_pagination.js`` — the visible page's paginator
    would look clickable and do nothing. ``strip_pagination_chrome`` removes
    that one ``<g>`` before the SVG is handed to a rasterizer; the rows stay.
    """

    def test_removes_paginator_group_keeps_rows(self, make_chart) -> None:
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )
        from dbt_charts.core.render.chart.table import strip_pagination_chrome

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="raster1",
            style=TableChartStylePatch(pagination={"enabled": True, "page_rows": 5}),
        )
        data = _make_data(20)
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart, data, width=600, board_style=resolve_style(get_theme_style())
        )
        assert "dbt-paginator" in svg  # sanity: chrome is present pre-strip

        stripped = strip_pagination_chrome(svg)

        # The visible, clickable-looking markup is gone. The pagination
        # script's own inert source text (never executed by a rasterizer)
        # is left alone, same as chart_interactivity.js always is — a
        # <script> element paints no pixels, so it isn't the dead-looking
        # affordance this guards against.
        assert "dbt-paginator" not in stripped
        assert "row_1" in stripped, "page-1 rows must survive stripping"

    def test_no_op_on_single_page_table(self, make_chart) -> None:
        from dbt_charts.core.compile.models.style.authored import (
            TableChartStylePatch,
        )
        from dbt_charts.core.render.chart.table import strip_pagination_chrome

        chart = make_chart(
            "table",
            x=None,
            y=None,
            id="raster2",
            style=TableChartStylePatch(pagination={"enabled": True, "page_rows": 50}),
        )
        data = _make_data(10)
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart, data, width=600, board_style=resolve_style(get_theme_style())
        )

        assert strip_pagination_chrome(svg) == svg
