"""VS Code JSON Schema renderer — decorates the strict dbt charts YAML schema.

Calls render_yaml_schema(ir) for the IR-driven core, then adds the IDE-specific
extras that have no Pydantic counterpart (fileMatch, layout anyOf constraint,
LayoutItem definition). The theme enum is part of the base schema itself
(render_yaml_schema injects it), not an IDE-only extra.

Entry point: render_vscode_schema(schema) -> dict
"""

from __future__ import annotations

from typing import Any

from dbt_charts.core.compile.schema.introspection import AuthorableSchema
from dbt_charts.core.compile.schema.renderers.json_schema import render_yaml_schema


def _rename_defs(obj: Any) -> Any:
    """Deep-walk obj, renaming $defs → definitions and updating $ref strings."""
    if isinstance(obj, dict):
        return {
            ("definitions" if k == "$defs" else k): _rename_defs(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_rename_defs(item) for item in obj]
    if isinstance(obj, str) and obj.startswith("#/$defs/"):
        return "#/definitions/" + obj[len("#/$defs/") :]
    return obj


def _extract_description(prop: dict[str, Any]) -> str:
    if "description" in prop:
        return prop["description"]
    for branch in prop.get("anyOf", []):
        if "description" in branch:
            return branch["description"]
    return ""


def _build_layout_item_def() -> dict[str, Any]:
    return {
        "oneOf": [
            {"type": "string", "description": "Chart name reference."},
            {"$ref": "#/definitions/AuthoredChart"},
            {
                "type": "object",
                "description": "Nested layout.",
                "properties": {
                    "rows": {
                        "type": "array",
                        "items": {"$ref": "#/definitions/LayoutItem"},
                        "description": "Nested vertical layout items.",
                    },
                    "cols": {
                        "type": "array",
                        "items": {"$ref": "#/definitions/LayoutItem"},
                        "description": "Nested horizontal layout items.",
                    },
                    "grid": {
                        "allOf": [{"$ref": "#/definitions/GridLayout"}],
                        "description": "Nested grid layout.",
                    },
                    "tabs": {
                        "allOf": [{"$ref": "#/definitions/TabLayout"}],
                        "description": "Nested tab layout.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Section title.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Section description.",
                    },
                    "details": {
                        "anyOf": [
                            {
                                "type": "string",
                                "description": "String shorthand: sets the summary label.",
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "summary": {
                                        "type": "string",
                                        "description": "Label shown when collapsed.",
                                    },
                                    "expanded_title": {
                                        "type": "string",
                                        "description": "Label shown when expanded.",
                                    },
                                    "expanded": {
                                        "type": "boolean",
                                        "default": False,
                                        "description": "Default open state.",
                                    },
                                },
                                "required": ["summary"],
                                "additionalProperties": False,
                            },
                        ],
                        "description": "Collapsible section. String shorthand → BoardDetails(summary=str).",
                    },
                    "style": {
                        "type": "object",
                        "description": "CSS-like style overrides for this section.",
                    },
                },
            },
        ]
    }


def _decorate_for_vscode(base: dict[str, Any]) -> dict[str, Any]:
    # tach-ignore(pre-existing compile->project coupling — accepted debt)
    from dbt_charts.core.project import PROJECT_CONFIG_NAME

    schema = _rename_defs(base)
    props = schema.setdefault("properties", {})
    defns = schema.setdefault("definitions", {})

    # IDE metadata
    schema["title"] = "dbt charts Board"
    schema["fileMatch"] = [
        "*.dataface.yml",
        "*.dataface.yaml",
        PROJECT_CONFIG_NAME,
        "dbt_charts.yaml",
        "charts/*.yml",
        "charts/*.yaml",
        "charts/**/*.yml",
        "charts/**/*.yaml",
        "*.board.yml",
    ]
    schema["anyOf"] = [
        {"required": ["rows"]},
        {"required": ["cols"]},
        {"required": ["grid"]},
        {"required": ["tabs"]},
        {"required": ["charts"]},
        {"required": ["content"]},
    ]

    # Override charts → typed additionalProperties (IR has untyped dict[str, Any])
    _chart_ref_schema = {
        "type": "string",
        "pattern": r"^.+\.charts\.\w+$",
        "description": "Cross-file chart reference: '<file>.charts.<name>'.",
    }
    props["charts"] = {
        "type": "object",
        "description": _extract_description(props.get("charts", {})),
        "additionalProperties": {
            "oneOf": [
                {"$ref": "#/definitions/AuthoredChart"},
                _chart_ref_schema,
            ]
        },
    }

    # Override variables/queries → typed additionalProperties with cross-file ref support.
    # IR emits only the inline model (Variable/AuthoredQuery); the ref form is a string
    # matching '<file>.<section>.<name>' and is coerced to a typed model at parse time.
    for key, ref_name, section_label, pattern in (
        ("variables", "Variable", "variable", r"^.+\.variables\.\w+$"),
        ("queries", "AuthoredQuery", "query", r"^.+\.queries\.\w+$"),
    ):
        if key in props:
            string_arms: list[dict[str, object]] = [
                {
                    "type": "string",
                    "pattern": pattern,
                    "description": f"Cross-file {section_label} reference.",
                },
            ]
            # queries also accept bare SQL shorthand ("SELECT …") — add an unconstrained
            # string arm so IDE validation does not red-squiggle valid SQL strings.
            # Runtime (Pydantic) already enforces the grammar; the schema arm is advisory only.
            if key == "queries":
                string_arms.append({"type": "string"})
            props[key] = {
                "type": "object",
                "description": _extract_description(props[key]),
                "additionalProperties": {
                    "oneOf": [
                        {"$ref": f"#/definitions/{ref_name}"},
                        *string_arms,
                    ]
                },
            }

    # Override rows/cols → typed items (IR has untyped list[str | dict])
    for key in ("rows", "cols"):
        if key in props:
            props[key] = {
                "type": "array",
                "description": _extract_description(props[key]),
                "items": {"$ref": "#/definitions/LayoutItem"},
            }

    # Widen CachePatch to its scalar authoring forms (`cache: 1h`, `cache: false`).
    # Every scope $refs this one definition, so decorating it here covers them all.
    # The IR emits only the block shape — the scalars are expanded by CachePatch's
    # before-validator, which JSON Schema generation cannot see.
    if "CachePatch" in defns:
        # Closed: `enabled` is not authorable, so the IDE offers only the
        # scalars and the keys the reference actually teaches. This is the
        # board-scope shape; the project root's extra `path` key lives in
        # `dbt_charts.yml`, which this board schema does not match.
        block_arm = {**defns["CachePatch"], "additionalProperties": False}
        # `ttl` is Optional in Python because unset means "inherit", but the
        # validator rejects a written `ttl: null` as ambiguous — so the null
        # arm the generic renderer emits for every Optional field would have
        # the IDE green-light the one spelling the compiler goes out of its
        # way to refuse.
        ttl = block_arm["properties"]["ttl"]
        block_arm["properties"] = {
            **block_arm["properties"],
            "ttl": {
                **ttl,
                # The `forever` arm is a bare enum and carries no `type`.
                "anyOf": [arm for arm in ttl["anyOf"] if arm.get("type") != "null"],
            },
        }
        defns["CachePatch"] = {
            "oneOf": [
                block_arm,
                {
                    "type": "boolean",
                    "description": "false disables caching at this scope; true "
                    "enables it with the inherited ttl.",
                },
                {
                    "type": "string",
                    "description": "Cache ttl: a duration ('5m', '1h', '7d', "
                    "'1h30m') or 'forever' to never auto-expire.",
                },
            ]
        }

    defns["LayoutItem"] = _build_layout_item_def()

    return schema


def render_vscode_schema(schema: AuthorableSchema) -> dict[str, Any]:
    """Render an AuthorableSchema as a VS Code draft-07 JSON Schema.

    Calls render_yaml_schema for the IR-driven core and decorates with
    IDE-specific extras (fileMatch, layout constraints, etc.).
    """
    base = render_yaml_schema(schema)
    return _decorate_for_vscode(base)
