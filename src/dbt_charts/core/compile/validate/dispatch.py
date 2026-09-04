"""Schema validation module.

Stage: COMPILE (Step 2 of 4)
Purpose: Validate AuthoredBoard structure and cross-references.

Entry Points:
    - validate_board(board: AuthoredBoard) -> List[ValidationError]

Inputs:
    - AuthoredBoard (from parser)

Outputs:
    - List[ValidationError] (empty if valid)

This validator focuses on semantic validation that Pydantic cannot handle:
- Cross-reference validation (chart → query)
- Layout item references (layout → chart)
- Consistency checks between related fields

Pydantic already handles:
- Type validation
- Required fields
- Field constraints
- Nested validation

Dependencies:
    - .types (AuthoredBoard, Chart)
    - .errors (ValidationError)

See also:
    - compile/parse/parser.py: Previous step
    - compile/normalize/dispatch.py: Next step
"""

from collections.abc import Mapping
from typing import Any

from dbt_charts.core.compile.config import user_facing_theme_names
from dbt_charts.core.compile.errors import ValidationError
from dbt_charts.core.compile.merge import get_theme_names, is_path_ref
from dbt_charts.core.compile.models.board.authored import (
    AuthoredBoard,
    TabItem,
)
from dbt_charts.core.compile.models.chart.authored import (
    AuthoredChart,
    CalloutChart,
    _BaseChartFields,
)
from dbt_charts.core.compile.models.query.authored import _BaseQueryFields
from dbt_charts.core.compile.models.refs import ChartRef, QueryRef
from dbt_charts.core.compile.parse.parser import looks_like_sql
from dbt_charts.core.diagnostics.codes_compile import (
    ERR_UNKNOWN_QUERY,
    ERR_UNKNOWN_THEME,
    ERR_UNRESOLVED_REFERENCE,
)

LayoutNode = str | AuthoredBoard | AuthoredChart | TabItem | dict[str, AuthoredChart]


def _layout_children(node: LayoutNode) -> list[LayoutNode]:
    """Direct layout children of a board or tab node."""
    if not isinstance(node, (AuthoredBoard, TabItem)):
        return []
    children: list[LayoutNode] = []
    if node.rows:
        children.extend(node.rows)
    if node.cols:
        children.extend(node.cols)
    if node.grid:
        children.extend(gi.item for gi in node.grid.items)
    if node.tabs:
        children.extend(node.tabs.items)
    return children


def _declared_names(board: AuthoredBoard) -> tuple[set[str], set[str]]:
    """Chart and query names declared anywhere in the board tree.

    The compiler's chart and query registries are board-global — any layout
    may reference any chart declared anywhere in the tree — so validation has
    to resolve against that same namespace. Resolving against only the top
    level reports valid cross-board authoring as an unresolved reference.
    """
    charts: set[str] = set()
    queries: set[str] = set()
    stack: list[LayoutNode] = [board]
    while stack:
        node = stack.pop()
        if isinstance(node, AuthoredBoard):
            charts |= set(node.charts or {})
            queries |= set(node.queries or {})
        stack.extend(_layout_children(node))
    return charts, queries


def validate_board(board: AuthoredBoard) -> list[ValidationError]:
    """Validate a AuthoredBoard structure and cross-references.

    Stage: COMPILE (Step 2 of 4: Validation)

    Performs semantic validation beyond what Pydantic provides:
    - Chart → Query references exist
    - Layout items reference existing charts

    Note: Pydantic already validates types, required fields, and nested
    structures during parsing. This function adds cross-reference validation.

    Args:
        board: Parsed AuthoredBoard to validate

    Returns:
        List of ValidationError objects (empty if valid)

    Example:
        >>> board = parse_yaml(yaml_content)
        >>> errors = validate_board(board)
        >>> if errors:
        ...     for e in errors:
        ...         print(f"Error: {e}")
    """
    errors: list[ValidationError] = []

    # Board-global, matching the registries the compiler resolves against.
    chart_names, query_names = _declared_names(board)

    # Validate chart → query references
    errors.extend(_validate_chart_query_references(board.charts or {}, query_names))

    # Validate layout → chart references
    errors.extend(_validate_layout_references(board, chart_names, query_names))

    # Validate theme names (`theme:` desugars into `extends:` before we see it)
    errors.extend(validate_theme_names(board))

    return errors


def validate_theme_names(board: AuthoredBoard) -> list[ValidationError]:
    """Every plain-name ``extends`` entry must be a built-in theme.

    ``theme:`` is sugar for ``extends:`` — by validation time the two are the
    same field. Only ``merged_patch`` resolves an entry as a board, and it runs
    on one node: the root board of a ``compile_file``, whose chain it folds and
    replaces with the selected theme name. Everywhere else — an in-memory
    ``compile()``, and every nested board in either lane — the entry reaches
    here untouched and nothing downstream will resolve it, so a plain name can
    only have meant a theme. Hence the message claims nothing about board
    lookup: none was attempted.

    Path refs are skipped because they are unambiguously board references, not
    because something resolves them at these positions (nothing does — see the
    path-ref follow-up); flagging them as unknown themes would just be wrong.
    """
    # Accept every shipped theme (diagnostic-only boards extend the internal
    # ones); list only the ones an author is meant to pick from.
    theme_names = get_theme_names()
    available = user_facing_theme_names()
    errors: list[ValidationError] = []
    stack: list[LayoutNode] = [board]
    while stack:
        node = stack.pop()
        if isinstance(node, AuthoredBoard) and node.extends is not None:
            raw = node.extends
            entries = [raw] if isinstance(raw, str) else raw
            errors.extend(
                ValidationError.from_code(
                    ERR_UNKNOWN_THEME, theme=entry, available=available
                )
                for entry in entries
                if not is_path_ref(entry) and entry not in theme_names
            )
        stack.extend(_layout_children(node))
    return errors


def _validate_chart_query_references(
    charts: Mapping[str, _BaseChartFields | CalloutChart | ChartRef],
    query_names: set[str],
) -> list[ValidationError]:
    """Validate that charts reference existing queries.

    Args:
        charts: Chart definitions (chart patch instance or ChartRef cross-file references)
        query_names: Available query names

    Returns:
        List of validation errors
    """
    errors: list[ValidationError] = []

    for chart_name, chart in charts.items():
        # Skip cross-file chart references — resolved during normalization
        if isinstance(chart, ChartRef):
            continue

        # CalloutChart is minimal — no query field by design.
        if isinstance(chart, CalloutChart):
            continue

        query_ref = chart.query

        # Skip validation for blank charts (no query)
        if query_ref is None:
            continue

        # Skip validation for inline query definitions and cross-file refs —
        # these are handled during normalization
        if isinstance(query_ref, (_BaseQueryFields, QueryRef)):
            continue

        # Strip "queries." prefix if present
        if query_ref.startswith("queries."):
            query_ref = query_ref[8:]

        # Cross-file references (e.g., "other_file.queries.name") are resolved later
        if "." in query_ref:
            continue

        if query_ref not in query_names:
            if looks_like_sql(query_ref):
                # Bare SQL string — normalizer will promote it to an inline query; skip here.
                continue

            errors.append(
                ValidationError.from_code(
                    ERR_UNKNOWN_QUERY,
                    chart_name=chart_name,
                    query_name=query_ref,
                )
            )

    return errors


def _validate_layout_references(
    board: AuthoredBoard,
    chart_names: set[str],
    query_names: set[str],
) -> list[ValidationError]:
    """Validate that layout items reference existing charts.

    Args:
        board: AuthoredBoard to validate
        chart_names: Available chart names
        query_names: Available query names

    Returns:
        List of validation errors
    """
    errors: list[ValidationError] = []

    # Collect all layout items
    layout_items = _get_layout_items(board)

    for location, item in layout_items:
        if isinstance(item, str):
            # String reference - must be a chart name (or special reference)
            if _is_special_reference(item):
                continue

            if item not in chart_names:
                error = ValidationError.from_code(
                    ERR_UNRESOLVED_REFERENCE, ref=item, context=" in layout item"
                )
                # `{context}` is a pre-formatted message suffix, but `fields`
                # is the machine-readable surface — store the bare value, so
                # this agrees with the `ReferenceError` site that raises the
                # same code from the normalizer.
                error.fields["context"] = "layout item"
                error.field_path = location
                errors.append(error)

        elif isinstance(item, (dict, _BaseChartFields)):
            # Inline chart - validate its query reference
            query_ref = item.get("query") if isinstance(item, dict) else item.query

            # Skip validation for blank charts (no query)
            if query_ref is None:
                continue

            # Skip validation for inline query definitions and cross-file refs —
            # these are handled during normalization
            if isinstance(query_ref, (_BaseQueryFields, QueryRef, dict)):
                continue

            if query_ref.startswith("queries."):
                query_ref = query_ref[8:]

            # Skip cross-file references
            if "." not in query_ref and query_ref not in query_names:
                if looks_like_sql(query_ref):
                    continue
                error = ValidationError.from_code(
                    ERR_UNKNOWN_QUERY,
                    chart_name=location,
                    query_name=query_ref,
                )
                # The offending value is the inline chart's `query:`, not the
                # whole item — same precision as the named-chart site, which
                # resolves to `charts.<id>.query`.
                error.field_path = f"{location}.query"
                errors.append(error)

    return errors


def _get_layout_items(board: AuthoredBoard) -> list[tuple[str, Any]]:
    """Extract all layout items with their locations.

    Locations are source-map keys: dotted all the way down, sequence indices
    included (`rows.0`, `tabs.items.1.rows.0`). They are used both to resolve
    a diagnostic's position and as the human-readable location in its message,
    so there is one spelling rather than a display form and a lookup form that
    can drift.

    Args:
        board: AuthoredBoard to extract items from

    Returns:
        List of (location, item) tuples
    """
    items: list[tuple[str, Any]] = []

    if board.rows:
        for idx, item in enumerate(board.rows):
            items.append((f"rows.{idx}", item))
            items.extend(_get_nested_items(item, f"rows.{idx}"))

    if board.cols:
        for idx, item in enumerate(board.cols):
            items.append((f"cols.{idx}", item))
            items.extend(_get_nested_items(item, f"cols.{idx}"))

    if board.grid:
        # `GridItem.item` is a nested field, so the authored scalar lives at
        # `grid.items.<n>.item` — `grid.items.<n>` is the wrapper block.
        for idx, grid_item in enumerate(board.grid.items):
            location = f"grid.items.{idx}.item"
            items.append((location, grid_item.item))
            items.extend(_get_nested_items(grid_item.item, location))

    if board.tabs:
        for idx, tab_item in enumerate(board.tabs.items):
            if tab_item.rows:
                for i, item in enumerate(tab_item.rows):
                    location = f"tabs.items.{idx}.rows.{i}"
                    items.append((location, item))
                    items.extend(_get_nested_items(item, location))
            if tab_item.cols:
                for i, item in enumerate(tab_item.cols):
                    location = f"tabs.items.{idx}.cols.{i}"
                    items.append((location, item))
                    items.extend(_get_nested_items(item, location))

    return items


def _get_nested_items(item: Any, parent_location: str) -> list[tuple[str, Any]]:
    """Extract items from nested board structures.

    A nested board reaches here as an `AuthoredBoard`: the parser types layout
    items, so matching `dict` would miss every nesting.

    A nested board declaring its own `charts:` needs no special case — those
    names are already in the board-global set `_declared_names` collects, so
    its items resolve like any other.

    Args:
        item: Item that might be a nested board
        parent_location: Parent location string

    Returns:
        List of (location, item) tuples from nested structures
    """
    if not isinstance(item, AuthoredBoard):
        return []

    items: list[tuple[str, Any]] = []
    for key, entries in (("rows", item.rows), ("cols", item.cols)):
        if entries is None:
            continue
        for idx, entry in enumerate(entries):
            location = f"{parent_location}.{key}.{idx}"
            items.append((location, entry))
            items.extend(_get_nested_items(entry, location))
    return items


def _is_special_reference(ref: str) -> bool:
    """Check if a reference is a special type (partial, remote, etc.).

    Special references are validated during normalization, not here.

    Args:
        ref: Reference string to check

    Returns:
        True if this is a special reference type
    """
    # Partial references start with underscore
    if ref.startswith("_"):
        return True

    # Cross-file references contain dots or slashes
    return bool("." in ref or "/" in ref)
