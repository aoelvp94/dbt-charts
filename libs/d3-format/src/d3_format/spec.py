"""FormatSpec dataclass and parse() function for d3-format grammar.

Grammar: [[fill]align][sign][symbol][0][width][,][.precision][~][type]
"""

from __future__ import annotations

import string
from dataclasses import dataclass

from d3_format.errors import D3FormatError

# Align characters that signal fill+align or just align.
_ALIGN_CHARS = frozenset("><^=")

# Sign characters.
_SIGN_CHARS = frozenset("-+( ")

# Symbol characters: "$" currency, "#" alternate form. d3's grammar admits one.
_SYMBOL_CHARS = frozenset("$#")

# d3's type group is `([a-z%])?` under the `i` flag: any ASCII letter, or "%".
# Only some of those letters select a formatter; the rest are valid syntax that
# d3 aliases to ".12~g" (applied by ``_resolve_type`` in format.py, not here --
# ``parse`` reports the spec as written).
_TYPE_CHARS = frozenset(string.ascii_letters + "%")

# d3's width and precision groups are `\d`, which is ASCII. str.isdigit() also
# accepts other Unicode digit forms, which would parse a spec d3 rejects.
_DIGITS = frozenset(string.digits)


@dataclass
class FormatSpec:
    """Parsed representation of a d3-format spec string.

    All fields map directly to d3-format grammar tokens.
    Defaults match d3.js defaults.
    """

    fill: str = " "
    align: str = ">"
    sign: str = "-"
    symbol: str = ""  # "", "$" (currency) or "#" (alternate form)
    zero: bool = False
    width: int | None = None
    comma: bool = False
    precision: int | None = None
    trim: bool = False  # ~ flag
    type: str = ""  # "" means default (g-ish) behavior

    def __str__(self) -> str:
        """Serialize back to a d3-format spec string, in grammar order.

        Omits every default-valued token, so a parsed spec serializes back to
        something an author would write rather than a fully-explicit
        expansion. ``zero`` implies ``fill == "0"`` and ``align == "="`` (the
        collapse in ``parse``), so the zero-pad flag is emitted alone rather
        than alongside a redundant ``0=`` fill and align.

        Raises:
            ValueError: If ``zero`` is set but ``fill``/``align`` have been
                mutated away from ``"0"``/``"="``. The d3 grammar cannot
                express that combination -- ``parse`` collapses ``zero`` back
                to ``fill="0"``, ``align="="`` unconditionally -- so silently
                keeping the flag and dropping the fill would misrepresent the
                spec. Clear ``zero`` first if an explicit fill/align is wanted.
        """
        if self.zero and (self.fill != "0" or self.align != "="):
            raise ValueError(
                "FormatSpec has zero=True with fill="
                f"{self.fill!r}, align={self.align!r}; the d3 grammar can "
                "only express zero-pad as fill='0', align='='. Clear zero "
                "if you want this fill/align combination."
            )
        tokens: list[str] = []
        if not self.zero and (self.fill != " " or self.align != ">"):
            tokens.append(self.fill)
            tokens.append(self.align)
        if self.sign != "-":
            tokens.append(self.sign)
        if self.symbol:
            tokens.append(self.symbol)
        if self.zero:
            tokens.append("0")
        if self.width is not None:
            tokens.append(str(self.width))
        if self.comma:
            tokens.append(",")
        if self.precision is not None:
            tokens.append(f".{self.precision}")
        if self.trim:
            tokens.append("~")
        tokens.append(self.type)
        return "".join(tokens)


def parse(spec: str) -> FormatSpec:
    """Parse a d3-format spec string into a FormatSpec.

    Args:
        spec: A d3-format spec string, e.g. ",.2f", "$,.0f", "0>10.2f".

    Returns:
        FormatSpec with parsed fields, exactly as written. Type aliasing
        (``n`` -> ``,g``, an unrecognized letter -> ``.12~g``) and precision
        clamping happen in ``format``, mirroring where d3 applies them.

    Raises:
        D3FormatError: If the spec does not match the d3-format grammar.
    """
    result = FormatSpec()
    i = 0
    n = len(spec)

    # --- Fill + align detection ---
    # If character at index 1 is an align char, index 0 is fill.
    # If character at index 0 is an align char (and index 1 is not), no fill.
    if n >= 2 and spec[1] in _ALIGN_CHARS:
        result.fill = spec[0]
        result.align = spec[1]
        i = 2
    elif n >= 1 and spec[0] in _ALIGN_CHARS:
        result.align = spec[0]
        i = 1

    # --- Sign ---
    if i < n and spec[i] in _SIGN_CHARS:
        result.sign = spec[i]
        i += 1

    # --- Symbol ---
    if i < n and spec[i] in _SYMBOL_CHARS:
        result.symbol = spec[i]
        i += 1

    # --- Zero-pad flag ---
    if i < n and spec[i] == "0":
        result.zero = True
        i += 1

    # An explicit "0" flag and a "0" fill under "=" align are the same request,
    # and d3 collapses them to one state before formatting.
    if result.zero or (result.fill == "0" and result.align == "="):
        result.zero = True
        result.fill = "0"
        result.align = "="  # zero-pad implies sign-then-zeros alignment

    # --- Width ---
    width_start = i
    while i < n and spec[i] in _DIGITS:
        i += 1
    if i > width_start:
        result.width = int(spec[width_start:i])

    # --- Comma grouping ---
    if i < n and spec[i] == ",":
        result.comma = True
        i += 1

    # --- Precision ---
    if i < n and spec[i] == ".":
        dot_pos = i
        i += 1  # consume '.'
        prec_start = i
        while i < n and spec[i] in _DIGITS:
            i += 1
        if i == prec_start:
            # d3's regex requires at least one digit after '.'; ".f" is invalid.
            raise D3FormatError(
                spec, dot_pos, "precision requires at least one digit after '.'"
            )
        result.precision = int(spec[prec_start:i])

    # --- Trim trailing zeros ---
    if i < n and spec[i] == "~":
        result.trim = True
        i += 1

    # --- Type letter ---
    if i < n:
        type_char = spec[i]
        i += 1
        if type_char not in _TYPE_CHARS:
            raise D3FormatError(
                spec,
                i - 1,
                f"invalid type {type_char!r}; "
                f"expected one of e, f, g, r, s, %, d, n, p, b, o, x, X, c, "
                f"or empty (default)",
            )
        result.type = type_char

    # --- Trailing garbage check ---
    if i < n:
        raise D3FormatError(
            spec,
            i,
            f"unexpected characters {spec[i:]!r} after type",
        )

    return result
