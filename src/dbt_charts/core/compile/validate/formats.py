"""Compile-time validation of authored format-string slots.

Authored format strings are checked against three layers, in order: the
predefined engine vocabulary, the theme/board alias table, then
``d3_format.parse``. A spec that survives none of the three — a typo like
``percent_1`` — raises ``ERR-FORMAT-INVALID`` here, at compile, instead of
surfacing as ``ERR-INTERNAL`` deep inside rasterization (see
``core/compile/format.py``'s ``resolve_format`` docstring for the three-way
contract this validator runs ahead of).

Coverage is the authored surface: board-level ``style:`` and every chart,
recursively, plus the alias table's own targets (validated via
``_validate_board`` with ``allow_predefined=False``). Slots are recognised by
field name (``_FORMAT_FIELDS``) rather than by type annotation; every current
format field is spelled one of those three names, so the coverage is complete.

Time-format slots (axis ticks, table columns — anywhere a date-typed column
value might render) additionally accept a strftime-style spec (``%b %Y``):
an author may write the strftime form directly rather than through a predefined
alias (``date_short``).
"""

from __future__ import annotations

from collections.abc import Iterator

from pydantic import BaseModel

from d3_format import parse as _d3_parse
from d3_format.errors import D3FormatError
from dbt_charts.core.compile.errors import CompilationError
from dbt_charts.core.compile.models.board.normalized import Board
from dbt_charts.core.compile.models.primitives import FormatConfig
from dbt_charts.core.diagnostics.codes_compile import (
    ERR_FORMAT_INVALID,
    ERR_FORMAT_NATIVE_IN_VEGA_SLOT,
    ERR_FORMAT_PREDEFINED_SHADOW,
)
from dbt_charts.core.text.format_d3 import is_time_format
from dbt_charts.core.text.predefined_formats import (
    ALL_PREDEFINED_NAMES,
    PREDEFINED_NATIVE_NAMES,
)

# Field names that hold an authored format spec. Every current format field is
# spelled one of these; a future field named otherwise would need a new entry here.
_FORMAT_FIELDS = frozenset({"format", "number_format", "time_format"})

# Field names whose subtree may also carry a strftime spec: axis ticks, table
# columns, and the footer timestamp are the slots that render a date. Matched on
# structural field names during the walk, never on the flattened path -- a
# chart id or column name could otherwise spell one of these and silently
# widen what its siblings accept.
#
# `axis`, `axis_band`, and `axis_quantitative` are chart-local axis overrides
# (`style_cascade.py`'s `_merge_axis_cascade`) that merge into the same
# resolved axis `format` field as `axis_x`/`axis_y` -- a strftime spec there
# is exactly as legitimate.
_TIME_CAPABLE_FIELDS = frozenset(
    {
        "axis",
        "axis_x",
        "axis_y",
        "axis_band",
        "axis_quantitative",
        "mirror",
        "columns",
        "column_defaults",
        "time_format",
        "timestamp",
    }
)

# Field names whose child format slots are rendered by Vega (not Python).
# PREDEFINED_NATIVE members bypass d3 and have no Vega equivalent; they are
# rejected here so the author gets a compile error rather than a Vega crash.
# `number_format` and `time_format` are always Vega-painted regardless of parent;
# _iter_format_slots sets vega_painted=True for those field names directly.
_VEGA_PAINTED_PARENTS = frozenset(
    {
        "axis",
        "axis_x",
        "axis_y",
        "axis_band",
        "axis_quantitative",
        "mirror",
        "labels",  # MarkLabelsStyle / BarLabelsStyle / PointLabelsStyle
        "total_label",  # BarTotalLabelStyle: bar stack total label
        "total",  # ChartTotal: donut center total (pie.py → Vega text-mark encoding)
        "tooltip",  # TooltipStyle: Vega-Lite tooltip format across all chart families
        "data_table",  # ChartDataTableSource/Aggregate/PerSeries: _vl_format_calc emits into Vega calculate transform
    }
)


def _iter_format_slots(
    node: object, path: str, time_capable: bool, vega_painted: bool = False
) -> Iterator[tuple[str, str | FormatConfig, bool, bool]]:
    """Yield (field_path, spec, time_capable, vega_painted) for every format slot under ``node``."""
    if isinstance(node, BaseModel):
        for name in type(node).model_fields:
            if name == "query":  # SQL text and source/cache config, no format slots
                continue
            value = getattr(node, name)
            if value is None:
                continue
            child_time = time_capable or name in _TIME_CAPABLE_FIELDS
            child_vega = vega_painted or name in _VEGA_PAINTED_PARENTS
            child = f"{path}.{name}"
            if name in _FORMAT_FIELDS and isinstance(value, (str, FormatConfig)):
                # number_format and time_format are always Vega-painted: both feed
                # into axis.labels.format via the Layer-10 merge in axis_cascade.py
                # and are rendered by Vega, never by Python renderers.
                slot_vega = child_vega or name in ("number_format", "time_format")
                yield child, value, child_time, slot_vega
            else:
                yield from _iter_format_slots(value, child, child_time, child_vega)
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _iter_format_slots(
                value, f"{path}.{key}", time_capable, vega_painted
            )
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            yield from _iter_format_slots(
                value, f"{path}.{index}", time_capable, vega_painted
            )


def _validate_spec(
    value: str | FormatConfig,
    formats: dict[str, str],
    field_path: str,
    time_format: bool,
    allow_predefined: bool = True,
    vega_painted: bool = False,
) -> None:
    """Raise if ``value`` resolves to an unusable spec.

    Also called from ``_validate_board`` on the four global theme-resolved
    axis slots (``charts.axis``/``axis_x``/``axis_y``/``axis_quantitative``)
    to catch a theme-baked default (e.g.
    ``axis_quantitative.labels.format == "number_default"``) whose alias no
    longer resolves -- a board that clears ``style.formats`` to ``null`` is
    valid, compile()-accepted authoring (``formats`` merges key-wise;
    explicitly nulling it is the one way to drop an inherited key), but it
    is never an *authored* format string itself, so this module's own
    per-chart walk (``_iter_format_slots``) never reaches it.

    ``allow_predefined=False`` is passed when validating alias targets: a
    predefined name is not a valid d3-format spec, so ``formats: {mine: currency}``
    must raise at compile rather than silently passing validation and dying at
    render with ERR-INTERNAL.

    ``vega_painted=True`` is passed for slots rendered by Vega (axis labels,
    mark value labels, ``number_format``, ``time_format``, ``data_table``).
    PREDEFINED_NATIVE members bypass d3 entirely and have no Vega equivalent;
    they are rejected here so the author gets ERR-FORMAT-NATIVE-IN-VEGA-SLOT
    rather than a Vega runtime crash.
    """
    spec = value.spec if isinstance(value, FormatConfig) else value
    if not spec:
        return
    if allow_predefined and spec in ALL_PREDEFINED_NAMES:
        if vega_painted and spec in PREDEFINED_NATIVE_NAMES:
            raise CompilationError.from_code(
                ERR_FORMAT_NATIVE_IN_VEGA_SLOT,
                spec=spec,
                field_path=field_path,
                available=sorted(ALL_PREDEFINED_NAMES - PREDEFINED_NATIVE_NAMES),
            )
        return
    if spec in formats:
        return
    if time_format and is_time_format(spec):
        return
    try:
        _d3_parse(spec)
    except D3FormatError as e:
        # Alias targets must be valid d3 specs; predefined names are not valid
        # d3 specs and are already excluded. Including them in available would
        # produce "Did you mean 'currency'?" when rejecting "currency" as a target.
        available = (
            sorted(formats)
            if not allow_predefined
            else sorted({*formats, *ALL_PREDEFINED_NAMES})
        )
        raise CompilationError.from_code(
            ERR_FORMAT_INVALID,
            spec=spec,
            field_path=field_path,
            reason=e.reason,
            position=e.position,
            available=available,
        ) from e


def validate_board_format_specs(board: Board) -> None:
    """Walk a normalized Board tree, validating every authored format string.

    Recurses into nested boards -- each carries its own resolved theme, and
    therefore its own alias table (``board.chart_style_context.formats``).
    """
    _validate_board(board, set())


def _validate_board(board: Board, validated: set[int]) -> None:
    """Validate one board's format slots, skipping charts a descendant owns."""
    # Nested boards first. Normalization hoists a nested board's charts into
    # every ancestor's `charts` registry (`_collect_charts_from_layout`), by
    # reference -- so the identical chart object is reachable from a board whose
    # alias table never defined the alias that chart uses. Validating the owner
    # first and skipping the object here keeps every chart judged against the
    # table that actually resolves it, and walks each chart exactly once.
    for item in board.layout.items:
        if item.type == "board" and item.board is not None:
            _validate_board(item.board, validated)

    formats = board.chart_style_context.formats
    if formats is None:
        formats = {}
    # Shadowing a predefined enum member name in style.formats is always a bug:
    # the engine owns those names and resolve_format checks them first.
    for alias in formats:
        if alias in ALL_PREDEFINED_NAMES:
            raise CompilationError.from_code(
                ERR_FORMAT_PREDEFINED_SHADOW,
                spec=alias,
                field_path=f"style.formats.{alias}",
            )
    # An alias is only useful if its target resolves; checking the keys alone
    # would let `formats: {mine: bogus}` reach the render-time raise.
    # A predefined name (e.g. "currency") is not a valid d3 spec — reject it.
    for alias, target in formats.items():
        _validate_spec(
            target, {}, f"style.formats.{alias}", True, allow_predefined=False
        )
    # Theme-baked axis format defaults (e.g. axis_quantitative.labels.format
    # == "number_default") are never *authored* format strings, so the
    # per-chart walk below never reaches them -- but `style.formats: null`
    # is valid, compile()-accepted authoring that drops an inherited alias,
    # and it leaves that default unresolvable. Both facts
    # (chart_style_context.<slot>.labels.format and the alias table) are
    # already in hand here, so the guarantee belongs at this boundary, not
    # as a defensive re-check downstream in render (core/AGENTS.md's
    # normalizer-trusts-downstream rule).
    charts_style = board.chart_style_context
    for slot_name, axis_style in (
        ("axis", charts_style.axis),
        ("axis_x", charts_style.axis_x),
        ("axis_y", charts_style.axis_y),
        ("axis_quantitative", charts_style.axis_quantitative),
    ):
        label_format = axis_style.labels.format
        if label_format is not None:
            # Axis label format slots are Vega-painted — native formatters invalid.
            _validate_spec(
                label_format,
                formats,
                f"style.charts.{slot_name}.labels.format",
                True,
                vega_painted=True,
            )
    # Board-level `style:` is the same authored surface as chart-local `style:`
    # and reaches the same consumer, so it needs the same check. Walk the
    # authored patch, not resolved_style -- the latter carries theme content
    # this pass has no business rejecting.
    if board.authored_style is not None:
        for field_path, spec, timed, is_vega in _iter_format_slots(
            board.authored_style, "style", False
        ):
            _validate_spec(spec, formats, field_path, timed, vega_painted=is_vega)
    for chart_id, chart in board.charts.items():
        if id(chart) in validated:
            continue
        validated.add(id(chart))
        for field_path, spec, timed, is_vega in _iter_format_slots(
            chart, f"charts.{chart_id}", False
        ):
            _validate_spec(spec, formats, field_path, timed, vega_painted=is_vega)
