"""Tests for board-link rewriting on completed SVG artifacts."""

from __future__ import annotations

import pytest

from dbt_charts.core.render.board_links import (
    absolutize_svg_links,
    board_link_slug,
    is_board_link,
    markdown_link_slugs,
)
from dbt_charts.core.render.errors import RenderError


def test_absolutize_svg_links_rewrites_root_relative_href_attributes() -> None:
    svg = (
        '<svg><a href="/acme/demo/d/revenue">Revenue</a>'
        "<image xlink:href='/acme/demo/static/logo.svg'/></svg>"
    )

    assert absolutize_svg_links(svg, "https://dashboards.example.com") == (
        '<svg><a href="https://dashboards.example.com/acme/demo/d/revenue">Revenue</a>'
        "<image xlink:href='https://dashboards.example.com/acme/demo/static/logo.svg'/></svg>"
    )


@pytest.mark.parametrize(
    "href",
    [
        "https://example.com/report",
        "http://example.com/report",
        "//cdn.example.com/chart.svg",
        "#details",
        "?region=north",
    ],
)
def test_absolutize_svg_links_preserves_non_root_relative_href(href: str) -> None:
    svg = f'<svg><a href="{href}">Open</a></svg>'

    assert absolutize_svg_links(svg, "https://dashboards.example.com") == svg


def test_absolutize_svg_links_rejects_empty_or_trailing_slash_origin() -> None:
    with pytest.raises(RenderError, match="origin must be non-empty") as empty:
        absolutize_svg_links("<svg/>", "")
    assert empty.value.code.code == "ERR-INPUT-INVALID"

    with pytest.raises(RenderError, match="must not end with") as trailing:
        absolutize_svg_links("<svg/>", "https://dashboards.example.com/")
    assert trailing.value.code.code == "ERR-INPUT-INVALID"


class TestLinkTargetSlug:
    """`link_target_slug` / `markdown_link_slugs` are engine API, so they are
    tested here rather than only through the Cloud consumer that motivated
    them — `test-dbt_charts.yml` owns this file and must be able to catch a break.
    """

    def test_rooted_and_relative_forms_resolve(self) -> None:
        assert board_link_slug("/revenue/detail", "revenue/list") == "revenue/detail"
        assert board_link_slug("detail", "revenue/list") == "revenue/detail"
        assert board_link_slug("../support/tickets", "revenue/list") == (
            "support/tickets"
        )

    def test_author_sugar_and_trailing_slash_come_off(self) -> None:
        assert board_link_slug("/revenue/detail.md", "revenue/list") == (
            "revenue/detail"
        )
        assert board_link_slug("/spend/", "overview") == "spend"

    def test_query_and_fragment_are_not_part_of_the_slug(self) -> None:
        assert board_link_slug("/revenue/detail?id={{ x }}", "revenue/list") == (
            "revenue/detail"
        )
        assert board_link_slug("/revenue/detail#top", "revenue/list") == (
            "revenue/detail"
        )

    def test_passthrough_schemes_are_not_board_navigation(self) -> None:
        for href in (
            "https://example.com/x",
            "mailto:ops@example.com",
            "#section",
            "?var=1",
            "cursor://file/x/board.yaml",
        ):
            assert not is_board_link(href)
            # Resolving one is a caller bug, not a None to thread through.
            with pytest.raises(RenderError, match="not board navigation"):
                board_link_slug(href, "revenue/list")

    def test_in_app_paths_are_board_navigation(self) -> None:
        assert is_board_link("/revenue/detail")
        assert is_board_link("detail")

    def test_markdown_and_raw_anchors_both_yield_slugs(self) -> None:
        markdown = (
            "[Spend](/spend/) · [Detail](detail) · [Site](https://example.com)\n"
            '<a href="/executive/overview">Overview</a>\n'
        )
        assert markdown_link_slugs(markdown, "revenue/list") == [
            "spend",
            "revenue/detail",
            "executive/overview",
        ]

    def test_image_syntax_is_not_a_board_link(self) -> None:
        assert markdown_link_slugs("![alt](/logo.png)", "overview") == []
