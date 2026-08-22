"""PNG format conversion.

Stage: RENDER
Purpose: Convert SVG output to PNG using vl-convert.
"""

from dbt_charts.core.render.errors import FormatError
from dbt_charts.core.render.font_support import (
    normalize_svg_font_families_for_vl_convert,
    register_vl_convert_fonts,
)


def to_png(svg_content: str, scale: float = 1.0) -> bytes:
    """Convert SVG to PNG using vl-convert.

    Args:
        svg_content: SVG string to convert
        scale: Scale factor for the output image

    Returns:
        PNG image as bytes

    Raises:
        FormatError: If conversion fails or dependencies missing
    """
    try:
        import vl_convert as vlc

        register_vl_convert_fonts(vlc)
        normalized_svg = normalize_svg_font_families_for_vl_convert(svg_content)
        return vlc.svg_to_png(normalized_svg, scale=scale)
    except ImportError:
        raise FormatError(
            "PNG export requires vl-convert-python: pip install vl-convert-python",
            "png",
        ) from None
    except FormatError:
        raise
    except Exception as e:
        raise FormatError(f"PNG conversion failed: {e}", "png") from e
