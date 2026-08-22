"""Tests for the AuthorableSchema IR produced by introspect().

TDD: these tests were written before introspection.py existed.
Run them to watch them fail, then implement to make them pass.
"""

from dbt_charts.core.compile.schema.introspection import (
    introspect,
)


class TestIntrospectReturnsSchema:
    def test_root_is_authored_board(self) -> None:
        schema = introspect()
        assert schema.root == "AuthoredBoard"

    def test_root_model_in_models(self) -> None:
        schema = introspect()
        assert "AuthoredBoard" in schema.models


class TestAuthordBoardFields:
    def test_title_field_present_with_description(self) -> None:
        schema = introspect()
        board = schema.models["AuthoredBoard"]
        title = next((f for f in board.fields if f.name == "title"), None)
        assert title is not None
        assert title.description

    def test_charts_field_present_with_description(self) -> None:
        schema = introspect()
        board = schema.models["AuthoredBoard"]
        charts = next((f for f in board.fields if f.name == "charts"), None)
        assert charts is not None
        assert charts.description

    def test_queries_field_present_with_description(self) -> None:
        schema = introspect()
        board = schema.models["AuthoredBoard"]
        queries = next((f for f in board.fields if f.name == "queries"), None)
        assert queries is not None
        assert queries.description

    def test_optional_fields_not_required(self) -> None:
        schema = introspect()
        board = schema.models["AuthoredBoard"]
        title = next(f for f in board.fields if f.name == "title")
        assert not title.required


class TestNestedModelsCollected:
    def test_grid_layout_collected(self) -> None:
        schema = introspect()
        assert "GridLayout" in schema.models

    def test_variable_collected(self) -> None:
        schema = introspect()
        assert "Variable" in schema.models

    def test_authored_query_collected(self) -> None:
        schema = introspect()
        assert "AuthoredQuery" in schema.models

    def test_authored_query_fields_have_descriptions(self) -> None:
        schema = introspect()
        query = schema.models["AuthoredQuery"]
        missing = [f.name for f in query.fields if not f.description]
        assert not missing, f"AuthoredQuery fields without description: {missing}"


class TestEnumCapture:
    def test_authored_chart_is_discriminated_union_in_ir(self) -> None:
        # AuthoredChart is now a synthetic union node; chart type tags live
        # in its UnionSpec.variants, not as a field with enum_values.
        schema = introspect()
        chart_model = schema.models.get("AuthoredChart")
        assert chart_model is not None
        assert chart_model.union is not None, "AuthoredChart must have a union spec"
        assert chart_model.fields == [], "union node has no direct fields"
        assert "bar" in chart_model.union.variants
        assert "line" in chart_model.union.variants
        assert "kpi" in chart_model.union.variants

    def test_variable_input_type_enum_captured(self) -> None:
        schema = introspect()
        variable = schema.models["Variable"]
        input_field = next((f for f in variable.fields if f.name == "input"), None)
        assert input_field is not None
        assert input_field.enum_values is not None
        assert "select" in input_field.enum_values
        assert "daterange" in input_field.enum_values


class TestPatchModelsCollected:
    """Regression: generated *StylePatch models must appear in the IR.

    Root cause: build_patch_model stamps __module__ = compiled_cls.__module__,
    so _is_authored_model() previously filtered them out. Fixed by accepting
    _PatchBase subclasses regardless of module.
    """

    _EXPECTED = frozenset(
        {
            "BarChartStylePatch",
            "LineChartStylePatch",
            "AreaChartStylePatch",
            "ScatterChartStylePatch",
            "SliceMarkStylePatch",
            "TotalStylePatch",
            "KpiChartStylePatch",
            "SparkStylePatch",
            "SparkBarChartStylePatch",
            "BaseAxisStylePatch",
            "AxisXStylePatch",
            "AxisYStylePatch",
            "QuantitativeAxisStylePatch",
            "BandAxisStylePatch",
            "BaseAxisGridStylePatch",
            "MeasureGridStylePatch",
            "AxisLineStylePatch",
            "AxisTicksStylePatch",
            "AxisLabelStylePatch",
            "LegendStylePatch",
            "TitleStylePatch",
            "TableChartStylePatch",
            "DataTableStylePatch",
            "GlobalMarksStylePatch",
            "PieChartStylePatch",
            "PointMarkStylePatch",
            "PaginationConfig",
        }
    )

    def test_all_expected_in_ir(self) -> None:
        schema = introspect()
        missing = self._EXPECTED - schema.models.keys()
        assert not missing, f"Missing from IR: {missing}"

    def test_patch_models_marked_generated(self) -> None:
        schema = introspect()
        for name in self._EXPECTED:
            if name == "PaginationConfig":
                continue
            model = schema.models.get(name)
            assert model is not None, f"{name} missing from IR"
            assert model.generated, f"{name} should be marked generated"

    def test_pagination_config_not_generated(self) -> None:
        schema = introspect()
        model = schema.models.get("PaginationConfig")
        assert model is not None
        assert not model.generated


class TestSourceConfigTypeRequired:
    """Source connector 'type' discriminator must be required, never optional."""

    _CONFIGS = [
        "PostgresSourceConfig",
        "SnowflakeSourceConfig",
        "BigQuerySourceConfig",
        "RedshiftSourceConfig",
        "MySQLSourceConfig",
        "DuckDBSourceConfig",
        "CsvSourceConfig",
        "ParquetSourceConfig",
        "JsonSourceConfig",
        "HttpSourceConfig",
        "DbtProfileSourceConfig",
    ]

    def test_type_field_is_required_in_ir(self) -> None:
        schema = introspect()
        failures = []
        for name in self._CONFIGS:
            model = schema.models.get(name)
            assert model is not None, f"{name} missing from IR"
            type_field = next((f for f in model.fields if f.name == "type"), None)
            if type_field is None or not type_field.required:
                failures.append(name)
        assert not failures, f"'type' is not required in IR for: {failures}"


class TestRefModelsCollected:
    """Cross-file ref models must appear in the IR.

    VariableRef/QueryRef/ChartRef live in models.refs (not an .authored module),
    so BFS from AuthoredBoard skips them. They are registered as explicit extra roots.
    """

    def test_variable_ref_collected(self) -> None:
        schema = introspect()
        assert "VariableRef" in schema.models

    def test_query_ref_collected(self) -> None:
        schema = introspect()
        assert "QueryRef" in schema.models

    def test_chart_ref_collected(self) -> None:
        schema = introspect()
        assert "ChartRef" in schema.models

    def test_ref_field_has_description(self) -> None:
        schema = introspect()
        for model_name in ("VariableRef", "QueryRef", "ChartRef"):
            model = schema.models[model_name]
            ref_field = next((f for f in model.fields if f.name == "ref"), None)
            assert ref_field is not None, f"{model_name} missing 'ref' field"
            assert ref_field.description, f"{model_name}.ref missing description"


class TestFieldAliasHonored:
    """Field aliases must be used as display names, not the Python attribute name."""

    def test_postgres_schema_field_uses_alias(self) -> None:
        schema = introspect()
        pg = schema.models.get("PostgresSourceConfig")
        assert pg is not None
        names = [f.name for f in pg.fields]
        assert "schema" in names, "alias 'schema' must appear in IR"
        assert "schema_" not in names, "Python attr 'schema_' must not leak into IR"


class TestSourceConnectorsCollected:
    _EXPECTED = frozenset(
        {
            "PostgresSourceConfig",
            "SnowflakeSourceConfig",
            "BigQuerySourceConfig",
            "RedshiftSourceConfig",
            "MySQLSourceConfig",
            "DuckDBSourceConfig",
            "CsvSourceConfig",
            "ParquetSourceConfig",
            "JsonSourceConfig",
            "HttpSourceConfig",
            "DbtProfileSourceConfig",
        }
    )

    def test_all_concrete_connectors_in_ir(self) -> None:
        schema = introspect()
        missing = self._EXPECTED - schema.models.keys()
        assert not missing, f"Missing from IR: {missing}"

    def test_private_and_abstract_classes_absent(self) -> None:
        schema = introspect()
        for name in ("_DbSourceShim", "BaseSourceConfig"):
            assert name not in schema.models, f"{name} should not be in IR"


class TestSchemaFieldTypes:
    def test_model_has_doc(self) -> None:
        schema = introspect()
        board = schema.models["AuthoredBoard"]
        assert board.doc  # docstring should be non-empty

    def test_every_collected_field_has_description(self) -> None:
        """All fields in every collected model must have descriptions.

        Source compiled models carry Field(description=...) and build_patch_model
        copies those descriptions to generated patch fields automatically.
        """
        schema = introspect()
        failures: list[str] = []
        for model_name, model in schema.models.items():
            for field in model.fields:
                if not field.description:
                    failures.append(f"{model_name}.{field.name}")
        assert not failures, f"Fields missing description in IR: {failures}"

    def test_no_mkdocs_admonitions_in_model_docs(self) -> None:
        """Model doc strings must not start with mkdocs admonition syntax."""
        schema = introspect()
        failures = [
            model_name
            for model_name, model in schema.models.items()
            if model.doc.startswith(("!!! ", "??? ", ":::"))
        ]
        assert not failures, f"Models with mkdocs admonitions in doc: {failures}"

    def test_annotated_tag_discriminator_unwrapped(self) -> None:
        ir = introspect()
        entries = next(
            f for f in ir.models["ChartDataTable"].fields if f.name == "entries"
        )
        assert "Tag(" not in entries.type_repr
        assert "Discriminator(" not in entries.type_repr
        for branch in (
            "ChartDataTableSource",
            "ChartDataTableAggregate",
            "ChartDataTablePerSeries",
        ):
            assert branch in entries.type_repr

    def test_annotated_strict_unwrapped(self) -> None:
        ir = introspect()
        is_null = next(
            f for f in ir.models["ConditionalRule"].fields if f.name == "is_null"
        )
        assert "strict=" not in is_null.type_repr
        assert is_null.type_repr == "bool | None"

    def test_annotated_primitive_beside_a_literal_survives_the_union(self) -> None:
        """`Literal[...] | Annotated[str, ...] | None` must keep its string arm.

        CachePatch.ttl is `Literal["forever"] | Duration | None`, where Duration
        is `Annotated[str, AfterValidator]`. Dropping the Annotated arm left the
        field looking like a closed one-value enum, which red-squiggled every
        real `ttl: 1h` in the IDE.
        """
        ir = introspect()
        ttl = next(f for f in ir.models["CachePatch"].fields if f.name == "ttl")
        assert ttl.enum_values == ["forever"]
        assert "str" in ttl.extra_union_types

    def test_synthesised_patch_models_have_doc(self) -> None:
        ir = introspect()
        for name, model in ir.models.items():
            if not model.generated:
                continue
            assert model.doc, f"{name} (generated patch) has empty doc"
            assert not model.doc.startswith("[Models]"), (
                f"{name} doc leaked from BaseModel.__doc__"
            )

    def test_border_style_patch_runtime_class_is_hand_written(self) -> None:
        """_PATCH_REGISTRY must prevent build_patch_model from synthesizing a duplicate.

        GlobalMarksStylePatch.bar.border: BorderStyle → build_patch_model(BorderStyle)
        must return the hand-written BorderStylePatch (with from_css), not a synthesized namesake.
        """
        import typing

        from dbt_charts.core.compile.models.primitives import BorderStylePatch
        from dbt_charts.core.compile.models.style.authored import GlobalMarksStylePatch

        # bar is now on GlobalMarksStylePatch; BarMarkStylePatch has the border field
        bar_field = GlobalMarksStylePatch.model_fields["bar"]
        bar_cls = next(
            a for a in typing.get_args(bar_field.annotation) if a is not type(None)
        )
        annotation = bar_cls.model_fields["border"].annotation
        # annotation is BorderStylePatch | None — extract the non-None arg
        border_cls = next(a for a in typing.get_args(annotation) if a is not type(None))
        assert border_cls is BorderStylePatch, (
            "registry fix must ensure BarMarkStylePatch.border uses hand-written "
            "BorderStylePatch (has from_css), not a synthesized duplicate"
        )
        assert hasattr(border_cls, "from_css")


class TestPromptRendererTypeCellMixedUnion:
    """_type_cell must include extra_union_types alongside enum values.

    Regression for bool | Literal["auto"] | None rendering as only 'enum: "auto"',
    dropping the bool alternative.
    """

    def test_a_model_arm_survives_beside_an_enum_arm(self) -> None:
        """An enum arm must not delete the model arms from the same cell.

        `format: FormatAlias | str | FormatConfig | None` is both — the enum
        branch used to return early with only the scalar extras, orphaning the
        `FormatConfig` section and telling authoring agents an object form was
        illegal while the JSON Schema said it was legal.
        """
        from dbt_charts.core.compile.schema.renderers.prompt import render_prompt

        result = render_prompt(introspect())
        assert "[FormatConfig](#formatconfig)" in result, (
            "every `format` row lost its FormatConfig link: the enum branch of "
            "_type_cell drops nested_models"
        )

    def test_scale_zero_type_cell_includes_bool(self) -> None:
        from dbt_charts.core.compile.schema.renderers.prompt import render_prompt

        result = render_prompt(introspect())
        # ScaleContinuousStylePatch.zero: bool | Literal["auto"] | None must render
        # as "bool | enum: "auto"" — not just 'enum: "auto"'.
        assert '`zero` | bool \\| enum: "auto"' in result, (
            "scale.zero must show bool alongside the auto enum in the rendered reference"
        )


def test_a_color_facet_survives_every_route_to_the_authored_model() -> None:
    """A field's *meaning* has to reach the model the panel actually reads.

    There are three routes from a source model to the thing the design surface
    describes, and the facet has to survive all of them:

    - reused verbatim — an all-optional `_PatchBase` is its own patch, which is
      why there is no `FontStylePatch`;
    - hand-written — `BorderStylePatch` is declared by hand and registered, so
      `build_patch_model_ext` short-circuits before any forwarding runs;
    - generated — `build_patch_model` synthesises the class and drops every
      marker outside `_FORWARDED_MARKER_TYPES`.

    Only the third exercises the forwarding this module's `Facet` entry exists
    for. `KpiTonesStylePatch` and `StylePatch` are generated; both arrive
    carrying nothing if `Facet` leaves that tuple. Which route a model takes is
    decided by whether it has a required field, so it can move between them
    without anyone touching the facets.
    """
    from dbt_charts.core.compile.models.markers import Color

    models = introspect().models
    for model_name, field_name in (
        ("FontStyle", "color"),
        ("BorderStylePatch", "color"),
        ("KpiTonesStylePatch", "positive"),
        ("StylePatch", "color"),
    ):
        field = next(f for f in models[model_name].fields if f.name == field_name)
        assert any(isinstance(facet, Color) for facet in field.facets), (
            f"{model_name}.{field_name} lost its Color facet"
        )
