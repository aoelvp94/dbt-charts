"""
markdown-svg: Convert Markdown to SVG with automatic text wrapping.

This library provides a simple way to render Markdown text as SVG,
with support for common Markdown elements and automatic text wrapping.

Basic usage:
    >>> from mdsvg import render
    >>> svg = render("# Hello World\n\nThis is **bold** text.")

With custom styling:
    >>> from mdsvg import render, Style
    >>> svg = render("# Hello", width=400, style=Style(text_color="#333"))

Measure dimensions without rendering:
    >>> from mdsvg import measure
    >>> size = measure("# Hello\n\nLong paragraph...")
    >>> print(f"Height: {size.height}px")

Get structured result for composing into larger SVGs:
    >>> from mdsvg import render_content, RenderResult
    >>> result = render_content("# Hello", width=400)
    >>> result.content  # SVG elements without <svg> wrapper
    >>> result.width    # 400.0
    >>> result.height   # Actual rendered height
    >>> result.to_svg() # Full SVG with wrapper
"""

# Precise text measurement
from .fonts import (
    FontFace,
    FontFaces,
    FontMeasurer,
    create_precise_wrapper,
    download_google_font,
    get_font_cache_dir,
    get_system_font,
    get_system_mono_font,
    list_cached_fonts,
    measure_text_precise,
    pieces_to_text,
    split_token_precise,
    truncate_text_precise,
    wrap_measured_pieces,
    wrap_text_precise,
)
from .images import (
    ImageSize,
    ImageUrlMapper,
    create_base_url_mapper,
    create_prefix_mapper,
    get_image_size,
)
from .parser import MarkdownParser, parse
from .renderer import (
    RenderResult,
    Size,
    SVGRenderer,
    measure,
    render,
    render_blocks,
    render_content,
)
from .style import (
    COMPACT_PRESET,
    DARK_THEME,
    DOCUMENT_PRESET,
    GITHUB_THEME,
    LIGHT_THEME,
    MINIMAL_PRESET,
    CodeBlockOverflow,
    Style,
    StylePresets,
    TextAlign,
    merge_styles,
)
from .types import (
    AnyBlock,
    Block,
    Blockquote,
    BlockType,
    CodeBlock,
    Document,
    Heading,
    HorizontalRule,
    ImageBlock,
    ListItem,
    OrderedList,
    Paragraph,
    RawHtmlBlock,
    Span,
    SpanType,
    Table,
    TableCell,
    TableRow,
    UnorderedList,
)

__all__ = [
    # Main API
    "render",
    "render_content",
    "render_blocks",
    "measure",
    "parse",
    # Classes
    "Style",
    "RenderResult",
    "MarkdownParser",
    "SVGRenderer",
    # Themes
    "LIGHT_THEME",
    "DARK_THEME",
    "GITHUB_THEME",
    # Style Presets
    "StylePresets",
    "DOCUMENT_PRESET",
    "COMPACT_PRESET",
    "MINIMAL_PRESET",
    "merge_styles",
    # Style option types
    "TextAlign",
    "CodeBlockOverflow",
    # Types
    "Size",
    "Document",
    "AnyBlock",
    "Block",
    "BlockType",
    "Span",
    "SpanType",
    "Paragraph",
    "Heading",
    "CodeBlock",
    "Blockquote",
    "UnorderedList",
    "OrderedList",
    "ListItem",
    "HorizontalRule",
    "Table",
    "TableRow",
    "TableCell",
    "ImageBlock",
    "RawHtmlBlock",
    # Utilities
    # Precise text measurement
    "FontFace",
    "FontFaces",
    "FontMeasurer",
    "get_system_font",
    "get_system_mono_font",
    "create_precise_wrapper",
    "measure_text_precise",
    "pieces_to_text",
    "split_token_precise",
    "truncate_text_precise",
    "wrap_measured_pieces",
    "wrap_text_precise",
    "download_google_font",
    "get_font_cache_dir",
    "list_cached_fonts",
    # Image utilities
    "ImageSize",
    "ImageUrlMapper",
    "get_image_size",
    "create_prefix_mapper",
    "create_base_url_mapper",
]
