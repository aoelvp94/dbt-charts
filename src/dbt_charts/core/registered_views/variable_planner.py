"""Metadata-driven variable planner for entity views.

Purpose: Choose which columns to expose as board variables in a generated
         entity view, and produce ordinary Variable instances that pass
         through the normal Dataface validate/normalize/render pipeline.

Public API:
- ``PlannerColumn`` — typed column descriptor (name + db type).
- ``InvalidColumnNameError`` — raised when a column name cannot be used
  as a variable id and was not included before the check.
- ``plan_entity_variables(cols, include)`` — select columns and emit a
  ``{name: Variable}`` dict ready for ``AuthoredBoard.variables``.

Variable id contract: a generated one-column, one-control variable's id
exactly matches the source column name. Columns whose names are not valid
variable ids must be excluded (via ``include``) or they raise
``InvalidColumnNameError``. No silent name mangling — a mangled name would
break filtered links like ``/data/.../sales/?status=closed``.

Default selection (no include): boolean, string/text, and date/timestamp
columns. Numeric measures and complex types (ARRAY, VARIANT, JSON, MAP,
etc.) are excluded from the default set because they are not useful filter
controls.
"""

from __future__ import annotations

from dataclasses import dataclass

from dbt_charts.core.compile.models.variable.authored import Variable
from dbt_charts.core.compile.resolve.chart.link_keys import (
    is_complex_db_type as _is_complex,
    is_identity_keyable as _is_identity_keyable,
    is_valid_column_identifier,
)
from dbt_charts.core.inspect.db_types import (
    STRING_TYPES,
    TEMPORAL_TYPES,
    extract_base_type,
)

_BOOLEAN_BASES: frozenset[str] = frozenset({"BOOLEAN", "BOOL"})


def _is_default_selected(col: PlannerColumn) -> bool:
    """True when a column should be included in the default filter set.

    Selects booleans, strings, and date/timestamp columns.
    Excludes numerics and complex types.
    """
    base = extract_base_type(col.actual_type)
    if _is_complex(col.actual_type):
        return False
    return base in _BOOLEAN_BASES or base in STRING_TYPES or base in TEMPORAL_TYPES


def _variable_for(col: PlannerColumn) -> Variable:
    """Build a Variable for a column using a sensible input type."""
    base = extract_base_type(col.actual_type)

    if base in _BOOLEAN_BASES:
        return Variable(input="checkbox", visible=True)

    if base in TEMPORAL_TYPES:
        return Variable(input="datepicker", visible=True)

    # String and anything else selected by caller
    return Variable(input="text", visible=True)


@dataclass(frozen=True)
class PlannerColumn:
    """Typed column descriptor fed to the variable planner.

    Attributes:
        name: Column name from the schema query result (``row["name"]``).
        actual_type: Database type string (``row["actual_type"]``), e.g.
            ``"VARCHAR"``, ``"BOOLEAN"``, ``"TIMESTAMP"``.
    """

    name: str
    actual_type: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("PlannerColumn.name must not be empty.")

    @property
    def is_valid_variable_id(self) -> bool:
        """True when ``name`` can be used directly as a board variable id."""
        return is_valid_column_identifier(self.name)

    @property
    def is_identity_keyable(self) -> bool:
        """True when this column can serve as a detail-page filter/key variable.

        See ``_is_identity_keyable``: integers, exact (scale-0) fixed-point, and
        strings round-trip through ``?col=value`` + ``WHERE col=value``; floats,
        fractional decimals, temporals, booleans, and complex types do not.
        """
        return _is_identity_keyable(self.actual_type)


class InvalidColumnNameError(ValueError):
    """Raised when one or more column names cannot be used as variable ids.

    Raised before any variables are produced so the error is caught early.
    Includes all offending names in a single message so the caller can fix
    them all at once rather than discovering them one by one.
    """


def plan_entity_variables(
    cols: list[PlannerColumn],
    *,
    include: set[str] | None = None,
) -> dict[str, Variable]:
    """Select columns and produce ``{name: Variable}`` for an entity board.

    Selection semantics:
    - No ``include``: use the metadata-chosen default set (booleans, strings,
      date/timestamp — not numerics or complex types).
    - ``include``: use only those column names.

    Unknown names in ``include`` (columns not present in ``cols``) are
    silently ignored.

    The variable id is always exactly the source column name (no mangling).
    Columns whose names are not valid variable ids and that survive
    ``include`` filtering raise ``InvalidColumnNameError``.

    Args:
        cols: Column descriptors from the pre-template schema query result.
        include: Column names to include explicitly. ``None`` means use the
            default heuristic selection.

    Returns:
        ``{column_name: Variable}`` for every selected column, in the same
        order as ``cols``. Each dict key is the variable id; it matches the
        source column name exactly.

    Raises:
        InvalidColumnNameError: If any selected column's name is not a valid
            board variable id. Includes all offending names in one message.
    """
    if include is not None:
        # Keep only the requested names, but iterate `cols` so the result stays
        # in column order (a set's iteration order is non-deterministic, which
        # would scramble URL param order in the entity detail link).
        selected: list[PlannerColumn] = [c for c in cols if c.name in include]
    else:
        # Default heuristic: booleans, strings, date/timestamp — not measures.
        selected = [c for c in cols if _is_default_selected(c)]

    # Validate all selected column names before emitting any variable.
    invalid = [c.name for c in selected if not c.is_valid_variable_id]
    if invalid:
        quoted = ", ".join(repr(n) for n in invalid)
        raise InvalidColumnNameError(
            f"Column name(s) {quoted} cannot be used as variable ids because they "
            "contain characters not allowed in identifiers (spaces, dashes, dots, "
            "leading digits, etc.). Either exclude these columns from the variable "
            "selection or rename them in the database."
        )

    return {c.name: _variable_for(c) for c in selected}
