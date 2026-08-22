"""TDD tests for render_yaml_schema: AuthorableSchema IR → nested YAML tree."""

from dbt_charts.core.compile.schema.introspection import (
    AuthorableModel,
    AuthorableSchema,
    SchemaField,
    introspect,
)
from dbt_charts.core.compile.schema.renderers.yaml_schema import (
    render_yaml_schema,
)


class TestRenderYamlSchemaStructure:
    def test_returns_string(self) -> None:
        assert isinstance(render_yaml_schema(introspect()), str)

    def test_terminates(self) -> None:
        # Guard: must not recurse infinitely.
        render_yaml_schema(introspect())

    def test_two_yaml_documents(self) -> None:
        result = render_yaml_schema(introspect())
        assert "---" in result, "Expected two YAML documents separated by ---"

    def test_board_root_fields_present(self) -> None:
        result = render_yaml_schema(introspect())
        for key in ("title", "charts", "queries", "variables"):
            assert f"\n{key}:" in result or result.startswith(f"{key}:"), (
                f"Missing root field: {key}"
            )

    def test_style_section_present(self) -> None:
        result = render_yaml_schema(introspect())
        # Style document appears after the --- separator
        _, _, style_doc = result.partition("---")
        assert style_doc.strip(), "Style document is empty"


class TestRenderYamlSchemaTypes:
    def test_enum_values_pipe_joined(self) -> None:
        result = render_yaml_schema(introspect())
        # Chart type field has many literal values; they should be pipe-joined.
        assert " | " in result

    def test_none_rendered_as_null(self) -> None:
        result = render_yaml_schema(introspect())
        assert "null" in result
        assert "None" not in result

    def test_no_pydantic_noise(self) -> None:
        result = render_yaml_schema(introspect())
        assert "Tag(" not in result
        assert "Discriminator(" not in result
        assert "strict=" not in result


class TestRenderYamlSchemaRecursion:
    def test_recursive_models_noted(self) -> None:
        # A model that references itself must be stopped with a comment.
        result = render_yaml_schema(introspect())
        assert "(recursive)" in result

    def test_source_configs_not_expanded(self) -> None:
        result = render_yaml_schema(introspect())
        # BigQuerySourceConfig fields like `project` should not appear inline.
        assert "project:" not in result


class TestRenderYamlSchemaSynthetic:
    """Unit tests against a hand-crafted minimal schema."""

    def _schema(self, models: dict[str, AuthorableModel]) -> AuthorableSchema:
        return AuthorableSchema(root="Root", models=models)

    def _field(
        self,
        name: str,
        type_repr: str = "str",
        *,
        nested_models: list[str] | None = None,
        enum_values: list[str] | None = None,
        extra_union_types: list[str] | None = None,
        container: str | None = None,
        required: bool = True,
    ) -> SchemaField:
        return SchemaField(
            name=name,
            description="",
            type_repr=type_repr,
            required=required,
            default=None,
            default_repr=None,
            enum_values=enum_values,
            nested_models=nested_models or [],
            extra_union_types=extra_union_types or [],
            container=container,
        )

    def test_leaf_field(self) -> None:
        schema = self._schema(
            {
                "Root": AuthorableModel(
                    name="Root",
                    doc="",
                    fields=[self._field("title", "str")],
                    generated=False,
                )
            }
        )
        result = render_yaml_schema(schema)
        assert "title: str" in result

    def test_enum_field_pipe_joined(self) -> None:

        schema = self._schema(
            {
                "Root": AuthorableModel(
                    name="Root",
                    doc="",
                    fields=[self._field("type", enum_values=["bar", "line"])],
                    generated=False,
                )
            }
        )
        result = render_yaml_schema(schema)
        assert "type: bar | line" in result

    def test_nested_model_expanded(self) -> None:

        schema = self._schema(
            {
                "Root": AuthorableModel(
                    name="Root",
                    doc="",
                    fields=[self._field("child", nested_models=["Child"])],
                    generated=False,
                ),
                "Child": AuthorableModel(
                    name="Child",
                    doc="",
                    fields=[self._field("value", "int")],
                    generated=False,
                ),
            }
        )
        result = render_yaml_schema(schema)
        assert "child:" in result
        assert "value: int" in result

    def test_self_referential_model_stopped(self) -> None:

        schema = self._schema(
            {
                "Root": AuthorableModel(
                    name="Root",
                    doc="",
                    fields=[self._field("self_ref", nested_models=["Root"])],
                    generated=False,
                )
            }
        )
        result = render_yaml_schema(schema)
        assert "(recursive)" in result

    def test_multi_model_union_all_branches_expanded(self) -> None:

        schema = self._schema(
            {
                "Root": AuthorableModel(
                    name="Root",
                    doc="",
                    fields=[self._field("content", nested_models=["A", "B"])],
                    generated=False,
                ),
                "A": AuthorableModel(
                    name="A",
                    doc="",
                    fields=[self._field("a_field", "str")],
                    generated=False,
                ),
                "B": AuthorableModel(
                    name="B",
                    doc="",
                    fields=[self._field("b_field", "int")],
                    generated=False,
                ),
            }
        )
        result = render_yaml_schema(schema)
        assert "# --- A ---" in result
        assert "# --- B ---" in result
        assert "a_field: str" in result
        assert "b_field: int" in result

    def test_dict_container_shows_key_placeholder(self) -> None:

        schema = self._schema(
            {
                "Root": AuthorableModel(
                    name="Root",
                    doc="",
                    fields=[
                        self._field("charts", nested_models=["Chart"], container="dict")
                    ],
                    generated=False,
                ),
                "Chart": AuthorableModel(
                    name="Chart",
                    doc="",
                    fields=[self._field("type", "str")],
                    generated=False,
                ),
            }
        )
        result = render_yaml_schema(schema)
        assert "charts:" in result
        assert "<key>:" in result
        assert "type: str" in result

    def test_list_container_rendered_as_sequence(self) -> None:

        schema = self._schema(
            {
                "Root": AuthorableModel(
                    name="Root",
                    doc="",
                    fields=[
                        self._field("rows", nested_models=["Row"], container="list")
                    ],
                    generated=False,
                ),
                "Row": AuthorableModel(
                    name="Row",
                    doc="",
                    fields=[self._field("span", "int")],
                    generated=False,
                ),
            }
        )
        result = render_yaml_schema(schema)
        assert "rows:" in result
        assert "- span: int" in result

    def test_enum_values_noted_alongside_nested_model(self) -> None:
        # When a field has both enum_values and nested_models (e.g. spark: line | SparkConfig),
        # the scalar enum alternatives must appear as a comment — not be silently dropped.
        schema = self._schema(
            {
                "Root": AuthorableModel(
                    name="Root",
                    doc="",
                    fields=[
                        self._field(
                            "spark",
                            nested_models=["SparkConfig"],
                            enum_values=["line", "area", "bar"],
                        )
                    ],
                    generated=False,
                ),
                "SparkConfig": AuthorableModel(
                    name="SparkConfig",
                    doc="",
                    fields=[self._field("color", "str")],
                    generated=False,
                ),
            }
        )
        result = render_yaml_schema(schema)
        assert "# also (scalar): line | area | bar" in result
