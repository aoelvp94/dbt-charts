"""Windowing algorithm for the table paginator.

Rules with the defaults (siblingCount=1, boundaryCount=1):

- Always show: page 1, page total, and ±1 around the current page.
- Any gap between consecutive must-show pages collapses to a single
  ``"…"`` regardless of gap size — there is NO small-gap expansion.
  That keeps edge states like page 1 of 8 compact (``1 2 … 8``) instead
  of running out to 5-in-a-row.
"""

from __future__ import annotations


class TestPaginatorWindow:
    def test_small_total_shows_all_pages(self) -> None:
        from dbt_charts.core.render.chart.table import _paginator_window

        assert _paginator_window(page=2, total=3) == [1, 2, 3]

    def test_five_pages_all_visible(self) -> None:
        """Tiny totals where every page is in the must-show set."""
        from dbt_charts.core.render.chart.table import _paginator_window

        # page=3 of 5 with sibling=1 covers pages 2,3,4; plus boundaries 1,5
        # → all five pages contiguous, no ellipsis.
        assert _paginator_window(page=3, total=5) == [1, 2, 3, 4, 5]

    def test_eight_pages_first_page_compact(self) -> None:
        """At page 1 of 8 we get ``1 2 … 8`` — the sibling 0 clips out, and
        the gap to 8 collapses to a single ellipsis."""
        from dbt_charts.core.render.chart.table import _paginator_window

        assert _paginator_window(page=1, total=8) == [1, 2, "…", 8]

    def test_eight_pages_middle_double_ellipsis(self) -> None:
        """At page 4 of 8 the left gap is exactly one hidden page (2) — it
        still ellipsizes. No expansion to a 5-in-a-row sequence."""
        from dbt_charts.core.render.chart.table import _paginator_window

        assert _paginator_window(page=4, total=8) == [1, "…", 3, 4, 5, "…", 8]

    def test_eight_pages_last_page_compact(self) -> None:
        from dbt_charts.core.render.chart.table import _paginator_window

        assert _paginator_window(page=8, total=8) == [1, "…", 7, 8]

    def test_twelve_pages_middle_double_ellipsis(self) -> None:
        from dbt_charts.core.render.chart.table import _paginator_window

        # The canonical compact layout: ‹ 1 … 4 5 6 … 12 ›
        assert _paginator_window(page=5, total=12) == [1, "…", 4, 5, 6, "…", 12]

    def test_twelve_pages_first_page_right_ellipsis_only(self) -> None:
        from dbt_charts.core.render.chart.table import _paginator_window

        assert _paginator_window(page=1, total=12) == [1, 2, "…", 12]

    def test_twelve_pages_last_page_left_ellipsis_only(self) -> None:
        from dbt_charts.core.render.chart.table import _paginator_window

        assert _paginator_window(page=12, total=12) == [1, "…", 11, 12]

    def test_fifty_pages_mid_window(self) -> None:
        from dbt_charts.core.render.chart.table import _paginator_window

        assert _paginator_window(page=25, total=50) == [
            1,
            "…",
            24,
            25,
            26,
            "…",
            50,
        ]

    def test_active_page_always_in_window(self) -> None:
        """The current page must appear in the returned sequence for any
        valid page/total combination."""
        from dbt_charts.core.render.chart.table import _paginator_window

        for total in (1, 3, 6, 7, 8, 12, 25, 100):
            candidates = {1, 2, total // 2 or 1, total - 1 or 1, total}
            for page in sorted(p for p in candidates if 1 <= p <= total):
                window = _paginator_window(page=page, total=total)
                assert page in window, (
                    f"page={page} total={total} missing from window {window}"
                )
