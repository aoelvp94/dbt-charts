"""Tests for image dimension probing."""

import base64
from urllib.parse import quote

import pytest

from mdsvg import get_image_size, render
from mdsvg.images import ImageSize

SVG_WITH_DIMENSIONS = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 412 128" '
    'width="412" height="128"><rect width="412" height="128"/></svg>'
)
SVG_VIEWBOX_ONLY = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 50">'
    '<rect width="200" height="50"/></svg>'
)


def data_uri(payload: str, media_type: str = "image/svg+xml") -> str:
    """Build a base64 data URI for the given payload."""
    encoded = base64.b64encode(payload.encode()).decode()
    return f"data:{media_type};base64,{encoded}"


class TestDataUriImageSize:
    """Data URIs are sized from their own payload, never stat()ed as paths."""

    def test_svg_with_explicit_width_and_height(self) -> None:
        assert get_image_size(data_uri(SVG_WITH_DIMENSIONS)) == ImageSize(
            width=412, height=128
        )

    def test_svg_with_only_a_viewbox(self) -> None:
        assert get_image_size(data_uri(SVG_VIEWBOX_ONLY)) == ImageSize(
            width=200, height=50
        )

    def test_svg_dimensions_with_px_units(self) -> None:
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="80px" height="40px"/>'
        assert get_image_size(data_uri(svg)) == ImageSize(width=80, height=40)

    def test_svg_percentage_dimensions_fall_back_to_viewbox(self) -> None:
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" '
            'viewBox="0 0 300 100"/>'
        )
        assert get_image_size(data_uri(svg)) == ImageSize(width=300, height=100)

    def test_unpadded_base64_payload(self) -> None:
        """Browsers decode data: URIs with forgiving-base64, so padding is optional."""
        encoded = base64.b64encode(SVG_WITH_DIMENSIONS.encode()).decode().rstrip("=")
        url = f"data:image/svg+xml;base64,{encoded}"
        assert get_image_size(url) == ImageSize(width=412, height=128)

    def test_percent_encoded_svg_payload(self) -> None:
        url = f"data:image/svg+xml,{quote(SVG_WITH_DIMENSIONS)}"
        assert get_image_size(url) == ImageSize(width=412, height=128)

    def test_binary_payload_uses_the_normal_header_parser(self) -> None:
        png = (
            bytes.fromhex(
                "89504e470d0a1a0a0000000d49484452000000200000001008060000001ff3ff61"
            )
            + b"\x00" * 16
        )
        url = f"data:image/png;base64,{base64.b64encode(png).decode()}"
        assert get_image_size(url) == ImageSize(width=32, height=16)

    def test_header_is_case_and_whitespace_insensitive(self) -> None:
        """RFC 2045 media types and the base64 token are case-insensitive."""
        encoded = base64.b64encode(SVG_WITH_DIMENSIONS.encode()).decode()
        for header in (
            "IMAGE/SVG+XML;BASE64",
            "image/SVG+xml;base64",
            "image/svg+xml; base64",
        ):
            assert get_image_size(f"data:{header},{encoded}") == ImageSize(
                width=412, height=128
            )

    def test_zero_dimensions_fall_back_to_viewbox(self) -> None:
        """Zero is 'no intrinsic size' — it must not suppress the viewBox."""
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0" '
            'viewBox="0 0 300 100"/>'
        )
        assert get_image_size(data_uri(svg)) == ImageSize(width=300, height=100)

    def test_sub_pixel_dimensions_fall_back_to_viewbox(self) -> None:
        """A positive width that rounds to 0 is still no size (ZeroDivisionError)."""
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="0.4" height="128" '
            'viewBox="0 0 300 100"/>'
        )
        assert get_image_size(data_uri(svg)) == ImageSize(width=300, height=100)

    def test_sub_pixel_viewbox_is_not_a_size(self) -> None:
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 0.4 128"/>'
        assert get_image_size(data_uri(svg)) is None

    def test_sub_pixel_svg_still_renders_the_document(self) -> None:
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="0.4" height="128"/>'
        rendered = render(f"![x]({data_uri(svg)})", width=400)
        assert "<image" in rendered


class TestUnmeasurableDataUris:
    """Intact but unmeasurable payloads return None, like any other source.

    Returning None routes them to the renderer's `image_fallback_aspect_ratio`.
    Raising here would abort the whole document for one decorative image — and
    the identical bytes behind an https:// URL already return None.
    """

    def test_media_type_the_header_parser_does_not_know(self) -> None:
        assert get_image_size(data_uri("\x00" * 64, media_type="image/avif")) is None

    def test_svg_with_no_intrinsic_size(self) -> None:
        """`width="100%"` with no viewBox genuinely has no intrinsic size."""
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%"/>'
        assert get_image_size(data_uri(svg)) is None

    def test_svg_declaring_xml_entities_is_not_parsed(self) -> None:
        """Never handed to expat, which caps entity amplification only from 2.6."""
        svg = (
            '<!DOCTYPE svg [<!ENTITY a "aaaaaaaa">]>'
            '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">&a;</svg>'
        )
        assert get_image_size(data_uri(svg)) is None

    def test_svg_with_no_size_attributes_at_all(self) -> None:
        assert (
            get_image_size(data_uri('<svg xmlns="http://www.w3.org/2000/svg"/>'))
            is None
        )

    def test_unmeasurable_data_uri_still_renders_the_document(self) -> None:
        """One unmeasurable image must not take the whole board down."""
        url = data_uri("\x00" * 64, media_type="image/avif")
        svg = render(f"# Title\n\n![Logo]({url})\n\nBody text.", width=400)
        assert "<image" in svg
        assert "Body text." in svg


class TestCorruptDataUris:
    """Bytes that cannot be an image raise — guessing would hide the mistake."""

    def test_malformed_base64_payload(self) -> None:
        with pytest.raises(ValueError, match="base64"):
            get_image_size("data:image/svg+xml;base64,!!!not-base64!!!")

    def test_svg_payload_that_is_not_xml(self) -> None:
        with pytest.raises(ValueError, match="Malformed XML"):
            get_image_size(data_uri("<svg not really xml"))

    def test_uri_without_a_payload_separator(self) -> None:
        with pytest.raises(ValueError, match="separating header from payload"):
            get_image_size("data:image/svg+xml;base64")


class TestInlineImageRendering:
    def test_renders_an_inline_data_uri_image(self) -> None:
        """Regression: a data URI used to be stat()ed as a path (ENAMETOOLONG).

        The payload is padded past PATH_MAX (1024) so os.stat rejects the URI
        outright instead of reporting a merely non-existent file.

        Asserts the laid-out height, not just that an <image> exists: at 412x128
        a 360px-wide box is 111.8 tall, where the 16:9 fallback ratio would give
        202.5. That difference is what distinguishes sizing the payload from
        merely not crashing.
        """
        padded = SVG_WITH_DIMENSIONS.replace("<rect", f"<!--{'x' * 1000}--><rect")
        url = data_uri(padded)
        assert len(url) > 1024
        svg = render(f"![Logo]({url})", width=400)
        assert '<image x="20" y="20" width="360" height="111.84"' in svg
