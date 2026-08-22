"""Integration tests for mdsvg."""

from __future__ import annotations

from pathlib import Path

import pytest

from mdsvg import (
    DARK_THEME,
    GITHUB_THEME,
    Style,
    measure,
    parse,
    render,
    render_blocks,
)


class TestPublicAPI:
    """Test the public API."""

    def test_render_function(self) -> None:
        """Test render() function."""
        svg = render("# Hello World")
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")

    def test_measure_function(self) -> None:
        """Test measure() function."""
        size = measure("# Hello World")
        assert size.width > 0
        assert size.height > 0

    def test_parse_function(self) -> None:
        """Test parse() function."""
        doc = parse("# Hello World")
        assert len(doc) == 1

    def test_render_blocks_function(self) -> None:
        """Test render_blocks() function."""
        blocks = parse("# Hello")
        svg = render_blocks(blocks)
        assert "<svg" in svg


class TestStyleAPI:
    """Test Style API."""

    def test_default_style(self) -> None:
        """Test default style."""
        style = Style()
        assert style.base_font_size == 14.0
        assert style.text_color == "#1a1a1a"

    def test_style_with_updates(self) -> None:
        """Test Style.with_updates()."""
        style = Style()
        new_style = style.with_updates(text_color="#ff0000")
        assert new_style.text_color == "#ff0000"
        assert style.text_color == "#1a1a1a"  # Original unchanged

    def test_style_get_heading_scale(self) -> None:
        """Test Style.get_heading_scale()."""
        style = Style()
        assert style.get_heading_scale(1) == 2.0
        assert style.get_heading_scale(6) == 0.9

    def test_style_get_heading_color(self) -> None:
        """Test Style.get_heading_color()."""
        style = Style()
        assert style.get_heading_color() == style.text_color

        style2 = Style(heading_color="#123456")
        assert style2.get_heading_color() == "#123456"

    def test_style_get_heading_size_falls_back_to_scale(self) -> None:
        """Without h*_size set, get_heading_size = base × scale."""
        style = Style(base_font_size=14.0)
        assert style.get_heading_size(1) == 14.0 * 2.0  # h1_scale
        assert style.get_heading_size(2) == 14.0 * 1.6  # h2_scale
        assert style.get_heading_size(6) == 14.0 * 0.9  # h6_scale

    def test_style_get_heading_size_absolute_override(self) -> None:
        """h*_size overrides the scale × base_font_size calculation."""
        style = Style(base_font_size=14.0, h2_size=18.0)
        assert style.get_heading_size(2) == 18.0
        # Other levels still use the scale path.
        assert style.get_heading_size(1) == 14.0 * 2.0

    def test_render_h2_honors_h2_size(self) -> None:
        """Renderer must emit h2 at h2_size, not base_font_size × h2_scale."""
        style = Style(base_font_size=14.0, h2_size=18.0)
        svg = render("## Heading", width=400, style=style)
        # Renderer emits font-size as a string attribute.
        assert 'font-size="18' in svg or "font-size: 18" in svg
        assert "22.4" not in svg  # 14 × 1.6 must not appear

    def test_heading_line_height_overrides_body_line_height(self) -> None:
        """When heading_line_height is set, wrapped heading lines use the
        heading multiplier instead of the body line_height."""
        # Two-line heading: forces the renderer to use line_height between lines.
        long_h1 = "# This is a long enough heading to wrap onto two lines"
        body_style = Style(base_font_size=12.0, line_height=1.6, h1_size=24.0)
        tight_style = Style(
            base_font_size=12.0, line_height=1.6, h1_size=24.0, heading_line_height=1.2
        )

        body_svg = render(long_h1, width=200, style=body_style)
        tight_svg = render(long_h1, width=200, style=tight_style)

        import re

        body_ys = [float(m) for m in re.findall(r'<text [^>]*y="([\d.]+)"', body_svg)]
        tight_ys = [float(m) for m in re.findall(r'<text [^>]*y="([\d.]+)"', tight_svg)]
        # First two heading lines exist in both renders.
        assert len(body_ys) >= 2 and len(tight_ys) >= 2
        body_gap = body_ys[1] - body_ys[0]
        tight_gap = tight_ys[1] - tight_ys[0]
        # Body multiplier 1.6 × 24 = 38.4; heading multiplier 1.2 × 24 = 28.8.
        assert body_gap == 24.0 * 1.6
        assert tight_gap == 24.0 * 1.2
        assert tight_gap < body_gap

    def test_heading_line_height_none_falls_back_to_body(self) -> None:
        """When heading_line_height is None (default), heading inherits body."""
        long_h1 = "# This is a long enough heading to wrap onto two lines"
        style = Style(base_font_size=12.0, line_height=1.6, h1_size=24.0)
        svg = render(long_h1, width=200, style=style)
        import re

        ys = [float(m) for m in re.findall(r'<text [^>]*y="([\d.]+)"', svg)]
        assert len(ys) >= 2
        assert ys[1] - ys[0] == 24.0 * 1.6


class TestThemes:
    """Test built-in themes."""

    def test_light_theme(self) -> None:
        """Test light theme."""
        from mdsvg import LIGHT_THEME

        svg = render("Hello", style=LIGHT_THEME)
        assert "<svg" in svg

    def test_dark_theme(self) -> None:
        """Test dark theme has different colors."""
        assert DARK_THEME.text_color != Style().text_color

    def test_github_theme(self) -> None:
        """Test GitHub theme."""
        assert GITHUB_THEME.base_font_size == 16.0


class TestFullWorkflow:
    """Test complete workflows."""

    def test_parse_measure_render(self) -> None:
        """Test parse -> measure -> render workflow."""
        md = "# Title\n\nParagraph"

        # Parse
        blocks = parse(md)
        assert len(blocks) == 2

        # Measure
        size = measure(md, width=400)
        assert size.width == 400

        # Render
        svg = render(md, width=400)
        assert "<svg" in svg

    def test_render_to_file(self, tmp_path: Path) -> None:
        """Test rendering to file."""
        svg = render("# Hello World")

        output_file = tmp_path / "test.svg"
        output_file.write_text(svg)

        assert output_file.exists()
        content = output_file.read_text()
        assert content.startswith("<svg")


class TestImports:
    """Test that all expected exports are available."""

    def test_main_functions(self) -> None:
        """Test main functions are importable."""
        from mdsvg import measure, parse, render, render_blocks

        assert callable(render)
        assert callable(measure)
        assert callable(parse)
        assert callable(render_blocks)

    def test_classes(self) -> None:
        """Test classes are importable."""
        from mdsvg import MarkdownParser, Style, SVGRenderer

        assert Style is not None
        assert MarkdownParser is not None
        assert SVGRenderer is not None

    def test_types(self) -> None:
        """Test types are importable."""
        from mdsvg import (
            Heading,
            Paragraph,
        )

        assert Heading is not None
        assert Paragraph is not None


class TestRealWorldExamples:
    """Test with real-world markdown examples."""

    def test_readme_style_document(self) -> None:
        """Test rendering a README-style document."""
        md = """# Project Name

A brief description of the project.

## Installation

```bash
pip install project-name
```

## Usage

```python
from project import main
main()
```

## Features

- Feature 1
- Feature 2
- Feature 3

## License

MIT
"""
        svg = render(md, width=600, padding=20)
        assert "<svg" in svg
        assert "Project Name" in svg
        assert "pip install" in svg

    def test_documentation_with_tables(self) -> None:
        """Test rendering documentation with tables."""
        md = """# API Reference

| Method | Description | Returns |
| ------ | ----------- | ------- |
| `get()` | Get item | `Item` |
| `set()` | Set item | `None` |
| `delete()` | Delete item | `bool` |

## Parameters

All methods accept the following parameters:

1. `id` - The item ID
2. `options` - Optional configuration
"""
        svg = render(md, width=500)
        assert "<svg" in svg
        assert "API Reference" in svg


class TestErrorHandling:
    """Test error handling."""

    def test_invalid_heading_level_in_type(self) -> None:
        """Test invalid heading level raises error."""
        from mdsvg.types import Heading, Span

        with pytest.raises(ValueError, match="Heading level must be 1-6"):
            Heading(level=0, spans=(Span(text="test"),))

        with pytest.raises(ValueError, match="Heading level must be 1-6"):
            Heading(level=7, spans=(Span(text="test"),))

    def test_link_without_url(self) -> None:
        """Test link span without URL raises error."""
        from mdsvg.types import Span, SpanType

        with pytest.raises(ValueError, match="Link spans must have a URL"):
            Span(text="link", span_type=SpanType.LINK)
