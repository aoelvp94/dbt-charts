"""d3-format — Python implementation of d3-format spec parsing and formatting.

Public API:
    format(spec_str)(value) -> str
    format(spec_str, value) -> str
    parse(spec_str) -> FormatSpec
    D3FormatError
"""

from d3_format.errors import D3FormatError
from d3_format.format import format
from d3_format.spec import FormatSpec, parse

__all__ = ["D3FormatError", "FormatSpec", "format", "parse"]
