"""Typed global config contract for compiled runtime defaults.

``Config`` is the authoritative required runtime config object.
Engine knobs only — no presentation fields (style, theme).

Dynamic sections remain open-ended but are backed by Pydantic
mapping-like nodes that still support mapping access.
"""

from __future__ import annotations

from collections.abc import ItemsView, Iterator, KeysView, Mapping, ValuesView
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    model_validator,
)

from dbt_charts.core.compile.models.cache import CachePatch
from dbt_charts.core.compile.models.primitives import HtmlPolicy
from dbt_charts.core.compile.models.vega_lite.config import VegaLiteConfig
from dbt_charts.core.compile.vega_lite import VEGA_LITE_SCHEMA_URL


def _normalize_node_value(value: object) -> object:
    """Recursively normalize nested mapping values into ConfigNode objects."""
    if isinstance(value, BaseModel):
        return value
    if isinstance(value, Mapping):
        return ConfigNode.model_validate(dict(value))
    if isinstance(value, list):
        return [_normalize_node_value(item) for item in value]
    return value


class ConfigMappingBase(BaseModel, Mapping[str, Any]):
    """Pydantic model with mapping-like helpers for config consumers."""

    model_config = ConfigDict(extra="forbid")

    # Mapping access is a migration shim for dynamic config sections; cache the
    # assembled top-level view and invalidate when this model's own fields change.
    _mapping_cache: dict[str, Any] | None = PrivateAttr(default=None)

    def _mapping_data(self) -> dict[str, Any]:
        mapping_cache = object.__getattribute__(self, "__pydantic_private__").get(
            "_mapping_cache"
        )
        if mapping_cache is not None:
            return mapping_cache

        data: dict[str, Any] = {}
        for key, field in type(self).model_fields.items():
            value = object.__getattribute__(self, key)
            data[key] = value
            if field.alias and field.alias != key:
                data[field.alias] = value
        extra = object.__getattribute__(self, "__pydantic_extra__") or {}
        for key, value in extra.items():
            data[key] = value
        self._mapping_cache = data
        return data

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        if name != "_mapping_cache":
            self._mapping_cache = None

    def __delattr__(self, item: str) -> None:
        super().__delattr__(item)
        if item != "_mapping_cache":
            self._mapping_cache = None

    def __getitem__(self, key: str) -> Any:
        data = self._mapping_data()
        if key not in data:
            raise KeyError(key)
        return data[key]

    def __iter__(self) -> Iterator[str]:  # type: ignore[override]
        return iter(self._mapping_data())

    def __len__(self) -> int:
        return len(self._mapping_data())

    def __bool__(self) -> bool:
        return bool(self._mapping_data())

    def get(self, key: str, default: Any = None) -> Any:
        return self._mapping_data().get(key, default)

    def items(self) -> ItemsView[str, Any]:
        return self._mapping_data().items()

    def keys(self) -> KeysView[str]:
        return self._mapping_data().keys()

    def values(self) -> ValuesView[Any]:
        return self._mapping_data().values()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        data = self._mapping_data()
        if name in data:
            return data[name]
        raise AttributeError(name)

    def to_plain_dict(self, *, exclude_none: bool = True) -> dict[str, Any]:
        """Dump config models to plain nested Python dicts."""
        return self.model_dump(mode="python", exclude_none=exclude_none, by_alias=True)


class ConfigNode(ConfigMappingBase):
    """Open-ended config section that still supports attribute and mapping access."""

    # Accepts arbitrary keys — the config tree is open-ended by design.
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _normalize_input(cls, value: object) -> object:
        if isinstance(value, ConfigNode):
            return value
        if isinstance(value, Mapping):
            return {key: _normalize_node_value(item) for key, item in value.items()}
        return value


class ChartRenderingConfig(ConfigNode):
    class AxisConfig(ConfigNode):
        label_gap_spaces: int = Field(
            description="Word-space separation required between axis labels."
        )
        label_gap_spaces_numeric: int = Field(
            description="Word-space separation required between numeric axis labels."
        )

    class PieConfig(ConfigNode):
        wedge_label_min_share: float
        invisible_slice_share: float
        wheel_dominance_min_ratio: float
        label_reach_coefficient: float
        outer_fraction: float
        attached_table_gap_px: float
        hybrid_heading_gap_px: float
        right_placement_min_width_fraction: float
        right_placement_min_width_px: float
        right_placement_max_wheel_px: float

    class BarConfig(ConfigNode):
        grouped_bar_padding_inner: float
        grouped_bar_padding_outer: float
        # Calibrated estimate of one legend entry's row height (label line height
        # plus row padding) and the fixed title/padding chrome above the rows,
        # used to decide whether a stacked bar's legend must yield so its
        # segments keep visible height — see stack_legend_row_height_px's use in
        # compile/resolve/chart/bar.py.
        stack_legend_row_height_px: float
        stack_legend_chrome_height_px: float
        # A bar/stacked-total only gets the baseline-anchored hover band when
        # its own value is under this fraction of the chart's own largest
        # value -- separate from hover_band_extend_fraction (how big the band
        # itself is) so a merely-small-but-visible bar doesn't get one.
        hover_band_trigger_fraction: float
        # Fraction of the plot's pixel extent the hover band extends by, once
        # triggered.
        hover_band_extend_fraction: float
        # Vertical room one value label needs inside its bar segment, as a
        # multiple of the label font size: the glyph box plus a little air.
        # Drives the fit test in render/chart/features/value_labels.py, which
        # drops a label whose segment provably cannot hold it.
        label_fit_line_height_multiplier: float = Field(gt=0)

    class TypeInferenceConfig(ConfigNode):
        max_ordinal_buckets: int

    class FrameConfig(ConfigNode):
        footer_rule_gap_px: int
        footer_timestamp_gap_px: int

    class DataTableConfig(ConfigNode):
        divider_gap: float
        chart_data_table_max_x_ticks: int

    class StrokeConfig(ConfigNode):
        min_width: float
        max_width: float

    class EndpointLabelsConfig(ConfigNode):
        # 0 collapses to the "no explicit pane width" sentinel and ≥1 restores the
        # rail-wider-than-canvas crash this cap exists to prevent.
        max_width_fraction: float = Field(gt=0, lt=1)
        line_height_multiplier: float = Field(gt=0)

    class GradientConfig(ConfigNode):
        nice_tick_count: int

    pie: PieConfig
    bar: BarConfig
    type_inference: TypeInferenceConfig
    frame: FrameConfig
    data_table: DataTableConfig
    stroke: StrokeConfig
    axis: AxisConfig
    endpoint_labels: EndpointLabelsConfig
    gradient: GradientConfig


class InspectorConfig(ConfigNode):
    tree_max_depth: int


class RenderingConfig(ConfigNode):
    class PngRenderingConfig(ConfigNode):
        scale: float

    png: PngRenderingConfig


class VegaRuntimeConfig(ConfigNode):
    """Vega-Lite renderer runtime config.

    Presentation fields (default_theme, default_palette) have moved to the
    Board/style cascade. Only the renderer runtime config and schema URL remain.
    """

    config: VegaLiteConfig = Field(default_factory=VegaLiteConfig)

    @property
    def schema(self) -> str:  # type: ignore[override]
        return VEGA_LITE_SCHEMA_URL


class ExecutionConfig(ConfigNode):
    # DuckDB-backed executors serialize access via _DUCKDB_EXECUTE_LOCK, so raising
    # max_workers beyond 1 doesn't increase actual parallelism for local DuckDB files.
    # The setting is meaningful for external warehouse executors (BigQuery, Snowflake).
    max_workers: int
    # Safety ceiling on how long a single query may run, enforced as a server-side
    # statement timeout on network warehouses (never a client-side abandon — see
    # execute/adapters/sql_adapter.py). DuckDB and SQLite are local file databases
    # with no server to enforce a timeout, so this has no effect on them.
    # Overridable per source via sources.<name>.max_query_duration_seconds.
    max_query_duration_seconds: int = Field(
        gt=0, description="Maximum seconds a single query may run (must be > 0)."
    )
    # Hard cap on files matched per glob pattern in file sources. Error is raised
    # before any file is read so a runaway glob fails fast. Override in dbt_charts.yml.
    max_glob_file_count: int = Field(
        gt=0, description="Maximum files a single glob may match (must be > 0)."
    )
    # Safety ceiling on rows returned by a single query, enforced by bounding the
    # driver's own fetch (fetchmany()/execute(limit=...)) rather than rewriting
    # SQL. Exceeding it truncates the result and emits WARN_QUERY_RESULT_TRUNCATED
    # rather than failing the query. A Cloud deployment ceiling
    # (DCT_MAX_ROWS_CEILING) can only lower this, never raise it. Override in
    # dbt_charts.yml under execution.max_rows.
    max_rows: int = Field(
        gt=0, description="Maximum rows a single query may return (must be > 0)."
    )
    # Safety ceiling on the serialized byte size of a single query result,
    # checked incrementally during row accumulation so an oversized result is
    # never fully serialized to measure it. Exceeding it truncates the result
    # and emits WARN_QUERY_RESULT_TRUNCATED rather than failing the query. A
    # Cloud deployment ceiling (DCT_MAX_RESULT_BYTES_CEILING) can only lower
    # this, never raise it. Override in dbt_charts.yml under
    # execution.max_result_bytes.
    max_result_bytes: int = Field(
        gt=0,
        description="Maximum serialized byte size of a single query result "
        "(must be > 0).",
    )
    # sqlglot uses different dialect names than Dataface's public-facing dialect strings.
    # This mapping normalizes Dataface names to sqlglot equivalents before parsing.
    dialect_aliases: dict[str, str]


class ServerConfig(ConfigNode):
    model_config = ConfigDict(extra="forbid")

    debug: bool
    nav: bool
    port: int | None = None  # None = use deterministic project-path port
    # When True, non-board frontmatter keys in .md files are rendered as a
    # metadata table at the top of the page.  Off by default so AGENTS.md,
    # README, and other prose files don't suddenly acquire header tables.
    markdown_metadata_table: bool


class ProjectCacheConfig(CachePatch):
    """Project cache root (``cache:`` in dbt_charts.yml): the cascade root every
    source/board/query inherits, plus the backend location.

    Deliberately the **same shape as every other scope** (``ttl`` — inherited
    from CachePatch), so ``cache: 4h`` means the same thing everywhere;
    ``path`` is the one project-only field, reachable via the block form
    (``cache: {ttl: 4h, path: .dft-cache.duckdb}``). There is no separate
    backend on/off switch — the store is provisioned lazily when any resolved
    query policy is enabled. The shipped root lives in
    ``defaults/default_config.yml``.

    One scalar is missing here that every other scope accepts: ``cache: true``.
    See the validator below.
    """

    @model_validator(mode="after")
    def _root_must_state_a_ttl(self) -> ProjectCacheConfig:
        """Caching on at the root with no ttl means forever — say so out loud.

        Reachable only by writing ``cache: true``: the scalar replaces the
        shipped block whole (``deep_merge_dict`` recurses only between
        mappings), and unlike every other scope the root has nothing above it
        to take a ttl from. So the one spelling that promises nothing about
        duration would quietly pick the longest one there is.
        """
        if self.enabled and self.ttl is None:
            raise ValueError(
                "the project cache root has to say how long to keep results — "
                "write cache: <duration> (e.g. cache: 24h) or cache: forever. "
                "(cache: true means 'keep the ttl from the scope above', and "
                "the project root has no scope above it.)"
            )
        return self

    # None = the zero-config in-memory store, a documented outcome rather than
    # a fallback (see the field description). Defaulted, not required, so the
    # project scope accepts the same bare `cache: 4h` scalar as every other
    # scope — a required project-only key would make that spelling unauthorable.
    path: str | None = Field(
        default=None,
        description=(
            "Persistent cache file location. None = ephemeral in-memory cache "
            "auto-provisioned by the engine; a string path selects a persistent "
            "cache file (created if absent). Both are documented outcomes, not "
            "a fallback."
        ),
    )


class Config(ConfigMappingBase):
    """Authoritative required runtime settings model.

    Engine knobs and definition registries only. Presentation (style, board
    layout) lives in the Board cascade via charts/meta.yaml — not here.

    Closed top-level fields define the supported global settings surface; any
    stray key in dbt_charts.yml (e.g. ``style:``, ``board:``, ``theme:``) raises a
    pydantic ValidationError (``Extra inputs are not permitted``). The default
    theme is an engine-level fallback (``DCT_DEFAULT_THEME`` env var →
    ``SHIPPED_DEFAULT_THEME_NAME``), not a dbt_charts.yml key.
    """

    model_config = ConfigDict(extra="forbid")

    cache: ProjectCacheConfig
    chart_rendering: ChartRenderingConfig
    execution: ExecutionConfig
    geo_sources: ConfigNode
    # Deployment wins (DCT_HTML_POLICY_CEILING), then this project ceiling, then the board field.
    # Default (trusted-raw) is permissive — no ceiling — for local development.
    # Cloud pins DCT_HTML_POLICY_CEILING=safe-subset at the deployment level.
    html_policy_ceiling: HtmlPolicy
    inspector: InspectorConfig
    rendering: RenderingConfig
    server: ServerConfig
    terminal: ConfigNode
    palettes: ConfigNode
    vega: VegaRuntimeConfig
    dbt_grays: ConfigNode
    dbt_creams: ConfigNode
    strict: bool | None = None  # None = strict mode not configured; defaults to off
    sources: ConfigNode | None = None  # None = no explicit sources section in config
    # Canonical public URL for dct render exports (e.g. "https://dashboards.example.com").
    # When set, rendered links are fully-qualified. Empty string means root-relative (default).
    public_url: str

    @model_validator(mode="after")
    def _validate_palette_contract(self) -> Config:
        category = self.palettes.get("vivid-10")
        if not isinstance(category, list) or not category:
            raise ValueError("palettes.vivid-10 must be present and non-empty")
        return self


def as_plain_mapping(value: ConfigMappingBase | Mapping[str, Any]) -> dict[str, Any]:
    """Project a compiled config model or raw mapping into a plain dict."""
    if isinstance(value, ConfigMappingBase):
        return value.to_plain_dict(exclude_none=False)
    return dict(value)


def is_mapping_like(value: object) -> bool:
    """Return whether a value can be consumed through mapping helpers."""
    return isinstance(value, ConfigMappingBase | Mapping)
