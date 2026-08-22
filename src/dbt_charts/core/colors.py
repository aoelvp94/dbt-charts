"""CSS/SVG color-string validation.

Lives in core (below compile/execute/render) so both compile (pie-attachment
table style resolution) and render (KPI/table SVG emission) can validate a
foreign color string without either reaching into the other's layer.
"""

from __future__ import annotations

import re
from typing import overload

from dbt_charts.core.diagnostics.base import DbtChartsError

_CSS_HEX_COLOR_PATTERN = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class InvalidColorError(DbtChartsError):
    """A color string is neither a valid hex color nor a recognized CSS keyword."""

    def __init__(self, message: str):
        self.message = message
        self.fields = {}
        super().__init__(message)
        if self.code is None:
            from dbt_charts.core.diagnostics.codes_unknown import ERR_INTERNAL

            self.code = ERR_INTERNAL


def is_sanitizable_color(color: str) -> bool:
    """Return True if ``color`` is accepted by sanitize_color (hex or transparent/none)."""
    return bool(_CSS_HEX_COLOR_PATTERN.match(color)) or color.lower() in {
        "transparent",
        "none",
    }


@overload
def sanitize_color(color: str | None, fallback: str) -> str: ...


@overload
def sanitize_color(color: str | None, fallback: None = ...) -> str | None: ...


def sanitize_color(color: str | None, fallback: str | None = None) -> str | None:
    """Validate and sanitize a color value for safe use in SVG/HTML.

    Accepts hex colors (``#fff``, ``#FFFFFF``) and the CSS keywords
    ``transparent`` and ``none``.  Presets use ``transparent`` to
    explicitly clear an inherited theme color (YAML ``null`` means
    "no override" in the merge system, so it doesn't disable an
    inherited fill).

    ``fallback`` is returned when ``color`` is None or empty.  A non-None
    ``color`` that is not a valid hex or keyword raises ``InvalidColorError``
    immediately — authored colors that are not valid are a configuration error,
    not a case for silent defaulting.
    """
    if not color:
        return fallback
    if _CSS_HEX_COLOR_PATTERN.match(color):
        return color
    if color.lower() in {"transparent", "none"}:
        return "transparent"
    raise InvalidColorError(f"Invalid color value: {color!r}")
