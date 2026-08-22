"""JSON Schema renderer — Layer 2 of the two-layer schema IR.

Converts an AuthorableSchema IR to a draft-07 JSON Schema dict.
Callers: IDE schema generation, validation tooling.

Entry point: render_yaml_schema(schema: AuthorableSchema) -> dict
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from typing import Any, get_args

from pydantic_core import PydanticUndefined

from dbt_charts.core.compile.models.schema_names import ThemeName
from dbt_charts.core.compile.schema.introspection import (
    AuthorableSchema,
    SchemaField,
    schema_path_to_yaml,
)

_PRIMITIVES: dict[str, dict[str, Any]] = {
    "str": {"type": "string"},
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "bool": {"type": "boolean"},
    "None": {"type": "null"},
}


def _schema_for_token(token: str) -> dict[str, Any]:
    """Map a single non-union type token to a JSON Schema dict."""
    if token in _PRIMITIVES:
        return _PRIMITIVES[token]
    if token.startswith("list["):
        return {"type": "array"}
    if token.startswith("dict["):
        return {"type": "object"}
    return {}


def _split_union(s: str) -> list[str]:
    """Split s on ' | ' separators at bracket depth 0 (not inside [...])."""
    parts: list[str] = []
    depth = 0
    start = 0
    i = 0
    while i < len(s):
        if s[i] == "[":
            depth += 1
        elif s[i] == "]":
            depth -= 1
        elif depth == 0 and s[i : i + 3] == " | ":
            parts.append(s[start:i])
            start = i + 3
            i += 3
            continue
        i += 1
    parts.append(s[start:])
    return parts


def _ref(model_name: str, root: str) -> dict[str, str]:
    """Build a $ref to a model's $defs entry, or to the document root.

    render_yaml_schema inlines the root model's properties at the top level and
    never emits a $defs entry for it. A field that recurses back to the root
    (a nested board) must therefore $ref the document root ("#") rather than a
    "#/$defs/<root>" entry that will never exist.
    """
    if model_name == root:
        return {"$ref": "#"}
    return {"$ref": f"#/$defs/{model_name}"}


def sibling_container_tokens(type_repr: str) -> list[str]:
    """list[...]/dict[...] arm tokens sitting beside an enum or model arm in
    the same union (e.g. `ThemeName | str | list[str]`).

    Shared by this module's _type_schema (enum branch) and prompt.py's
    _type_cell — both need to recover a container sibling arm that
    field.extra_union_types drops (it recurses into a container's item/value
    type instead of reporting the container's own shape, by design for the
    field.container-wrapping case). One canonical extractor per
    `core/AGENTS.md`'s "one canonical mapper per concept" rule; not
    underscore-prefixed since prompt.py imports it across module boundaries.
    """
    base = type_repr.replace(" | None", "").strip()
    return [
        token.strip()
        for token in _split_union(base)
        if token.strip().startswith(("list[", "dict["))
    ]


def _type_schema(field: SchemaField, root: str) -> dict[str, Any]:
    """Build the JSON Schema type object for a single field."""
    nullable = "None" in field.type_repr

    extra = [_PRIMITIVES[t] for t in field.extra_union_types if t in _PRIMITIVES]

    if field.tuple_item_reprs is not None:
        # A fixed-length tuple: one type_repr string per position, mapped
        # through the same _map_type_repr each bare list[X]/dict[K,V] field
        # already uses -- prefixItems is the one shape neither field.container
        # nor field.enum_values models (both assume every position shares one
        # type; a tuple's positions don't).
        tuple_schema = {
            "type": "array",
            "prefixItems": [_map_type_repr(r) for r in field.tuple_item_reprs],
            "minItems": len(field.tuple_item_reprs),
            "maxItems": len(field.tuple_item_reprs),
        }
        return {"anyOf": [tuple_schema, {"type": "null"}]} if nullable else tuple_schema

    if field.enum_values is not None:
        enum_item = {"enum": field.enum_values}
        branches: list[dict[str, Any]]
        if field.nested_models:
            # Field accepts both model objects and scalar enum values (e.g. SparkConfig | SparkTypeLiteral).
            model_refs = [_ref(n, root) for n in field.nested_models]
            branches = model_refs + [enum_item] + extra
        else:
            branches = [enum_item] + extra
        # field.container is set only when the whole field is a single
        # list[...]/dict[...] (e.g. dict[str, PaletteName | str]) — wrap the
        # enum+extra branches as that container's items/additionalProperties,
        # mirroring the field.nested_models branch below.
        if field.container in ("list", "dict"):
            enum_inner = branches[0] if len(branches) == 1 else {"anyOf": branches}
            wrapped = (
                {"type": "array", "items": enum_inner}
                if field.container == "list"
                else {"type": "object", "additionalProperties": enum_inner}
            )
            return {"anyOf": [wrapped, {"type": "null"}]} if nullable else wrapped
        # Otherwise a list[...]/dict[...] may still sit as a *sibling* union
        # arm (e.g. `ThemeName | str | list[str]`) — add its bare shape so it
        # isn't dropped from the anyOf. Multiple sibling tokens can map to the
        # same schema (list[str] | list[float] both → {"type": "array"}), so
        # dedup on the mapped shape, not the token.
        for token in sibling_container_tokens(field.type_repr):
            arm = _schema_for_token(token)
            if arm and arm not in branches:
                branches.append(arm)
        if nullable:
            branches.append({"type": "null"})
        return {"anyOf": branches} if len(branches) > 1 else branches[0]

    if field.nested_models:
        refs: list[dict[str, Any]] = [_ref(n, root) for n in field.nested_models]
        branches = refs + extra
        inner: dict[str, Any] = (
            branches[0] if len(branches) == 1 else {"anyOf": branches}
        )
        if field.container == "list":
            if field.container_mapping_models:
                map_refs = [_ref(n, root) for n in field.container_mapping_models]
                if len(map_refs) == 1:
                    item_branches = [
                        inner,
                        {"type": "object", "additionalProperties": map_refs[0]},
                    ]
                else:
                    item_branches = [
                        inner,
                        {
                            "type": "object",
                            "additionalProperties": {"anyOf": map_refs},
                        },
                    ]
                inner = {"anyOf": item_branches}
            arr: dict[str, Any] = {"type": "array", "items": inner}
            parts: list[dict[str, Any]] = [arr]
            if nullable:
                parts.append({"type": "null"})
            return {"anyOf": parts} if len(parts) > 1 else parts[0]
        if field.container == "dict":
            obj: dict[str, Any] = {"type": "object", "additionalProperties": inner}
            parts = [obj]
            if nullable:
                parts.append({"type": "null"})
            return {"anyOf": parts} if len(parts) > 1 else parts[0]
        all_branches: list[dict[str, Any]] = branches
        if nullable:
            all_branches.append({"type": "null"})
        return {"anyOf": all_branches} if len(all_branches) > 1 else all_branches[0]

    return _map_type_repr(field.type_repr)


def _map_type_repr(type_repr: str) -> dict[str, Any]:
    """Map a type_repr string to a JSON Schema type dict."""
    nullable = " | None" in type_repr
    base = type_repr.replace(" | None", "").strip()

    if base in _PRIMITIVES:
        schema = _PRIMITIVES[base]
    elif " | " in base:
        # Bracket-aware split so 'list[X | Y]' stays intact; dedup identical schemas
        # (e.g. list[str] | list[float] both map to {"type": "array"}).
        token_schemas = []
        for token in _split_union(base):
            s = _schema_for_token(token.strip())
            if s and s not in token_schemas:
                token_schemas.append(s)
        schema = {"anyOf": token_schemas} if token_schemas else {}
    elif base.startswith("list["):
        schema = {"type": "array"}
    elif base.startswith("dict["):
        schema = {"type": "object"}
    else:
        schema = {}

    if not nullable or not schema:
        return schema
    if "anyOf" in schema:
        schema = dict(schema)
        schema["anyOf"] = list(schema["anyOf"]) + [{"type": "null"}]
        return schema
    return {"anyOf": [schema, {"type": "null"}]}


def _inherit_note(field: SchemaField) -> str:
    """Return the fallback sentence for a field that carries an inheritance marker."""
    if field.inherit_slot:
        exception = ""
        if field.inherit_slot_exclude:
            names = ", ".join(f"`{n}`" for n in sorted(field.inherit_slot_exclude))
            exception = f" (except {names})"
        return f"Unset fields fall back to `{schema_path_to_yaml(field.inherit_slot)}`{exception}."
    if field.inherit_from:
        return f"Falls back to `{schema_path_to_yaml(field.inherit_from[0])}`."
    return ""


def _union_to_def(model_name: str, ir: AuthorableSchema) -> dict[str, Any]:
    """Build a JSON Schema $defs entry for a union IR model.

    Discriminated unions emit an if/then allOf structure. Structural unions
    emit anyOf refs so each branch retains its own required and forbidden keys.
    """
    model = ir.models[model_name]
    assert model.union is not None  # caller guarantee
    spec = model.union

    if spec.discriminator is None:
        variants = list(dict.fromkeys(spec.variants.values()))
        defn: dict[str, Any] = {
            "anyOf": [_ref(class_name, ir.root) for class_name in variants]
        }
        if model.doc:
            defn["description"] = model.doc
        return defn

    class_to_tags: dict[str, list[str]] = defaultdict(list)
    for tag, class_name in spec.variants.items():
        class_to_tags[class_name].append(tag)

    all_tags = sorted(spec.variants.keys())
    all_of = []
    for class_name, tags in class_to_tags.items():
        all_of.append(
            {
                "if": {
                    "properties": {spec.discriminator: {"enum": sorted(tags)}},
                    "required": [spec.discriminator],
                },
                "then": _ref(class_name, ir.root),
            }
        )

    defn = {
        "type": "object",
        "properties": {
            spec.discriminator: {
                "enum": all_tags,
                "description": f"Chart family selector. One of: {', '.join(all_tags)}.",
            }
        },
        "required": [spec.discriminator],
        "allOf": all_of,
    }
    if model.doc:
        defn["description"] = model.doc
    return defn


def _model_to_def(model_name: str, ir: AuthorableSchema) -> dict[str, Any]:
    """Build a JSON Schema $defs entry for one AuthorableModel."""
    model = ir.models[model_name]
    if model.union is not None:
        return _union_to_def(model_name, ir)

    required = [f.name for f in model.fields if f.required and not f.is_extra_key]
    properties: dict[str, Any] = {}
    additional_properties: dict[str, Any] | None = None
    for field in model.fields:
        prop: dict[str, Any] = _type_schema(field, ir.root)
        note = _inherit_note(field)
        desc = " ".join(filter(None, [field.description, note]))
        if desc:
            prop = dict(prop)
            prop["description"] = desc
        if (
            not field.required
            and field.default is not dataclasses.MISSING
            and field.default is not None
            and field.default is not PydanticUndefined
        ):
            prop = dict(prop)
            prop["default"] = field.default
        if field.is_extra_key:
            additional_properties = prop
        else:
            properties[field.name] = prop

    defn: dict[str, Any] = {"type": "object", "properties": properties}
    if model.doc:
        defn["description"] = model.doc
    if required:
        defn["required"] = required
    if additional_properties is not None:
        defn["additionalProperties"] = additional_properties
    else:
        defn["additionalProperties"] = False
    return defn


def _theme_property_schema() -> dict[str, str | list[str]]:
    """Schema for the ``theme:`` authoring-sugar key.

    ``theme:`` has no backing Pydantic field — ``_desugar_theme`` rewrites it
    into ``extends:`` before validation runs, so introspection never sees it
    as a model field and this property must be hand-assembled here rather
    than derived from a field annotation. It reads the same generated
    ``ThemeName`` list the ``extends`` field's enum arm reads, so the two can
    never drift apart.
    """
    return {
        "type": "string",
        "enum": sorted(get_args(ThemeName)),
        "description": "Built-in theme name — shorthand for `extends: <name>`.",
    }


def render_yaml_schema(schema: AuthorableSchema) -> dict[str, Any]:
    """Render the strict draft-07 Dataface YAML schema.

    Produces a self-contained schema with the root model's properties
    inlined and all reachable authored models in $defs. Author-defined model
    objects are closed; only declared keyed collections use typed additional
    properties.
    """
    root = _model_to_def(schema.root, schema)
    defs = {
        name: _model_to_def(name, schema)
        for name in schema.models
        if name != schema.root
    }

    # Widen ChartDataTable to accept the bare-list shorthand handled by its
    # _accept_bare_list model_validator (list[entry] -> {entries: list[entry]}).
    # Covers every data_table field in Bar/Line/Area/etc. charts.
    if "ChartDataTable" in defs:
        entry_ref: dict[str, Any] = {
            "anyOf": [
                {"$ref": "#/$defs/ChartDataTableSource"},
                {"$ref": "#/$defs/ChartDataTableAggregate"},
                {"$ref": "#/$defs/ChartDataTablePerSeries"},
            ]
        }
        defs["ChartDataTable"] = {
            "anyOf": [
                defs["ChartDataTable"],
                {"type": "array", "items": entry_ref, "minItems": 1},
            ]
        }

    result: dict[str, Any] = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": schema.root,
    }
    if root.get("description"):
        result["description"] = root["description"]
    result["type"] = "object"
    result["properties"] = {
        **root.get("properties", {}),
        "theme": _theme_property_schema(),
    }
    result["additionalProperties"] = root["additionalProperties"]
    if root.get("required"):
        result["required"] = root["required"]
    if defs:
        result["$defs"] = defs

    return result


render_json_schema = render_yaml_schema
