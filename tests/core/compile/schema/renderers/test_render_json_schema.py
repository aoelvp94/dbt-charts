"""TDD tests for render_json_schema: AuthorableSchema IR → draft-07 JSON Schema."""

import json

from dbt_charts.core.compile.schema.introspection import introspect
from dbt_charts.core.compile.schema.renderers.json_schema import render_json_schema


class TestRenderJsonSchemaStructure:
    def test_returns_dict(self) -> None:
        assert isinstance(render_json_schema(introspect()), dict)

    def test_is_json_serializable(self) -> None:
        json.dumps(render_json_schema(introspect()))

    def test_has_schema_version(self) -> None:
        result = render_json_schema(introspect())
        assert result.get("$schema") == "http://json-schema.org/draft-07/schema#"

    def test_has_properties(self) -> None:
        assert "properties" in render_json_schema(introspect())

    def test_root_properties_present(self) -> None:
        props = render_json_schema(introspect())["properties"]
        for key in ("title", "charts", "queries", "variables"):
            assert key in props, f"Missing root property: {key}"


class TestRenderJsonSchemaDescriptions:
    def test_root_properties_have_descriptions(self) -> None:
        props = render_json_schema(introspect())["properties"]
        for key in ("title", "charts", "queries"):
            assert props[key].get("description"), f"No description on {key}"

    def test_nested_model_properties_have_descriptions(self) -> None:
        defs = render_json_schema(introspect()).get("$defs", {})
        variable = defs.get("Variable", {})
        props = variable.get("properties", {})
        assert props.get("input", {}).get("description")


class TestRenderJsonSchemaRefs:
    def test_defs_contains_authored_models(self) -> None:
        defs = render_json_schema(introspect()).get("$defs", {})
        for name in ("GridLayout", "Variable", "AuthoredQuery", "AuthoredChart"):
            assert name in defs, f"{name} missing from $defs"

    def test_enum_values_in_chart_patch_type(self) -> None:
        defs = render_json_schema(introspect()).get("$defs", {})
        chart_patch = defs.get("AuthoredChart", {})
        type_prop = chart_patch.get("properties", {}).get("type", {})
        schema_str = json.dumps(type_prop)
        assert "bar" in schema_str and "line" in schema_str

    def test_required_fields_listed(self) -> None:
        defs = render_json_schema(introspect()).get("$defs", {})
        grid_layout = defs.get("GridLayout", {})
        # GridLayout.items is required
        assert "items" in grid_layout.get("required", [])


class TestRenderJsonSchemaUnionTypes:
    def test_multi_type_union_field_has_multiple_branches(self) -> None:
        # BarChart.y: str | list[str] | None — must not drop the list branch
        # (AuthoredChart is now a discriminated union; fields live on the family classes)
        defs = render_json_schema(introspect()).get("$defs", {})
        y_prop = defs["BarChart"]["properties"]["y"]
        schema_str = json.dumps(y_prop)
        assert "array" in schema_str, "list[str] branch must appear as array type"
        assert "string" in schema_str

    def test_chart_query_includes_authored_query_ref(self) -> None:
        # BarChart.query: str | AuthoredQuery | QueryRef | None
        # Must reference AuthoredQuery (the typed inline query model).
        # (AuthoredChart is now a discriminated union; fields live on the family classes)
        defs = render_json_schema(introspect()).get("$defs", {})
        query_prop = defs["BarChart"]["properties"]["query"]
        schema_str = json.dumps(query_prop)
        assert "AuthoredQuery" in schema_str, (
            "query schema must reference AuthoredQuery"
        )

    def test_dict_keyed_model_field_emits_object_with_additional_properties(
        self,
    ) -> None:
        # AuthoredBoard.variables: dict[str, Variable | str] | None
        # Must render as {type: object, additionalProperties: ...}, not bare $ref
        props = render_json_schema(introspect())["properties"]
        variables_prop = props["variables"]
        schema_str = json.dumps(variables_prop)
        assert (
            '"type": "object"' in schema_str or "additionalProperties" in schema_str
        ), "dict[str, Model] field must emit object schema, not bare $ref"

    def test_list_of_model_emits_array_with_items_ref(self) -> None:
        # GridLayout.items: list[GridItem] — must not render as bare $ref
        defs = render_json_schema(introspect()).get("$defs", {})
        items_prop = defs["GridLayout"]["properties"]["items"]
        assert items_prop.get("type") == "array", "list[Model] must emit array type"
        assert items_prop.get("items", {}).get("$ref", "").endswith("/GridItem"), (
            "list[Model] items must be a $ref to the model"
        )

    def test_str_or_model_union_includes_both_branches(self) -> None:
        # KpiSupportConfig.format: str | FormatConfig | None
        # Must include both string branch and $ref branch — not just the model ref.
        defs = render_json_schema(introspect()).get("$defs", {})
        format_prop = defs["KpiSupportConfig"]["properties"]["format"]
        schema_str = json.dumps(format_prop)
        assert "string" in schema_str, "str branch must appear for str | Model union"
        assert "FormatConfig" in schema_str, "model $ref branch must appear"

    def test_stack_is_enum_only_no_bool(self) -> None:
        # BarChartStylePatch.stack: Literal["none","zero","normalize","center"] | None
        # Bool was removed — only string enum values are valid.
        defs = render_json_schema(introspect()).get("$defs", {})
        stack_prop = defs["BarChartStylePatch"]["properties"]["stack"]
        schema_str = json.dumps(stack_prop)
        assert "boolean" not in schema_str, "bool must not appear — use 'none'/'zero'"
        assert "zero" in schema_str, "enum values must appear"
        assert "none" in schema_str, "'none' sentinel must appear"

    def test_variable_dependencies_not_in_schema(self) -> None:
        # Variable.variable_dependencies is a compile-time field (exclude=True)
        # and must not appear in the IDE schema that authors write against.
        defs = render_json_schema(introspect()).get("$defs", {})
        variable_props = defs.get("Variable", {}).get("properties", {})
        assert "variable_dependencies" not in variable_props, (
            "variable_dependencies is a compile-time field and must not be exposed to authors"
        )


class TestRenderJsonSchemaInheritance:
    def test_inherit_from_appended_to_description(self) -> None:
        # BarChartStylePatch.aspect_ratio carries Inherit(from_path="Style.charts.aspect_ratio").
        # The JSON Schema description must include the fallback path so IDE tooltips
        # communicate inheritance to dashboard authors.
        defs = render_json_schema(introspect()).get("$defs", {})
        prop = defs["BarChartStylePatch"]["properties"]["aspect_ratio"]
        desc = prop.get("description", "")
        assert "Falls back to" in desc, "inherit_from must produce fallback description"
        assert "style.charts.aspect_ratio" in desc

    def test_inherit_slot_appended_to_description(self) -> None:
        # BarChartStylePatch.marks carries InheritSlot(from_path="Style.charts.marks").
        defs = render_json_schema(introspect()).get("$defs", {})
        prop = defs["BarChartStylePatch"]["properties"]["marks"]
        desc = prop.get("description", "")
        assert "Unset fields fall back to" in desc
        assert "style.charts.marks" in desc

    def test_inherit_slot_exclude_appended_to_description(self) -> None:
        # SliceLabelsStyle.font carries InheritSlot(exclude={"color"}) — the
        # generated description must say so, not claim color falls back too.
        defs = render_json_schema(introspect()).get("$defs", {})
        prop = defs["SliceLabelsStyle"]["properties"]["font"]
        desc = prop.get("description", "")
        assert "Unset fields fall back to" in desc
        assert "except `color`" in desc

    def test_plain_field_unaffected(self) -> None:
        # A field with no inheritance must not gain spurious fallback text.
        defs = render_json_schema(introspect()).get("$defs", {})
        prop = defs["AuthoredChart"]["properties"]["type"]
        desc = prop.get("description", "")
        assert "Falls back to" not in desc
        assert "Unset fields fall back to" not in desc


class TestThemeProperty:
    """theme: has no backing Pydantic field (_desugar_theme consumes it before
    validation), so render_yaml_schema hand-injects it — this must reach the
    engine-shipped schema too, not just the VS Code decorator, and must never
    drift from extends's own ThemeName enum arm."""

    def test_theme_property_present_with_non_empty_description(self) -> None:
        schema = render_json_schema(introspect())
        theme_prop = schema["properties"]["theme"]
        assert theme_prop["type"] == "string"
        assert theme_prop["enum"]
        assert theme_prop["description"]

    def test_theme_and_extends_share_the_same_enum_list(self) -> None:
        schema = render_json_schema(introspect())
        theme_enum = set(schema["properties"]["theme"]["enum"])
        extends_prop = schema["properties"]["extends"]
        extends_enum = next(
            set(branch["enum"]) for branch in extends_prop["anyOf"] if "enum" in branch
        )
        assert theme_enum == extends_enum

    def test_theme_enum_matches_generated_theme_name(self) -> None:
        import typing

        from dbt_charts.core.compile.models.schema_names import ThemeName

        schema = render_json_schema(introspect())
        assert set(schema["properties"]["theme"]["enum"]) == set(
            typing.get_args(ThemeName)
        )


class TestRenderJsonSchemaOverlapStruct:
    """overlap is a struct (tilt/skip bools) — must render as $ref to an object, not an enum or array."""

    def test_overlap_is_object_not_array(self) -> None:
        # AxisLabelStylePatch.overlap is AxisLabelOverlapConfigPatch | None.
        # Must emit a $ref to the patch model (an object with tilt/skip bool fields).
        defs = render_json_schema(introspect()).get("$defs", {})
        prop = defs["AxisLabelStylePatch"]["properties"]["overlap"]
        schema_str = json.dumps(prop)
        # Struct shape: object reference, not array
        assert '"type": "array"' not in schema_str, (
            "overlap must be an object, not an array: " + schema_str
        )
        # Struct properties must be in the schema defs
        assert (
            "AxisLabelOverlapConfig" in schema_str
            or "AxisLabelOverlapConfigPatch" in schema_str
        ), "overlap must reference the AxisLabelOverlapConfig struct: " + schema_str
