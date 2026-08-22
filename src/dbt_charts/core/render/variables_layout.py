"""Where every variable control sits — the strip's one layout authority.

Stage: RENDER
Purpose: Decide each control's box in board user units, and the height of the
band that holds them.

The chrome renderer draws from these boxes and the band takes its height from
the same result, so the two cannot disagree. That is the point: the code this
replaces had a sizer estimating widths from a character count while the browser
laid out something else, and the two answers drifted by up to 155% on a single
control.

Widths are *measured*, not guessed. A control whose width is content-driven —
a select showing ``All`` versus ``Latin America and the Caribbean`` — is sized
from the text it will actually draw. A control the theme fixes (`text`,
`number`, `checkbox`, `slider`, `daterange`) keeps its theme width, so
``variables.input.widths.*`` stays load-bearing rather than silently orphaned.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from dbt_charts.core.compile.models.variable.authored import VariableInputType
from dbt_charts.core.font_measure import get_font_measurer

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dbt_charts.core.compile.models.style.theme.variables import VariablesStyle

# Input kinds whose rendered width follows the text they display. Everything
# else is sized by the theme, and its box must not move when the value changes.
_CONTENT_SIZED = frozenset({"select", "multiselect", "radio", "date", "datepicker"})

# Ornaments the chrome draws inside a field's right edge — the one table saying
# which input gets which glyph. The strip imports these rather than keeping its
# own copy, and `ornament_width` is added to every control's width regardless of
# how the field itself was sized, so a glyph can never be drawn outside the
# field measured to hold it.
ARROW_ORNAMENT = frozenset({"select", "multiselect", "radio"})
CALENDAR_ORNAMENT = frozenset({"date", "datepicker", "daterange"})

# Widths reach here through several subtractions, so a row that fits exactly can
# read as overflowing by a fraction of a pixel. Sub-pixel slop gets the benefit
# of the doubt rather than costing a whole row. Public because the title-inline
# fit test asks the same question of the same numbers and has to answer it the
# same way — two epsilons kept in sync by comment is one epsilon that drifts.
WRAP_EPSILON = 0.5


@dataclass(frozen=True)
class ControlSpec:
    """One control to lay out, with its widget already resolved.

    ``input`` is the *refined* widget — the one the chrome will actually draw.
    Refinement needs option values, so it resolves once upstream and arrives
    here settled; laying out one widget while drawing another is the exact
    divergence this module exists to remove.
    """

    name: str
    input: VariableInputType
    label: str
    value: str


@dataclass(frozen=True)
class ControlBox:
    """One control's placed geometry, in board user units.

    ``label_width`` splits the box: the label draws in it, the field takes the
    rest after ``control_gap``. Published rather than re-measured downstream, so
    the width that was reserved is the width that gets drawn.
    """

    name: str
    input: VariableInputType
    label: str
    value: str
    x: float
    y: float
    width: float
    height: float
    label_width: float


@dataclass(frozen=True)
class VariablesLayout:
    """Every control's box plus the band that contains them."""

    boxes: tuple[ControlBox, ...]
    height: float
    rows: int


def lay_out_variables(
    specs: Sequence[ControlSpec], width: float, variables_style: VariablesStyle
) -> VariablesLayout:
    """Place each control into rows no wider than ``width``.

    Returns boxes in the order given — document order is what a host binds
    against, so it is not reordered to pack rows more tightly.
    """
    if not specs:
        return VariablesLayout(boxes=(), height=0.0, rows=0)

    gap = float(variables_style.gap)
    row_height = float(variables_style.container_height)
    available = max(width, 1.0)

    boxes: list[ControlBox] = []
    x = 0.0
    row = 0
    font_size = variables_style.font.size
    assert font_size is not None, "style.variables.font.size must be configured"
    for spec in specs:
        label_width = _text_width(f"{spec.label}:", float(font_size))
        # The ornament is added here, not inside `_input_width`, so a
        # theme-sized field reserves room for its glyph exactly like a measured
        # one — `daterange` is theme-sized and still draws a calendar.
        control_width = (
            label_width
            + float(variables_style.control_gap)
            + _input_width(spec, variables_style, float(font_size))
            + ornament_width(spec.input, float(font_size))
        )
        # First control on a row is placed wherever it lands, even when it is
        # wider than the strip: an overrun is visible and debuggable, a dropped
        # filter is not.
        if boxes and x + control_width > available + WRAP_EPSILON:
            row += 1
            x = 0.0
        boxes.append(
            ControlBox(
                name=spec.name,
                input=spec.input,
                label=spec.label,
                value=spec.value,
                x=x,
                y=row * (row_height + gap),
                width=control_width,
                height=row_height,
                label_width=label_width,
            )
        )
        x += control_width + gap

    rows = row + 1
    return VariablesLayout(
        boxes=tuple(boxes),
        height=rows * row_height + (rows - 1) * gap,
        rows=rows,
    )


def ornament_width(input_type: VariableInputType, font_size: float) -> float:
    """Width the type ornament occupies inside a field, in board user units.

    Sized from the text beside it — a derivation, not a new theme field to
    author. The layout reserves this and the chrome draws exactly it.
    """
    if input_type in ARROW_ORNAMENT:
        return font_size
    if input_type in CALENDAR_ORNAMENT:
        return font_size * 0.85
    return 0.0


def _input_width(
    spec: ControlSpec, variables_style: VariablesStyle, font_size: float
) -> float:
    """The input's rendered width — measured when content-driven, else themed."""
    widths = variables_style.input.widths
    padding = variables_style.input.padding

    if spec.input == "checkbox":
        return float(widths.checkbox)
    if spec.input in ("slider", "range"):
        # The track is fixed; the value beside it is what varies.
        return (
            float(widths.range)
            + float(variables_style.control_gap)
            + max(_text_width(spec.value, font_size), float(widths.slider_value_min))
        )

    boxed = (
        max(_text_width(spec.value, font_size), font_size)
        + float(padding.left)
        + float(padding.right)
    )
    if spec.input in _CONTENT_SIZED:
        # Sized by what it displays. An unset control still needs a field to be
        # a field, so the text slot floors at one em (handled above).
        return boxed

    # Theme-sized. The theme width is a floor, not a ceiling: it sets the
    # resting size, but a value too long for it still gets a box that holds it —
    # the chrome draws the whole value, and the reserved width has to be the
    # drawn width or controls overlap in every static export.
    if spec.input == "number":
        return max(float(widths.number), boxed)
    if spec.input == "daterange":
        return max(float(widths.daterange), boxed)
    return max(float(widths.text), boxed)


def _text_width(text: str, font_size: float) -> float:
    """Measured advance width of ``text`` at ``font_size``."""
    if not text:
        return 0.0
    return float(get_font_measurer().measure(text, font_size))
