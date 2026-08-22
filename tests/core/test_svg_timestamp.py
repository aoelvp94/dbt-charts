"""Tests for SVG render timestamp functionality.

Tests the data-rendered-at attribute and visible timestamp display.
"""

import re
from collections.abc import Callable
from datetime import datetime
from xml.etree import ElementTree

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile.config import get_theme_style

from ._svg_render import render_board_to_svg as _render_svg


def _render_timestamp_element(svg: str) -> ElementTree.Element:
    root = ElementTree.fromstring(svg)
    matches = [
        element
        for element in root.iter("{http://www.w3.org/2000/svg}text")
        if element.attrib.get("data-role") == "render-timestamp"
    ]
    assert len(matches) == 1
    return matches[0]


def _footer_text_element(svg: str) -> ElementTree.Element:
    root = ElementTree.fromstring(svg)
    matches = [
        element
        for element in root.iter("{http://www.w3.org/2000/svg}text")
        if element.attrib.get("data-role") != "render-timestamp"
    ]
    assert matches
    return matches[-1]


class TestSVGRenderTimestamp:
    """Tests for SVG render timestamp functionality."""

    def test_svg_includes_data_rendered_at_attribute(self):
        """Test that SVG output includes data-rendered-at attribute with ISO timestamp."""
        svg_output = _render_svg()

        # Check that data-rendered-at attribute exists with ISO 8601 format
        assert 'data-rendered-at="' in svg_output

        # Extract and validate the timestamp format
        match = re.search(
            r'data-rendered-at="(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)"', svg_output
        )
        assert match is not None, "data-rendered-at should contain ISO 8601 timestamp"

        # Verify it's a valid timestamp
        timestamp_str = match.group(1)
        parsed = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%SZ")
        assert parsed is not None

    def test_svg_includes_visible_timestamp_by_default(self):
        """A visible freshness stamp renders footer-left by default.

        Asserts the semantic contract (present, left-anchored, non-empty), not
        the theme default's exact caption wording — that is tunable, and pinning
        it here would break on a copy tweak with no defect. Zone disclosure has
        its own test; caption shape is pinned under an explicit format override
        in test_timestamp_footer_style.py.
        """
        svg_output = _render_svg()

        timestamp = _render_timestamp_element(svg_output)
        # Footer-left default → the timestamp text itself is left-anchored
        # (the right-anchored element in the SVG is the footer attribution).
        assert timestamp.attrib["text-anchor"] == "start"
        assert timestamp.text is not None and timestamp.text.strip()

    def test_svg_timestamp_can_be_disabled(
        self, local_project: Callable[..., FilesystemProject]
    ):
        """Test that visible timestamp can be disabled via board style."""
        # Hiding the timestamp is now a per-board style authoring decision.
        # Use the test helper from test_timestamp_footer_style which exercises
        # the full authored style path.
        yaml = """\
title: Test
queries:
  q: {type: values, rows: [{n: 1}]}
charts:
  t: {query: q, type: table}
rows: [t]
style:
  timestamp:
    visible: false
"""
        from pathlib import Path

        from dbt_charts.core.compile import compile
        from dbt_charts.core.execute import Executor
        from dbt_charts.core.execute.adapters import build_adapter_registry
        from dbt_charts.core.render import render

        result = compile(yaml)
        assert result.board is not None
        rendered = render(
            result.board,
            Executor(
                result.board,
                adapter_registry=build_adapter_registry(local_project(Path.cwd())),
            ),
            format="svg",
        )
        svg_output = rendered.output
        assert isinstance(svg_output, str)

        # data-rendered-at should still be present (always included in the SVG root element)
        assert 'data-rendered-at="' in svg_output

        # But the visible timestamp text element should not be present
        assert 'data-role="render-timestamp"' not in svg_output

    def test_svg_timestamp_format_is_configurable(
        self, local_project: Callable[..., FilesystemProject]
    ):
        """Test that timestamp format can be configured via board style."""
        yaml = """\
title: Test
queries:
  q: {type: values, rows: [{n: 1}]}
charts:
  t: {query: q, type: table}
rows: [t]
style:
  timestamp:
    format: "%Y/%m/%d"
    font:
      size: 11
      color: "#999999"
"""
        from pathlib import Path

        from dbt_charts.core.compile import compile
        from dbt_charts.core.execute import Executor
        from dbt_charts.core.execute.adapters import build_adapter_registry
        from dbt_charts.core.render import render

        result = compile(yaml)
        assert result.board is not None
        rendered = render(
            result.board,
            Executor(
                result.board,
                adapter_registry=build_adapter_registry(local_project(Path.cwd())),
            ),
            format="svg",
        )
        svg_output = rendered.output
        assert isinstance(svg_output, str)

        # Should see the custom format in the visible timestamp
        date_pattern = r"\d{4}/\d{2}/\d{2}"
        assert re.search(date_pattern, svg_output) is not None

    def test_data_rendered_at_is_always_iso8601_utc(
        self, local_project: Callable[..., FilesystemProject]
    ):
        """Test that data-rendered-at attribute is always ISO 8601 UTC regardless of display format."""
        # The data-rendered-at attr is always UTC ISO 8601; the display timestamp
        # uses the authored format. Use a non-ISO display format to verify the
        # root attribute is independent.
        yaml = """\
title: Test
queries:
  q: {type: values, rows: [{n: 1}]}
charts:
  t: {query: q, type: table}
rows: [t]
style:
  timestamp:
    format: "%b %d, %Y"
    font:
      size: 11
      color: "#999999"
"""
        from pathlib import Path

        from dbt_charts.core.compile import compile
        from dbt_charts.core.execute import Executor
        from dbt_charts.core.execute.adapters import build_adapter_registry
        from dbt_charts.core.render import render

        result = compile(yaml)
        assert result.board is not None
        rendered = render(
            result.board,
            Executor(
                result.board,
                adapter_registry=build_adapter_registry(local_project(Path.cwd())),
            ),
            format="svg",
        )
        svg_output = rendered.output
        assert isinstance(svg_output, str)

        # data-rendered-at should always be ISO 8601
        match = re.search(
            r'data-rendered-at="(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)"', svg_output
        )
        assert match is not None

    def test_svg_visible_timestamp_discloses_utc_zone(self):
        """The visible freshness stamp discloses its zone; the value is always UTC."""
        svg_output = _render_svg()
        timestamp = _render_timestamp_element(svg_output)
        assert timestamp.text is not None
        assert "UTC" in timestamp.text, (
            "Visible timestamp should disclose its timezone (the value is UTC)"
        )

    def test_svg_timestamp_top_uses_configured_y_and_align(
        self, local_project: Callable[..., FilesystemProject]
    ):
        """Top-positioned timestamp sits at style.timestamp.y and honors align.

        The default is footer-left, so the `position: top` branch (which places
        the element at `style.timestamp.y`) is only reachable via an override —
        this pins that branch and the `y` field it reads.
        """
        yaml = """\
title: Test
queries:
  q: {type: values, rows: [{n: 1}]}
charts:
  t: {query: q, type: table}
rows: [t]
style:
  timestamp:
    position: top
    align: right
"""
        from pathlib import Path

        from dbt_charts.core.compile import compile
        from dbt_charts.core.execute import Executor
        from dbt_charts.core.execute.adapters import build_adapter_registry
        from dbt_charts.core.render import render

        result = compile(yaml)
        assert result.board is not None
        rendered = render(
            result.board,
            Executor(
                result.board,
                adapter_registry=build_adapter_registry(local_project(Path.cwd())),
            ),
            format="svg",
        )
        assert isinstance(rendered.output, str)
        timestamp = _render_timestamp_element(rendered.output)
        # Compare against the resolved y rather than pinning the theme literal.
        assert float(timestamp.attrib["y"]) == result.board.resolved_style.timestamp.y
        assert timestamp.attrib["text-anchor"] == "end"

    def test_svg_timestamp_footer_left_uses_footer_baseline(
        self, local_project: Callable[..., FilesystemProject]
    ):
        """Footer-left timestamp shares the footer baseline and starts at page padding."""
        yaml = """\
title: Test
queries:
  q: {type: values, rows: [{n: 1}]}
charts:
  t: {query: q, type: table}
rows: [t]
style:
  timestamp:
    position: footer
    align: left
"""
        from pathlib import Path

        from dbt_charts.core.compile import compile
        from dbt_charts.core.execute import Executor
        from dbt_charts.core.execute.adapters import build_adapter_registry
        from dbt_charts.core.render import render

        result = compile(yaml)
        assert result.board is not None
        rendered = render(
            result.board,
            Executor(
                result.board,
                adapter_registry=build_adapter_registry(local_project(Path.cwd())),
            ),
            format="svg",
        )
        assert isinstance(rendered.output, str)
        timestamp = _render_timestamp_element(rendered.output)
        footer = _footer_text_element(rendered.output)

        assert timestamp.attrib["y"] == footer.attrib["y"]
        assert timestamp.attrib["x"] == str(int(get_theme_style().frame.margin))
        assert timestamp.attrib["text-anchor"] == "start"

    def test_svg_timestamp_footer_right_avoids_visible_footer(
        self, local_project: Callable[..., FilesystemProject]
    ):
        """Footer-right timestamp shifts left of the visible attribution text."""
        yaml = """\
title: Test
queries:
  q: {type: values, rows: [{n: 1}]}
charts:
  t: {query: q, type: table}
rows: [t]
style:
  timestamp:
    position: footer
    align: right
"""
        from pathlib import Path

        from dbt_charts.core.compile import compile
        from dbt_charts.core.compile.config import (
            get_chart_rendering,
            get_default_theme_name,
        )
        from dbt_charts.core.execute import Executor
        from dbt_charts.core.execute.adapters import build_adapter_registry
        from dbt_charts.core.font_measure import get_font_measurer
        from dbt_charts.core.render import render

        result = compile(yaml)
        assert result.board is not None
        rendered = render(
            result.board,
            Executor(
                result.board,
                adapter_registry=build_adapter_registry(local_project(Path.cwd())),
            ),
            format="svg",
        )
        assert isinstance(rendered.output, str)
        timestamp = _render_timestamp_element(rendered.output)
        footer = _footer_text_element(rendered.output)
        footer_style = get_theme_style(get_default_theme_name()).footer
        assert footer_style.font.size is not None
        attribution_width = get_font_measurer().measure(
            footer_style.text,
            float(footer_style.font.size),
        )

        assert timestamp.attrib["y"] == footer.attrib["y"]
        assert timestamp.attrib["text-anchor"] == "end"
        assert float(timestamp.attrib["x"]) <= (
            float(footer.attrib["x"])
            - attribution_width
            - get_chart_rendering().frame.footer_timestamp_gap_px
        )

    def test_svg_timestamp_footer_right_flushes_when_footer_hidden(
        self, local_project: Callable[..., FilesystemProject]
    ):
        """Footer-right timestamp uses the right page edge when attribution is hidden."""
        yaml = """\
title: Test
queries:
  q: {type: values, rows: [{n: 1}]}
charts:
  t: {query: q, type: table}
rows: [t]
style:
  footer:
    visible: false
  timestamp:
    position: footer
    align: right
"""
        from pathlib import Path

        from dbt_charts.core.compile import compile
        from dbt_charts.core.execute import Executor
        from dbt_charts.core.execute.adapters import build_adapter_registry
        from dbt_charts.core.render import render

        result = compile(yaml)
        assert result.board is not None
        rendered = render(
            result.board,
            Executor(
                result.board,
                adapter_registry=build_adapter_registry(local_project(Path.cwd())),
            ),
            format="svg",
        )
        assert isinstance(rendered.output, str)
        timestamp = _render_timestamp_element(rendered.output)
        root = ElementTree.fromstring(rendered.output)
        view_box = root.attrib["viewBox"].split()
        right_edge = float(view_box[2]) - get_theme_style().frame.margin

        assert timestamp.attrib["text-anchor"] == "end"
        assert float(timestamp.attrib["x"]) == right_edge
