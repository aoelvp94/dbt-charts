"""Regression test: the root <svg>'s inline style must not blank standalone exports.

The root element used to carry ``style="display: block; max-width: 100%; height:
auto;"``. Inline CSS outranks the element's own ``height`` presentation attribute, so
``height: auto`` won. Inside our HTML host that resolves against the viewBox aspect
ratio (the fit-to-width trick page.css documents), but a standalone export has no such
layout context: ``auto`` computes to nothing and the artifact renders blank — a
broken-image placeholder in Slack, GitHub, or any server-side thumbnailer. The fix
drops the inline style to ``display: block;`` only; every host that embeds the SVG
already sets its own fit rule (page.css, Cloud's main.css, playground's
preview-svg-wrapper.css).
"""

import re

import pytest

try:
    import cairosvg
except (ImportError, OSError):  # cairosvg raises OSError when libcairo is absent
    pytest.skip("cairo native library unavailable", allow_module_level=True)

from .._svg_render import render_board_to_svg  # noqa: E402


def _root_style(svg: str) -> str:
    match = re.search(r"<svg\b[^>]*\bstyle=\"([^\"]*)\"", svg)
    assert match is not None, "root <svg> has no style attribute"
    return match.group(1)


class TestSvgRootStandaloneExport:
    def test_root_style_carries_no_height_auto(self) -> None:
        svg = render_board_to_svg()
        style = _root_style(svg)
        assert style == "display: block;", (
            f"root <svg> style regressed to a host-responsive rule: {style!r} — "
            "max-width/height:auto blank standalone exports (see module docstring)"
        )

    def test_standalone_export_rasterizes_non_blank(self) -> None:
        """A cairosvg rasterization stands in for a thumbnailer: no browser, no JS,
        no HTML host to supply a fit rule — just the SVG document on its own."""
        svg = render_board_to_svg()
        png_bytes = cairosvg.svg2png(bytestring=svg.encode("utf-8"))
        assert png_bytes is not None

        # A fully transparent raster (every pixel alpha=0) is what "auto" height
        # collapsing to zero produces. Decode without extra deps: PNG raw scanlines
        # for an RGBA image are ``1 + 4*width`` bytes per row (leading filter byte);
        # any non-zero alpha byte proves something was actually painted.
        import zlib

        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        idat = b"".join(
            _png_chunk_data(png_bytes, offset)
            for offset in _png_chunk_offsets(png_bytes, b"IDAT")
        )
        raw = zlib.decompress(idat)
        assert any(byte != 0 for byte in raw), (
            "rasterized standalone SVG is fully blank — height:auto regression"
        )


def _png_chunk_offsets(data: bytes, chunk_type: bytes) -> list[int]:
    offsets = []
    pos = 8
    while pos < len(data):
        length = int.from_bytes(data[pos : pos + 4], "big")
        ctype = data[pos + 4 : pos + 8]
        if ctype == chunk_type:
            offsets.append(pos)
        pos += 12 + length
    return offsets


def _png_chunk_data(data: bytes, offset: int) -> bytes:
    length = int.from_bytes(data[offset : offset + 4], "big")
    return data[offset + 8 : offset + 8 + length]
