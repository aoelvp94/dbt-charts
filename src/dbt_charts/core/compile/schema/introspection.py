"""Pydantic model introspection — Layer 1 of the two-layer schema IR.

Walks AuthoredBoard and all reachable authored models once, producing an
AuthorableSchema IR. Renderers (json_schema, prompt, markdown, erd) consume
this IR — no rendering logic lives here.

Entry point: introspect() -> AuthorableSchema
"""

from __future__ import annotations

import dataclasses
import typing
from enum import Enum
from typing import Any, ForwardRef, Literal, get_args, get_origin

from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefinedType

from dbt_charts.core.compile.models.board.authored import AuthoredBoard
from dbt_charts.core.compile.models.chart.authored import (
    AUTHORED_CHART_VARIANTS,
    AuthoredChart,
)
from dbt_charts.core.compile.models.factories import _PatchBase
from dbt_charts.core.compile.models.markers import Facet
from dbt_charts.core.compile.models.query.authored import (
    AuthoredCompactValuesQuery,
    AuthoredHttpQuery,
    AuthoredMetricflowQuery,
    AuthoredQuery,
    AuthoredSchemaQuery,
    AuthoredSqlQuery,
    AuthoredValuesQuery,
)
from dbt_charts.core.compile.models.source import (
    BigQuerySourceConfig,
    CsvSourceConfig,
    DbtProfileSourceConfig,
    DuckDBSourceConfig,
    HttpSourceConfig,
    JsonSourceConfig,
    MySQLSourceConfig,
    ParquetSourceConfig,
    PostgresSourceConfig,
    RedshiftSourceConfig,
    SnowflakeSourceConfig,
    SQLiteSourceConfig,
)
from dbt_charts.core.compile.models.style.authored import PaginationConfig


@dataclasses.dataclass
class SchemaField:
    name: str
    description: str
    type_repr: str
    required: bool
    default: Any
    default_repr: (
        str | None
    )  # human-readable default for display (None = no meaningful default)
    enum_values: list[str | bool] | None
    nested_models: list[str]  # class names of nested AuthorableModels (empty = none)
    container: str | None = None  # "list" or "dict" if the model is in a container
    extra_union_types: list[str] = dataclasses.field(
        default_factory=list
    )  # primitive type names alongside models or enums in a union
    container_mapping_models: list[str] = dataclasses.field(default_factory=list)
    # Per-position type_repr strings for a FIXED-length tuple field (e.g.
    # tuple[int, float] -> ("int", "float")); None for every other shape,
    # including a variadic tuple[X, ...] (which is list-shaped, not fixed).
    tuple_item_reprs: tuple[str, ...] | None = None
    is_extra_key: bool = (
        False  # True for synthetic '<name>' fields from __pydantic_extra__
    )
    inherit_from: tuple[str, ...] = ()  # ordered fallback dot-paths (Inherit marker)
    inherit_slot: str | None = None  # source subtree path (InheritSlot marker)
    inherit_slot_exclude: frozenset[str] = (
        frozenset()
    )  # leaf names InheritSlot excludes
    # Semantic facets declared on the field — what the value *means*, which the
    # type and the description cannot say. Today: `Color` and `Channel`.
    facets: tuple[Facet, ...] = ()


@dataclasses.dataclass
class UnionSpec:
    """Variant metadata for a synthetic union entry like AuthoredChart."""

    # None means the variants are structurally distinguished. This is used for
    # authored queries whose type tag may be inferred from variant-only keys.
    discriminator: str | None
    variants: dict[str, str]  # tag -> model name (e.g. "bar" -> "BarChart")


@dataclasses.dataclass
class AuthorableModel:
    name: str
    doc: str
    fields: list[SchemaField]
    generated: bool = False  # True for _PatchBase subclasses (build_patch_model output)
    union: UnionSpec | None = (
        None  # set on synthetic union entries (e.g. AuthoredChart)
    )
    # True when the model validates with nothing set, so an editor can bring the
    # object into existence one field at a time. False means it cannot: a
    # required field (`BoardDetails.summary`) or a model validator
    # (`MultiplesConfig`, which demands `rows` or `columns`) refuses the
    # single-key object, and only a form that writes the whole thing will do.
    # Synthetic union entries have no class to ask, and default to False.
    empty_is_valid: bool = False


@dataclasses.dataclass
class AuthorableSchema:
    root: str
    models: dict[str, AuthorableModel]


def schema_path_to_yaml(abs_path: str) -> str:
    """Convert an InheritGraph dot-path to its authored YAML key path.

    InheritGraph paths use the model class name as root: ``"Style.charts.axis"``.
    Authored YAML uses the lowercase key: ``"style.charts.axis"``.
    """
    dot = abs_path.index(".")
    return abs_path[:dot].lower() + abs_path[dot:]


# Registry mapping union alias objects to their IR model names.
# Used in _nested_model_names to short-circuit discriminated union traversal.
_UNION_ALIASES = {
    AuthoredChart: "AuthoredChart",
    AuthoredQuery: "AuthoredQuery",
}


def _unwrap_annotated(annotation: Any) -> Any:
    """Strip Annotated[X, *metadata] → X. Idempotent on plain types."""
    if hasattr(annotation, "__metadata__"):
        return annotation.__origin__
    return annotation


def _is_authored_model(cls: Any) -> bool:
    """Return True if cls should be included in the IR.

    Includes authored.* models, primitives, _PatchBase subclasses, compiled
    style models from style/theme/, and *Patch models from models.cache (CachePatch is the authored
    overlay for the cache block — same role as *StylePatch, different module).
    """
    if not (isinstance(cls, type) and issubclass(cls, BaseModel)):
        return False
    if issubclass(cls, _PatchBase):
        return True
    module = getattr(cls, "__module__", "")
    return (
        ".authored" in module
        or module.endswith("primitives")
        or module.endswith("style.theme")
        or ".style.theme." in module
        or (module.endswith(".models.cache") and cls.__name__.endswith("Patch"))
    )


def _extract_enum_values(annotation: Any) -> list[str | bool] | None:
    """Return enum values if annotation is an Enum or Literal, else None.

    Values are returned as their native Python types (str, int, bool, etc.) so
    the JSON Schema renderer emits the correct JSON type (true, not "True").
    """
    annotation = _unwrap_annotated(annotation)
    origin = get_origin(annotation)
    args = get_args(annotation)

    # Literal["foo", "bar", ...] or Literal[True]
    if origin is Literal:
        return [a for a in args if isinstance(a, (str, bool))]

    # str Enum subclass
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return [e.value for e in annotation]

    # Union — look for a Literal or Enum inside (e.g. ChartType | None)
    if origin is type(None) or origin is None:
        return None
    # handle Union (typing.Union has origin = types.UnionType or typing.Union)
    if args:
        for arg in args:
            result = _extract_enum_values(arg)
            if result:
                return result

    return None


def _nested_model_names(annotation: Any) -> list[str]:
    """Return all authored model class names reachable from annotation.

    Returns an empty list if no authored models are found.
    For plain types, returns a one-element list; for discriminated unions,
    returns one entry per branch. Union aliases (e.g. AuthoredChart) resolve
    to a single opaque name without expanding their branches.
    """
    if annotation in _UNION_ALIASES:
        return [_UNION_ALIASES[annotation]]
    annotation = _unwrap_annotated(annotation)
    if annotation in _UNION_ALIASES:
        return [_UNION_ALIASES[annotation]]
    if _is_authored_model(annotation):
        return [annotation.__name__]

    origin = get_origin(annotation)
    args = get_args(annotation)
    if not args:
        return []

    # dict[K, V] — recurse into the value type only
    if origin is dict and len(args) == 2:
        return _nested_model_names(args[1])

    # list[SomeModel] or Union/Optional — collect all authored branches, dedup by class name
    result: list[str] = []
    for arg in args:
        result.extend(_nested_model_names(arg))
    return list(dict.fromkeys(result))


def _all_model_names_in_annotation(annotation: Any) -> list[str]:
    """Return class names of ALL BaseModel subclasses reachable from annotation.

    Unlike _nested_model_names, this is not limited to "authored" modules.
    Used for __pydantic_extra__ synthetic fields where the value type may
    reference source connector configs (models.source module).
    """
    annotation = _unwrap_annotated(annotation)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation.__name__]

    origin = get_origin(annotation)
    args = get_args(annotation)
    if not args:
        return []

    if origin is dict and len(args) == 2:
        return _all_model_names_in_annotation(args[1])

    result: list[str] = []
    for arg in args:
        if arg is not type(None):
            result.extend(_all_model_names_in_annotation(arg))
    return result


def _type_repr(annotation: Any) -> str:
    """Human-readable type string for display in docs/prompts."""
    annotation = _unwrap_annotated(annotation)
    if annotation is None or annotation is type(None):
        return "None"
    if isinstance(annotation, ForwardRef):
        return annotation.__forward_arg__

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is Literal:
        values = [repr(a) for a in args]
        return f"one of: {', '.join(values)}"

    # Guard: only match plain types, not generic aliases (list[X], dict[K,V])
    # On Python 3.10, isinstance(list[X], type) can return True for GenericAlias.
    if origin is None and isinstance(annotation, type):
        if issubclass(annotation, Enum):
            return f"one of: {', '.join(e.value for e in annotation)}"
        return annotation.__name__

    if origin is list:
        if args:
            return f"list[{_type_repr(args[0])}]"
        return "list"

    if origin is dict:
        if len(args) == 2:
            return f"dict[{_type_repr(args[0])}, {_type_repr(args[1])}]"
        return "dict"

    if origin is tuple:
        if not args:
            return "tuple"
        if len(args) == 2 and args[1] is Ellipsis:
            return f"tuple[{_type_repr(args[0])}, ...]"
        return f"tuple[{', '.join(_type_repr(a) for a in args)}]"

    # Union types (X | Y | None) — deduplicate branches (discriminated unions may
    # have the same class under multiple Tag() aliases, e.g. BarChart for bar+histogram)
    if args:
        non_none = [a for a in args if a is not type(None)]
        nullable = any(a is type(None) for a in args)
        parts = list(dict.fromkeys(_type_repr(a) for a in non_none))
        result = " | ".join(parts)
        if nullable and len(non_none) > 0:
            result += " | None"
        return result

    if annotation is Any:
        return "Any"
    return str(annotation)


def _get_container(annotation: Any) -> str | None:
    """Return 'list' or 'dict' if annotation wraps a nested model in a container."""
    annotation = _unwrap_annotated(annotation)
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is list:
        return "list"
    if origin is dict:
        return "dict"
    if args:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _get_container(non_none[0])
    return None


def _tuple_item_reprs(
    annotation: Any,  # type-state: explicit_any — arbitrary typing construct, matches _get_container/_type_repr
) -> tuple[str, ...] | None:
    """Return per-position type_repr strings for a FIXED-length tuple field.

    None for every other shape, including a variadic tuple[X, ...] (that's
    list-shaped: one item type repeated, not one type per position).
    """
    annotation = _unwrap_annotated(annotation)
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is tuple:
        if not args or (len(args) == 2 and args[1] is Ellipsis):
            return None
        return tuple(_type_repr(a) for a in args)
    if args:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _tuple_item_reprs(non_none[0])
    return None


_PRIMITIVE_NAMES = frozenset({"str", "int", "float", "bool"})


def _default_repr(field_info: FieldInfo) -> str | None:
    """Return a human-readable default string for display, or None if no meaningful default."""
    if field_info.is_required():
        return None
    default = field_info.default
    if isinstance(default, PydanticUndefinedType):
        factory = field_info.default_factory
        if factory is dict:
            return "{}"
        if factory is list:
            return "[]"
        return None
    if default is None:
        return None
    if isinstance(default, bool):
        return str(default).lower()
    if isinstance(default, str):
        return f'"{default}"'
    if isinstance(default, (int, float)):
        return str(default)
    return None


def _extra_union_types(annotation: Any) -> list[str]:
    """Primitive type names that sit alongside models or enums in a union.

    Returns the names (e.g. ["str", "bool"]) so the renderer can include
    them in anyOf alongside $ref or enum branches.
    Container values recurse because ``list[str | AuthoredChart]`` needs the
    same scalar branch on its item schema as a bare union does.
    """
    annotation = _unwrap_annotated(annotation)
    origin = get_origin(annotation)
    args = get_args(annotation)
    if not args:
        return []

    if origin in (list, dict):
        return _extra_union_types(args[-1])

    result: list[str] = []
    for arg in args:
        # Unwrap per-arm: a validated primitive alias (Duration =
        # Annotated[str, AfterValidator]) is still a str arm of the union, and
        # dropping it makes a `Literal[...] | Duration` field look like a closed
        # enum in every generated schema.
        arg = _unwrap_annotated(arg)
        if arg is type(None):
            continue
        if _is_authored_model(arg):
            continue
        arg_origin = get_origin(arg)
        if arg_origin in (list, dict):
            result.extend(_extra_union_types(arg))
            continue
        if arg_origin is Literal:
            continue
        if isinstance(arg, type) and issubclass(arg, Enum):
            continue
        if (
            arg_origin is None
            and isinstance(arg, type)
            and arg.__name__ in _PRIMITIVE_NAMES
        ):
            result.append(arg.__name__)
    return list(dict.fromkeys(result))


def _container_mapping_models(annotation: type) -> list[str]:
    """Return named-map value models nested in a list item union."""
    annotation = _unwrap_annotated(annotation)
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is dict and len(args) == 2:
        return _nested_model_names(args[1])
    if origin is list and args:
        return _container_mapping_models(args[0])
    result: list[str] = []
    for arg in args:
        result.extend(_container_mapping_models(arg))
    return list(dict.fromkeys(result))


def _build_schema_field(
    name: str, field_info: FieldInfo, annotation: Any
) -> SchemaField:
    """Convert one Pydantic field into a SchemaField."""
    from dbt_charts.core.compile.models.markers import Inherit, InheritSlot

    required = field_info.is_required()
    default = field_info.default if not required else dataclasses.MISSING
    metadata = field_info.metadata or []
    inherit = next((m for m in metadata if isinstance(m, Inherit)), None)
    inherit_slot = next((m for m in metadata if isinstance(m, InheritSlot)), None)
    return SchemaField(
        name=name,
        description=field_info.description or "",
        type_repr=_type_repr(annotation),
        required=required,
        default=default,
        default_repr=_default_repr(field_info),
        enum_values=_extract_enum_values(annotation),
        nested_models=_nested_model_names(annotation),
        container=_get_container(annotation),
        extra_union_types=_extra_union_types(annotation),
        container_mapping_models=_container_mapping_models(annotation),
        tuple_item_reprs=_tuple_item_reprs(annotation),
        inherit_from=(inherit.from_path,) if inherit is not None else (),
        inherit_slot=inherit_slot.from_path if inherit_slot is not None else None,
        inherit_slot_exclude=(
            inherit_slot.exclude if inherit_slot is not None else frozenset()
        ),
        facets=tuple(m for m in metadata if isinstance(m, Facet)),
    )


def _collect_models(
    model_cls: type[BaseModel],
    collected: dict[str, AuthorableModel],
) -> None:
    """Recursively walk model_cls and all reachable authored sub-models."""
    name = model_cls.__name__
    if name in collected:
        return

    # Use __doc__ directly (not inspect.getdoc) to avoid MRO walk that pulls in
    # Pydantic BaseModel's "[Models](../concepts/models.md)" doc for generated patches.
    raw_doc = model_cls.__doc__ or ""
    doc = ""
    for line in raw_doc.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith(("!!! ", "??? ", ":::")):
            doc = stripped
            break

    fields: list[SchemaField] = []

    for field_name, field_info in model_cls.model_fields.items():
        # Two ways to say "not authorable, keep it out of the reference":
        # `exclude=True` for fields that also must not serialize, and
        # `json_schema_extra={"internal": True}` for derived fields whose value
        # still has to survive a model_dump round-trip.
        extra = field_info.json_schema_extra
        if field_info.exclude or (isinstance(extra, dict) and extra.get("internal")):
            continue
        annotation = field_info.annotation
        display_name = field_info.alias or field_name
        sf = _build_schema_field(display_name, field_info, annotation)
        fields.append(sf)

    # Synthesize a '<name>' field for models with typed __pydantic_extra__.
    # get_type_hints() is needed because from __future__ import annotations turns
    # annotations into strings; vars() gives the raw (unresolved) form.
    try:
        hints = typing.get_type_hints(model_cls)
        extra_annotation = hints.get("__pydantic_extra__")
    except NameError:
        extra_annotation = None
    if extra_annotation is not None:
        ea_origin = get_origin(extra_annotation)
        ea_args = get_args(extra_annotation)
        if ea_origin is dict and len(ea_args) == 2:
            value_annotation = ea_args[1]
            fields.append(
                SchemaField(
                    name="<name>",
                    description="Additional named entry.",
                    type_repr=_type_repr(value_annotation),
                    required=False,
                    default=None,
                    default_repr=None,
                    enum_values=None,
                    nested_models=_all_model_names_in_annotation(value_annotation),
                    is_extra_key=True,
                )
            )

    collected[name] = AuthorableModel(
        name=name,
        doc=doc,
        fields=fields,
        generated=issubclass(model_cls, _PatchBase),
        empty_is_valid=_empty_is_valid(model_cls),
    )

    # Recurse into nested authored models
    for sf in fields:
        for model_name in sf.nested_models:
            if model_name not in collected:
                nested_cls = _find_nested_class(model_cls, model_name)
                if nested_cls is not None and _is_authored_model(nested_cls):
                    _collect_models(nested_cls, collected)


def _empty_is_valid(model_cls: type[BaseModel]) -> bool:
    """Whether `model_cls()` validates — asked of the model, not restated here.

    Required fields are already on `SchemaField`, but a model validator is not:
    `MultiplesConfig` declares every field optional and then refuses an object
    with neither `rows` nor `columns`. Constructing one is the only answer that
    cannot drift from the validator that owns the rule.
    """
    try:
        model_cls()
    except ValidationError:
        return False
    return True


def _find_nested_class(parent_cls: type[BaseModel], class_name: str) -> type | None:
    """Find a nested model class by name from a parent model's field annotations."""
    for field_info in parent_cls.model_fields.values():
        annotation = field_info.annotation
        cls = _find_in_annotation(annotation, class_name)
        if cls is not None:
            return cls
    return None


def _find_in_annotation(annotation: Any, class_name: str) -> type | None:
    """Recursively search annotation tree for a class with the given name."""
    if isinstance(annotation, type) and annotation.__name__ == class_name:
        return annotation
    args = get_args(annotation)
    for arg in args:
        result = _find_in_annotation(arg, class_name)
        if result is not None:
            return result
    return None


def introspect() -> AuthorableSchema:
    """Walk AuthoredBoard and all reachable authored models, returning an IR.

    The returned AuthorableSchema is the single source of truth consumed by
    render_json_schema, render_prompt, render_markdown, and render_erd.
    """
    collected: dict[str, AuthorableModel] = {}
    _collect_models(AuthoredBoard, collected)
    # Walk extra roots not reachable via AuthoredBoard type annotations.
    # Per-type authored query models are not reachable via AuthoredBoard annotations
    # (AuthoredQuery is a discriminated union alias, like AuthoredChart).
    # Source connector configs are reached via sources: dict[str, Any] — no type annotation.
    # Per-family chart patch classes are not reachable via AuthoredBoard annotations either
    # (AuthoredChart is a discriminated union alias, not a typed field on AuthoredBoard).
    from dbt_charts.core.compile.models.chart.authored import (  # noqa: PLC0415
        AreaChart,
        BarChart,
        CalloutChart,
        GeoshapeChart,
        HeatmapChart,
        KpiChart,
        LineChart,
        PieChart,
        PointMapChart,
        ScatterChart,
        SparkBarChart,
        TableChart,
    )
    from dbt_charts.core.compile.models.refs import (  # noqa: PLC0415
        ChartRef,
        QueryRef,
        VariableRef,
    )
    from dbt_charts.core.compile.models.style.theme import Style  # noqa: PLC0415

    for extra in (
        VariableRef,
        QueryRef,
        ChartRef,
        BarChart,
        LineChart,
        AreaChart,
        ScatterChart,
        HeatmapChart,
        PieChart,
        KpiChart,
        TableChart,
        PointMapChart,
        GeoshapeChart,
        CalloutChart,
        SparkBarChart,
        AuthoredSqlQuery,
        AuthoredMetricflowQuery,
        AuthoredHttpQuery,
        AuthoredValuesQuery,
        AuthoredCompactValuesQuery,
        AuthoredSchemaQuery,
        PaginationConfig,
        PostgresSourceConfig,
        SnowflakeSourceConfig,
        BigQuerySourceConfig,
        RedshiftSourceConfig,
        MySQLSourceConfig,
        DuckDBSourceConfig,
        SQLiteSourceConfig,
        CsvSourceConfig,
        ParquetSourceConfig,
        JsonSourceConfig,
        HttpSourceConfig,
        DbtProfileSourceConfig,
        # Compiled style root — walks style/theme/ types so inherit-chain metadata
        # (Inherit/InheritSlot markers) is visible in the schema IR.
        Style,
    ):
        _collect_models(extra, collected)
    # Build a synthetic "AuthoredChart" IR entry as a proper discriminated union.
    # fields=[] because the variant family classes (BarChart, LineChart, etc.) are
    # the authorable surface; this entry is a dispatch node only.
    collected["AuthoredChart"] = AuthorableModel(
        name="AuthoredChart",
        doc=(
            "Discriminated union of per-family chart patches. "
            "type: is mandatory; missing or unknown type raises ValidationError."
        ),
        fields=[],
        union=UnionSpec(
            discriminator="type",
            variants=dict(AUTHORED_CHART_VARIANTS),
        ),
    )
    # Query tags are optional in YAML because normalize_query_value infers them
    # from variant-only keys. Keep the synthetic editor/schema node as a union of
    # the concrete shapes instead of flattening their fields; flattening turns a
    # requirement from one variant (such as HTTP url) into a global requirement.
    query_variants = (
        "AuthoredSqlQuery",
        "AuthoredMetricflowQuery",
        "AuthoredHttpQuery",
        "AuthoredValuesQuery",
        "AuthoredCompactValuesQuery",
        "AuthoredSchemaQuery",
    )
    if all(name in collected for name in query_variants):
        collected["AuthoredQuery"] = AuthorableModel(
            name="AuthoredQuery",
            doc=(
                "Union of per-type authored query shapes. "
                "type: is inferred from key presence when omitted (bare SQL string, "
                "sql: -> sql; metrics: -> metricflow; "
                "url: -> http; rows:/values: -> values)."
            ),
            fields=[],
            union=UnionSpec(
                discriminator=None,
                variants={name: name for name in query_variants},
            ),
        )
    return AuthorableSchema(root="AuthoredBoard", models=collected)
