"""Authored board types — YAML input representation.

Stage: COMPILE (Input)
Purpose: Types that map directly to the YAML board schema.

Contains the top-level AuthoredBoard and its layout sub-shapes, plus
LayoutType for board layout variants.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    model_validator,
)

from dbt_charts.core.aliases import normalize_alias_url
from dbt_charts.core.compile.models.cache import CachePatch
from dbt_charts.core.compile.models.chart.authored import AuthoredChart
from dbt_charts.core.compile.models.markers import Merge, Strategy
from dbt_charts.core.compile.models.primitives import HtmlPolicy
from dbt_charts.core.compile.models.query.authored import AuthoredQuery
from dbt_charts.core.compile.models.refs import (
    ChartRef,
    QueryRef,
    VariableRef,
    normalize_query_value,
)
from dbt_charts.core.compile.models.schema_names import ThemeName
from dbt_charts.core.compile.models.style.authored import StylePatch
from dbt_charts.core.compile.models.variable.authored import (
    SingleRowBoolProbe,
    Variable,
)


def _ref_or_inline(v: object, ref_cls: type) -> str:
    """Classify a union value as '@ref' or '@inline'.

    Returns '@ref' when v is already a typed ref instance, a bare cross-file ref
    string, or a dict that contains a 'ref' key. Returns '@inline' otherwise.

    Tag names start with '@' to prevent collision with user-chosen YAML keys
    ('ref', 'inline') in Pydantic error locs.

    Routing any dict with a 'ref' key to the ref branch produces a clean
    'extra inputs not permitted' error from the ref model (extra="forbid")
    rather than an opaque 'extra inputs' error on the inline model.
    """
    if isinstance(v, ref_cls):
        return "@ref"
    if isinstance(v, str):
        return "@ref"
    if isinstance(v, dict) and "ref" in v:
        return "@ref"
    return "@inline"


def _var_discriminator(v: object) -> str:
    return _ref_or_inline(v, VariableRef)


def _query_discriminator(v: object) -> str:
    return _ref_or_inline(v, QueryRef)


def _chart_discriminator(v: object) -> str:
    return _ref_or_inline(v, ChartRef)


VariableOrRef = Annotated[
    Annotated[Variable, Tag("@inline")] | Annotated[VariableRef, Tag("@ref")],
    Discriminator(_var_discriminator),
]
QueryOrRef = Annotated[
    Annotated[AuthoredQuery, Tag("@inline")] | Annotated[QueryRef, Tag("@ref")],
    Discriminator(_query_discriminator),
]
ChartOrRef = Annotated[
    Annotated[AuthoredChart, Tag("@inline")] | Annotated[ChartRef, Tag("@ref")],
    Discriminator(_chart_discriminator),
]

# ============================================================================
# LAYOUT SUB-SHAPES
# ============================================================================

_CHARTREF_KEYS = frozenset({"chart", "width", "height", "description", "visible"})
_CHARTREF_MSG = (
    "Layout item uses removed `chart:` reference form. "
    "Use a bare chart name (`- chart_name`) or a nested board wrapper:\n"
    "  - height: 600\n"
    "    rows:\n"
    "      - chart_name"
)


def _reject_chartref_dict(v: Any) -> Any:
    if (
        isinstance(v, dict)
        and isinstance(v.get("chart"), str)
        and v.keys() <= _CHARTREF_KEYS
    ):
        raise ValueError(_CHARTREF_MSG)
    return v


def _check_layout_list(v: Any) -> Any:
    if not isinstance(v, list):
        return v
    for item in v:
        _reject_chartref_dict(item)
    return v


def _check_layout_item(v: Any) -> Any:
    return _reject_chartref_dict(v)


class GridItem(BaseModel):
    """Grid layout item with position and span.

    Uses grid terminology (not pixels):
        col: Column position (0-indexed)
        row: Row position (0-indexed)
        col_span: Number of columns to span (default 1)
        row_span: Number of rows to span (default 1)
        width: Alias for col_span (more intuitive)
        height: Alias for row_span (more intuitive)

    Example:
        - item: my_chart
          col: 0
          row: 0
          width: 12      # Takes half of 24-column grid (alias for col_span)
          height: 2      # Spans 2 rows (alias for row_span)
    """

    model_config = ConfigDict(extra="forbid")

    item: Annotated[
        str | AuthoredBoard | AuthoredChart | dict[str, AuthoredChart],
        BeforeValidator(_check_layout_item),
    ] = Field(
        description="Chart name or inline chart/board definition to place in this grid cell."
    )
    col: int | None = Field(
        default=None, description="Column position (0-indexed). Auto-placed if omitted."
    )
    row: int | None = Field(
        default=None, description="Row position (0-indexed). Auto-placed if omitted."
    )
    col_span: int | None = Field(
        default=None, description="Number of columns to span (width in grid units)."
    )
    row_span: int | None = Field(
        default=None, description="Number of rows to span (height in grid units)."
    )
    width: int | None = Field(
        default=None, description="Alias for col_span (more intuitive name)."
    )
    height: int | None = Field(
        default=None, description="Alias for row_span (more intuitive name)."
    )
    description: str | None = Field(
        default=None,
        description="Optional metadata for AI search and context tooltips.",
    )


class GridLayout(BaseModel):
    """Grid layout configuration."""

    model_config = ConfigDict(extra="forbid")

    columns: int = Field(
        default=24, description="Number of grid columns (default: 24)."
    )
    row_height: str | None = Field(
        default=None, description="Default row height as a CSS value (e.g., '200px')."
    )
    gap: Literal["sm", "md", "lg", "xl"] | None = Field(
        default=None, description="Gap between grid cells (sm, md, lg, xl)."
    )
    default_width: int | None = Field(
        default=None,
        description="Default column span for items that don't specify width.",
    )
    default_height: int | None = Field(
        default=None,
        description="Default row span for items that don't specify height.",
    )
    items: list[GridItem] = Field(
        description="List of grid items with position and span configuration."
    )


class TabItem(BaseModel):
    """Tab layout item."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(description="Tab label displayed in the tab bar.")
    icon: str | None = Field(
        default=None,
        description="Optional icon shown in the tab (e.g., emoji or icon name).",
    )
    description: str | None = Field(
        default=None,
        description="Optional metadata for AI search and context tooltips.",
    )
    text: str | None = Field(
        default=None, description="Markdown text content shown in this tab."
    )
    style: StylePatch | None = Field(
        default=None, description="Style patch for this tab's content area."
    )

    # Layout fields (tab can contain nested layouts)
    rows: Annotated[
        list[str | AuthoredBoard | AuthoredChart | dict[str, AuthoredChart]] | None,
        BeforeValidator(_check_layout_list),
    ] = Field(default=None, description="Vertical stack layout for this tab's content.")
    cols: Annotated[
        list[str | AuthoredBoard | AuthoredChart | dict[str, AuthoredChart]] | None,
        BeforeValidator(_check_layout_list),
    ] = Field(default=None, description="Horizontal layout for this tab's content.")
    grid: GridLayout | None = Field(
        default=None, description="CSS-grid layout for this tab's content."
    )
    tabs: TabLayout | None = Field(
        default=None, description="Nested tab layout (tabs within tabs)."
    )


class TabLayout(BaseModel):
    """Tab layout configuration.

    The `id` field controls the variable name and URL param for tab selection.
    If not provided, auto-generates as 'tab', 'tab_1', etc.

    Example YAML:
        tabs:
          id: view              # → URL param ?view=overview
          default: overview
          items:
            - title: Overview
              rows: [kpi_row]
            - title: Details
              rows: [detail_table]
    """

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(
        default=None,
        description="Variable name and URL param base for tab selection (auto-generated if omitted).",
    )
    position: Literal["top", "left"] = Field(
        default="top", description="Tab bar position (top or left)."
    )
    default: str | None = Field(
        default=None, description="Default tab title to activate on load."
    )
    items: list[TabItem] = Field(description="List of tab items.")


# ============================================================================
# BOARD (TOP-LEVEL)
# ============================================================================


class BoardDetails(BaseModel):
    """Collapsible section metadata for a board.

    Authored as a block or string shorthand:

        details: "Show more"                        # str shorthand
        details:
          summary: "Show more"
          expanded_title: "Hide"
          expanded: false
    """

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(description="Label shown when the section is collapsed.")
    expanded_title: str | None = Field(
        default=None,
        description="Label shown when the section is expanded. Defaults to summary.",
    )
    expanded: bool = Field(
        default=False, description="Whether the section is open by default."
    )


def _coerce_details(v: Any) -> Any:
    """Coerce str → BoardDetails dict for the BeforeValidator on AuthoredBoard.details."""
    if isinstance(v, str):
        return {"summary": v}
    return v


class _BoardDesugarMixin(BaseModel):
    """Shared authoring-input mixin: desugar ``theme:`` and normalize query shorthand.

    Inherited by both ``AuthoredBoard`` and ``BoardPatch`` so that meta files and
    extends fragments (validated as ``BoardPatch`` by the merge engine) accept the
    exact same authored input the canonical model does. Every desugaring/normalizing
    validator that turns valid authored YAML into the model's field shape belongs
    here — not on ``AuthoredBoard`` alone — because ``build_patch_model_ext`` only
    carries over validators that live on the patch model's base class.

    Single-write: ``_desugar_theme`` strips ``theme`` and sets ``extends``.
    ``AuthoredBoard`` does NOT override ``_desugar_theme``.

    Note: ``normalized.Board`` still carries a ``theme`` field + ``set_theme``
    method — a live parallel theme-name channel that re-cascades
    ``resolved_style`` when the theme is switched after compile (see
    ``normalize/dispatch.py``; read at serve time in ``core/serve/server.py``).  The
    Phase-3 cutover to ``resolve_board`` deletes the ``theme`` field, folding it
    into the single ``extends`` path.
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _normalize_queries(cls, data: object) -> object:
        """Normalize string query shorthand to full form before field validation.

        ``queries: {q: "SELECT ..."}`` is authoring sugar for
        ``queries: {q: {type: sql, sql: "SELECT ..."}}``. Runs for all boards —
        top-level and nested boards embedded in rows/cols/tabs/grid — and for every
        meta/extends fragment, since they all share this mixin. Delegates to the
        single shared helper ``normalize_query_value`` (models.refs).
        """
        if not isinstance(data, dict):
            return data
        raw_queries = data.get("queries")
        if not isinstance(raw_queries, dict):
            return data
        return {
            **data,
            "queries": {
                name: normalize_query_value(q) for name, q in raw_queries.items()
            },
        }

    @model_validator(mode="before")
    @classmethod
    def _desugar_theme(cls, data: Any) -> Any:
        """Desugar ``theme: X`` → ``extends: X`` (single-write: theme removed).

        ``theme:`` is authoring sugar for ``extends:``. Having both is an error.
        """
        if not isinstance(data, dict) or "theme" not in data:
            return data
        theme_val = data.get("theme")
        extends_val = data.get("extends")
        if extends_val is not None and theme_val is not None:
            raise ValueError(
                "Cannot specify both 'theme:' and 'extends:'. "
                "'theme:' is sugar for 'extends:' — use one or the other."
            )
        data = dict(data)
        if theme_val is not None:
            data["extends"] = theme_val
        del data["theme"]  # always strip theme: (even null — it is not a field)
        return data


class AuthoredBoard(_BoardDesugarMixin):
    """AuthoredBoard definition from YAML.

    This is the top-level input type representing a complete board.
    A board contains definitions (variables, queries, charts) and a layout.

    Example YAML:
        title: Sales Board
        description: Overview of sales metrics

        source: my_postgres  # Default source for all queries

        variables:
          date_range:
            input: daterange
            default: ["2024-01-01", "2024-12-31"]

        queries:
          sales: SELECT * FROM sales WHERE date BETWEEN ...

        charts:
          revenue:
            query: sales
            type: line
            x: date
            y: amount

        rows:
          - revenue

    Layout:
        Exactly one layout type should be present (rows, cols, grid, or tabs).
        Layout items can be:
        - Chart name (string reference)
        - Inline chart definition (dict with query and type)
        - Nested board (dict with layout keys)

    Source:
        Optional source shorthand: ``source: my_db`` sets the default connection
        for all queries. Inheritable via meta.yaml cascade.
    """

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str | None, Merge(Strategy.OVERRIDE)] = Field(
        default=None, description="Dashboard title displayed at the top."
    )
    description: Annotated[str | None, Merge(Strategy.OVERRIDE)] = Field(
        default=None, description="Description text for the dashboard."
    )
    tags: Annotated[list[str] | None, Merge(Strategy.APPEND, nested=Strategy.CHILD)] = (
        Field(default=None, description="Tags for categorization and search.")
    )
    aliases: list[str] | None = (
        Field(  # no Merge marker — identity field, validate-absent in extends/meta lane
            default=None,
            description=(
                "Additional URLs that redirect to this board's canonical file-path URL. "
                "Each entry must be absolute (leading /). Requests to these URLs are "
                "redirected (302) to the board's real path, query string preserved. "
                "Valid on .yml, .yaml, .md, and folder index.* boards."
            ),
        )
    )

    text: Annotated[str | None, Merge(Strategy.OVERRIDE)] = Field(
        default=None, description="Markdown text content for text-only sections."
    )
    html_policy: Annotated[HtmlPolicy, Merge(Strategy.OVERRIDE)] = Field(
        default="none",
        description=(
            "HTML rendering policy for the board's body text. One of: "
            '"none" (default) — HTML is escaped and rendered as plain markdown; '
            '"safe-subset" — reserved for a parser-checked allowlist (not yet '
            "enforced — currently renders as none); "
            '"trusted-raw" — raw HTML via foreignObject. TRUSTED-CONTENT ONLY: '
            "this is NOT a security sandbox. <script>/event-handlers are stripped "
            "as a best-effort guard, not a guarantee. Enable only on first-party "
            "boards you fully control."
        ),
    )

    # Default source name for all queries; inheritable via meta.yaml cascade.
    source: Annotated[
        str | None,
        Merge(Strategy.OVERRIDE),
    ] = Field(
        default=None,
        description="Default source name for all queries in this board. Inheritable via meta.yaml cascade.",
    )

    # The dashboard's own cache layer, between source and query in the cascade:
    # every query this board declares inherits it and may refine it. Not
    # Optional — a CachePatch with no fields set already means "authors
    # nothing, inherit everything", so a None state would be a second spelling
    # of the same thing (cascade placeholder, per models/AGENTS.md).
    #
    # No Merge marker: DEEP by type inference, matching `merge_cache_layers`
    # field-for-field. Overriding the meta.yaml block whole would make
    # `cache: true` — the one spelling that sets nothing but the switch — drop
    # the directory's ttl for the project root's.
    cache: CachePatch = Field(
        default_factory=CachePatch,
        description=(
            "Cache policy for every query in this dashboard, e.g. cache: 1h — "
            "queries inherit it and may refine it; cache: false opts the whole "
            "dashboard out. Inheritable via the meta.yaml cascade."
        ),
    )

    # Scoped definitions
    variables: Annotated[
        dict[str, VariableOrRef] | None, Merge(Strategy.BY_KEY, nested=Strategy.CHILD)
    ] = Field(
        default_factory=dict,
        description="Variable definitions for dynamic filtering and UI controls.",
    )
    queries: Annotated[dict[str, QueryOrRef] | None, Merge(Strategy.BY_KEY)] = Field(
        default_factory=dict,
        description="Named query definitions (SQL, CSV, MetricFlow, HTTP, etc.).",
    )
    charts: Annotated[dict[str, ChartOrRef] | None, Merge(Strategy.BY_KEY)] = Field(
        default_factory=dict,
        description=(
            "Named chart definitions. When no explicit layout is present, "
            "charts render as an implicit row layout in authored order."
        ),
    )

    # Layout (exactly one should be present)
    rows: Annotated[
        list[str | AuthoredBoard | AuthoredChart | dict[str, AuthoredChart]] | None,
        BeforeValidator(_check_layout_list),
        Merge(Strategy.APPEND, nested=Strategy.CHILD),
    ] = Field(
        default=None,
        description="Vertical stack layout: list of chart names or inline chart/board definitions.",
    )
    cols: Annotated[
        list[str | AuthoredBoard | AuthoredChart | dict[str, AuthoredChart]] | None,
        BeforeValidator(_check_layout_list),
        Merge(Strategy.APPEND, nested=Strategy.CHILD),
    ] = Field(
        default=None,
        description="Horizontal layout: list of chart names or inline chart/board definitions.",
    )
    grid: Annotated[GridLayout | None, Merge(Strategy.DEEP, nested=Strategy.CHILD)] = (
        Field(
            default=None,
            description="CSS-grid style layout with explicit row/column placement.",
        )
    )
    tabs: Annotated[TabLayout | None, Merge(Strategy.DEEP, nested=Strategy.CHILD)] = (
        Field(
            default=None,
            description="Tabbed navigation layout where each tab contains its own layout.",
        )
    )

    # Card gap toggle: when true, adds gap between cards.
    card_gap: Annotated[bool, Merge(Strategy.OVERRIDE)] = Field(
        default=False,
        description="When True, adds gap between cards. Default: cards are edge-to-edge (0 gap).",
    )

    # Focus mode
    chart_focus: Annotated[str | None, Merge(Strategy.OVERRIDE)] = Field(
        default=None,
        description="Render only this named chart with its dependent variables (useful for embedding or SVG export).",
    )

    # Collapsible section (details)
    details: Annotated[
        BoardDetails | None, BeforeValidator(_coerce_details), Merge(Strategy.OVERRIDE)
    ] = Field(
        default=None,
        description=(
            "Collapsible section metadata. "
            "String shorthand: details: 'text' → BoardDetails(summary='text'). "
            "Block form: details: {summary: ..., expanded_title: ..., expanded: false}."
        ),
    )

    # Styling & dimensions (when nested)
    id: str | None = (
        Field(  # no Merge marker — identity field, validate-absent in extends/meta lane
            default=None,
            description="Explicit ID for this board. Auto-generated from filename if omitted.",
        )
    )
    style: Annotated[StylePatch | None, Merge(Strategy.DEEP)] = Field(
        default=None,
        description="Style patch (background, padding, border, etc.). Background and semantic color tokens (accent, muted) cascade to nested child boards.",
    )
    width: Annotated[str | int | None, Merge(Strategy.OVERRIDE)] = Field(
        default=None,
        description="Width when nested (e.g., '50%', '400px', or an integer in pixels). "
        "On the root board there is no parent to place it into, so it instead sets "
        "the board's own width (equivalent to 'style.frame.width') — percentages "
        "are rejected there since there's nothing to size relative to.",
    )
    height: Annotated[str | int | None, Merge(Strategy.OVERRIDE)] = Field(
        default=None,
        description="Height when nested (e.g., '300px' or an integer in pixels).",
    )
    visible: Annotated[
        bool | str | SingleRowBoolProbe | None, Merge(Strategy.OVERRIDE)
    ] = Field(
        default=None,
        description=(
            "Controls whether this layout item is rendered. "
            "Accepts a bool, variable name, Jinja expression, "
            "or {query, column} probe."
        ),
    )

    # Inheritance chain — names and/or relative paths of boards this board extends.
    # The resolution engine folds the chain (low→high priority) before merging.
    # `override` here: a child's extends replaces the parent's; the parent's own
    # extends is already folded in during chain resolution, never re-merged.
    extends: Annotated[ThemeName | str | list[str] | None, Merge(Strategy.OVERRIDE)] = (
        Field(
            default=None,
            description="Board name(s) or relative path(s) this board inherits from, low to high priority. A built-in theme name resolves it directly.",
        )
    )

    # Auto-link: synthesize a detail-page link for table charts when no explicit
    # link: is set. Default off — opt in at the board level (per-board override).
    # Explicit link: always wins; link: none suppresses per chart.
    # dct serve-scoped for Phase 1; project-level opt-in is deferred.
    auto_link: bool = Field(
        default=False,
        description=(
            "When True, table charts with no explicit link: automatically link each "
            "row to its canonical /data/<source>/<schema>/<table>/detail/ page. "
            "Default off. Explicit link: always wins; set link: ~ to suppress per chart."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def reject_board_key(cls, data: Any) -> Any:
        """Reject 'board' as a top-level key."""
        if isinstance(data, dict) and "board" in data:
            raise ValueError(
                "'board:' is not valid. Board properties (title, rows, queries, etc.) "
                "should be at the top level of the YAML file, not nested under 'board:'."
            )
        return data

    @model_validator(mode="after")
    def validate_aliases(self) -> AuthoredBoard:
        """Every alias must be absolute, per ``aliases``' own description.

        Checked through ``normalize_alias_url`` so the authored surface and the
        redirect index cannot disagree about what a well-formed alias is; the
        normalized value is discarded, since the board stores what the author
        wrote.
        """
        if self.aliases is None:
            return self
        for alias in self.aliases:
            normalize_alias_url(alias)
        return self

    @model_validator(mode="after")
    def validate_layout(self) -> AuthoredBoard:
        """Ensure at least one layout type or content is defined."""
        layouts = [self.rows, self.cols, self.grid, self.tabs]
        defined = [layout for layout in layouts if layout is not None]
        if len(defined) > 1:
            raise ValueError(
                "Board can only have one layout type (rows, cols, grid, or tabs)"
            )
        if (
            len(defined) == 0
            and self.text is None
            and not self.title
            and not self.description
            and not self.charts
        ):
            raise ValueError(
                "Board must have at least one layout type, text, title, description, or chart"
            )
        return self

    def get_default_source(self) -> str | None:
        """Return the default source name, or None."""
        return self.source


# Resolve forward references (GridItem.item and TabItem.rows/cols reference types
# defined later in the file — rebuild after all classes are in scope)
GridItem.model_rebuild()
TabItem.model_rebuild()
AuthoredBoard.model_rebuild()


# ============================================================================
# LAYOUT TYPE
# ============================================================================


class LayoutType(str, Enum):
    """Layout types for organizing charts.

    - rows: Vertical stack of items
    - cols: Horizontal arrangement of items
    - grid: CSS-grid style layout with columns
    - tabs: Tabbed navigation between views
    """

    ROWS = "rows"
    COLS = "cols"
    GRID = "grid"
    TABS = "tabs"
