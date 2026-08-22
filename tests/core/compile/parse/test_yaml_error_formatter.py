"""Tests for YAML error formatting.

Tests verify that validation errors include:
1. Line numbers where errors occur
2. Context - the actual YAML snippet
3. Helpful suggestions (e.g., "Did you mean 'bar'?")
4. Graceful handling of common mistakes
"""

import pytest

from dbt_charts.core.compile import compile
from dbt_charts.core.compile.parse.yaml_error_formatter import (
    get_valid_chart_types,
    get_yaml_context,
    suggest_similar_value,
)


class TestDynamicTypeExtraction:
    """Tests for dynamic extraction of valid types from type definitions."""

    def test_get_valid_chart_types_returns_tuple(self):
        """Test that get_valid_chart_types returns a non-empty tuple."""
        chart_types = get_valid_chart_types()
        assert isinstance(chart_types, tuple)
        assert len(chart_types) > 0

    def test_get_valid_chart_types_contains_expected_values(self):
        """Test that common chart types are included."""
        chart_types = get_valid_chart_types()
        expected = ["bar", "line", "area", "table", "kpi", "scatter"]
        for expected_type in expected:
            assert expected_type in chart_types, f"Missing chart type: {expected_type}"

    def test_get_valid_chart_types_matches_authored_union(self):
        """Test that returned types match authored YAML chart tags."""
        from typing import get_args

        from pydantic import Tag

        from dbt_charts.core.compile.models.chart.authored import (
            AUTHORED_CHART_TYPE_TAGS,
            SUPPORTED_AUTHORED_CHART_TYPES,
            AuthoredChart,
        )

        chart_types = get_valid_chart_types()
        assert chart_types == AUTHORED_CHART_TYPE_TAGS
        assert isinstance(SUPPORTED_AUTHORED_CHART_TYPES, frozenset)
        assert frozenset(AUTHORED_CHART_TYPE_TAGS) == SUPPORTED_AUTHORED_CHART_TYPES

        authored_union = get_args(AuthoredChart)[0]
        union_tags = tuple(
            tag.tag
            for chart_variant in get_args(authored_union)
            for tag in get_args(chart_variant)[1:]
            if isinstance(tag, Tag)
        )
        assert union_tags == AUTHORED_CHART_TYPE_TAGS

        # Internal/future chart marks should not be advertised as authored YAML.
        assert "circle" not in chart_types
        assert "boxplot" not in chart_types


class TestGetYamlContext:
    """Tests for extracting YAML context around an error."""

    def test_context_shows_surrounding_lines(self):
        """Test context shows lines before and after the error."""
        yaml_content = """title: My Dashboard
queries:
  sales:
    sql: SELECT * FROM sales
charts:
  revenue:
    type: bars
    query: sales
rows:
  - revenue
"""
        context = get_yaml_context(yaml_content, 7, context_lines=2)

        # Should show lines 5-9 (2 before, error line, 2 after)
        assert "charts:" in context
        assert "revenue:" in context
        assert "type: bars" in context
        assert "query: sales" in context

    def test_context_at_start_of_file(self):
        """Test context handles errors at the start of file."""
        yaml_content = """title: My Dashboard
rows: []
"""
        context = get_yaml_context(yaml_content, 1, context_lines=2)
        assert "title:" in context

    def test_context_marks_error_line(self):
        """Test context clearly marks the error line."""
        yaml_content = """title: My Dashboard
queries:
  sales:
    sql: SELECT * FROM sales
charts:
  revenue:
    type: bars
    query: sales
rows:
  - revenue
"""
        context = get_yaml_context(yaml_content, 7, context_lines=2)

        # The error line should be marked (e.g., with arrow or highlighting)
        assert "type: bars" in context
        # Should have some marker for the error line
        assert (
            "#" in context or "<--" in context or ">>>" in context or "^^^" in context
        )


class TestSuggestSimilarValue:
    """Tests for suggesting similar values (typo correction)."""

    def test_suggest_chart_type_typo(self):
        """Test suggesting correct chart type for typos."""
        valid_types = ["bar", "line", "area", "pie", "table", "kpi", "scatter"]

        # Test common typos
        assert suggest_similar_value("bars", valid_types) == "bar"
        assert suggest_similar_value("lines", valid_types) == "line"
        # "barchart" is too different from "bar" with default cutoff, that's expected
        assert suggest_similar_value("barchart", valid_types, cutoff=0.4) == "bar"
        assert suggest_similar_value("Bar", valid_types) == "bar"

    def test_no_suggestion_for_completely_wrong_value(self):
        """Test no suggestion when value is too different."""
        valid_types = ["bar", "line", "area"]
        # 'xyz123' is too different from any valid type
        suggestion = suggest_similar_value("xyz123", valid_types)
        assert suggestion is None

    def test_suggest_field_name(self):
        """Test suggesting field names."""
        valid_fields = [
            "query",
            "type",
            "title",
            "subtitle",
            "description",
            "x",
            "y",
            "color",
        ]

        assert suggest_similar_value("querry", valid_fields) == "query"
        assert suggest_similar_value("tittle", valid_fields) == "title"


class TestFormatValidationError:
    """Tests for the main error formatting function."""

    def test_format_invalid_chart_type(self):
        """Test formatting error for invalid chart type."""
        yaml_content = """title: Test
queries:
  q1:
    sql: SELECT 1
    source: test
charts:
  my_chart:
    type: bars
    query: q1
rows:
  - my_chart
"""
        result = compile(yaml_content)

        # Should fail compilation
        assert not result.success
        assert len(result.errors) > 0

        # Get the error message
        error_msg = str(result.errors[0])

        # Error should mention line number
        # (We can check for this after implementation)

        # Error should mention the chart name or type field
        assert "my_chart" in error_msg.lower() or "type" in error_msg.lower()

    def test_format_missing_required_field(self):
        """Test formatting error for missing required field."""
        yaml_content = """title: Test
queries:
  q1:
    sql: SELECT 1
    source: test
charts:
  my_kpi:
    type: kpi
    query: q1
rows:
  - my_kpi
"""
        result = compile(yaml_content)

        # KPI without value should fail
        assert not result.success
        assert len(result.errors) > 0

        error_msg = str(result.errors[0])
        # Should mention 'value' field is required
        assert "value" in error_msg.lower()

    def test_format_reference_error(self):
        """Test formatting error for invalid reference."""
        yaml_content = """title: Test
queries:
  q1:
    sql: SELECT 1
    source: test
charts:
  my_chart:
    type: bar
    query: nonexistent_query
rows:
  - my_chart
"""
        result = compile(yaml_content)

        # Should fail due to nonexistent query reference
        assert not result.success
        assert len(result.errors) > 0

        error_msg = str(result.errors[0])
        # Should mention the missing reference
        assert (
            "nonexistent_query" in error_msg.lower() or "not found" in error_msg.lower()
        )


class TestChartFieldDiagnostics:
    """Tests for family-aware chart field diagnostics."""

    def test_family_field_map_matches_authored_chart_union_tags(self):
        """The diagnostics helper stays in sync with the authored chart union."""
        from typing import cast, get_args

        from pydantic import BaseModel, Tag

        from dbt_charts.core.compile.models.chart.authored import AuthoredChart
        from dbt_charts.core.compile.parse.yaml_error_formatter import (
            _authored_chart_fields_by_type,
        )

        union = get_args(AuthoredChart)[0]
        expected: dict[str, frozenset[str]] = {}
        for branch in get_args(union):
            branch_args = get_args(branch)
            chart_model = cast(type[BaseModel], branch_args[0])
            tag = next(
                metadata.tag
                for metadata in branch_args[1:]
                if isinstance(metadata, Tag)
            )
            expected[tag] = frozenset(chart_model.model_fields)

        assert _authored_chart_fields_by_type() == expected

    def test_table_height_reports_unsupported_family_not_self_suggestion(self):
        """A valid field on another family should not suggest itself."""
        yaml_content = """title: Test
queries:
  q1:
    sql: SELECT 'A' AS label, 1 AS value
    source: test
charts:
  table_chart:
    type: table
    query: q1
    height: 240
rows:
  - table_chart
"""
        result = compile(yaml_content)

        assert not result.success
        height_error = next(
            error for error in result.errors if error.path.endswith("height")
        )

        assert height_error.hint is not None
        assert "Did you mean 'height'?" not in height_error.hint
        assert "`height:` is not supported on `type: table`" in height_error.hint
        assert "Supported chart types for `height:`" in height_error.hint

    @pytest.mark.parametrize(
        "chart_type",
        [
            "kpi",
            "callout",
            "spark_bar",
        ],
    )
    def test_extended_height_rejecting_families_get_family_hint(self, chart_type):
        """Renderer-owned-sizing families (kpi/callout/spark_bar) should get the
        same truthful height rule. pie/geoshape/point_map/bubble_map now author
        height/width directly (_RadialChartFields/_GeoChartFields) and are
        exercised by test_geo_and_pie_families_accept_height_width instead.
        """
        chart_bodies = {
            "kpi": """    type: kpi
    query: q1
    value: value
    height: 240
""",
            "callout": """    type: callout
    message: Check the dashboard note.
    height: 240
""",
            "spark_bar": """    type: spark_bar
    query: q1
    x: label
    y: value
    height: 240
""",
        }
        yaml_content = f"""title: Test
queries:
  q1:
    sql: SELECT 'US' AS label, 1 AS value
    source: test
charts:
  checked_chart:
{chart_bodies[chart_type]}rows:
  - checked_chart
"""
        result = compile(yaml_content)

        assert not result.success
        height_error = next(
            error for error in result.errors if error.path.endswith("height")
        )

        assert height_error.hint is not None
        assert "Did you mean 'height'?" not in height_error.hint
        assert (
            f"`height:` is not supported on `type: {chart_type}`" in height_error.hint
        )

    @pytest.mark.parametrize(
        ("chart_type", "body"),
        [
            (
                "pie",
                "    type: pie\n    query: q1\n    theta: value\n    color: label\n    height: 240\n    width: 320\n",
            ),
            (
                "map",
                "    type: map\n    query: q1\n    geo_source: world-countries\n"
                "    lookup: label\n    color: value\n    height: 240\n    width: 320\n",
            ),
            (
                "point_map",
                "    type: point_map\n    query: q1\n    latitude: value\n"
                "    longitude: value\n    height: 240\n    width: 320\n",
            ),
        ],
    )
    def test_geo_and_pie_families_accept_height_width(self, chart_type, body):
        """pie/geoshape/point_map author height/width directly — no rejection."""
        yaml_content = f"""title: Test
queries:
  q1:
    sql: SELECT 'US' AS label, 1 AS value
    source: test
charts:
  checked_chart:
{body}rows:
  - checked_chart
"""
        result = compile(yaml_content)
        assert result.success, result.errors

    def test_table_width_uses_same_supported_family_hint(self):
        """Root width follows the same family-aware unsupported-field path."""
        yaml_content = """title: Test
queries:
  q1:
    sql: SELECT 'A' AS label, 1 AS value
    source: test
charts:
  table_chart:
    type: table
    query: q1
    width: 320
rows:
  - table_chart
"""
        result = compile(yaml_content)

        assert not result.success
        width_error = next(
            error for error in result.errors if error.path.endswith("width")
        )

        assert width_error.hint is not None
        assert "Did you mean 'width'?" not in width_error.hint
        assert "`width:` is not supported on `type: table`" in width_error.hint
        assert "Supported chart types for `width:`" in width_error.hint

    def test_height_typo_on_supporting_chart_keeps_did_you_mean_hint(self):
        """Typos should still use the existing did-you-mean flow."""
        yaml_content = """title: Test
queries:
  q1:
    sql: SELECT 'A' AS label, 1 AS value
    source: test
charts:
  bar_chart:
    type: bar
    query: q1
    x: label
    y: value
    heigth: 240
rows:
  - bar_chart
"""
        result = compile(yaml_content)

        assert not result.success
        typo_error = next(
            error for error in result.errors if error.path.endswith("heigth")
        )

        assert typo_error.hint is not None
        assert "Did you mean 'height'?" in typo_error.hint


class TestExtraForbiddenSchemaAwareHints:
    """Extra-field diagnostics should be driven by the model at that YAML level."""

    def test_variable_unknown_field_lists_allowed_keys(self):
        yaml_content = """title: Test
variables:
  region:
    input: select
    values: [North, South]
rows: []
"""
        result = compile(yaml_content)

        assert not result.success
        error = result.errors[0]

        assert (
            error.message
            == "Unknown field 'values' at variables.region. Full path: variables.region.values."
        )
        assert error.path == "variables.region.values"
        assert error.hint is not None
        assert "Allowed keys:" in error.hint
        assert "input" in error.hint
        assert "label" in error.hint
        assert "options" in error.hint
        assert "default" in error.hint
        assert "Did you mean" not in error.hint
        assert "See: dct docs variables" in error.hint
        assert error.fields["unknown_field"] == "values"
        assert "options" in error.fields["allowed_keys"]
        assert error.fields["docs_topic"] == "variables"

    def test_variable_options_typo_drills_into_nested_model(self):
        yaml_content = """title: Test
variables:
  region:
    input: select
    options:
      statc: [North, South]
rows: []
"""
        result = compile(yaml_content)

        assert not result.success
        error = result.errors[0]

        assert (
            error.message
            == "Unknown field 'statc' at variables.region.options. Full path: variables.region.options.statc."
        )
        assert error.hint is not None
        assert "Allowed keys: column, label_column, query, static." in error.hint
        assert "Did you mean 'static'?" in error.hint
        assert error.fields["allowed_keys"] == [
            "column",
            "label_column",
            "query",
            "static",
        ]

    def test_query_unknown_field_lists_allowed_keys(self):
        yaml_content = """title: Test
queries:
  q1:
    sql: SELECT 1
    source: test
    timeout_ms: 10
rows: []
"""
        result = compile(yaml_content)

        assert not result.success
        error = result.errors[0]

        # The union member tag appears in the path — same shape as chart-family
        # union errors (charts.c1.bar.<field>).
        assert (
            error.message
            == "Unknown field 'timeout_ms' at queries.q1.sql. Full path: queries.q1.sql.timeout_ms."
        )
        assert error.hint is not None
        assert "Allowed keys:" in error.hint
        assert "sql" in error.hint
        assert "source" in error.hint
        assert "type" in error.hint
        assert "See: dct docs queries" in error.hint

    def test_chart_style_unknown_field_lists_keys_at_nested_style_level(self):
        yaml_content = """title: Test
queries:
  q1:
    sql: SELECT 1 AS x
    source: test
charts:
  c1:
    type: line
    query: q1
    x: x
    y: x
    style:
      legend:
        disable: true
rows:
  - c1
"""
        result = compile(yaml_content)

        assert not result.success
        error = result.errors[0]

        assert (
            error.message
            == "Unknown field 'disable' at charts.c1.line.style.legend. Full path: charts.c1.line.style.legend.disable."
        )
        assert error.hint is not None
        assert "Allowed keys:" in error.hint
        assert "visible" in error.hint
        assert "Did you mean 'visible'?" in error.hint
        assert "See: dct docs charts" in error.hint

    def test_line_format_at_chart_root_points_at_style_number_format(self):
        yaml_content = """title: Test
queries:
  q1:
    sql: SELECT 1 AS x
    source: test
charts:
  c1:
    type: line
    query: q1
    x: x
    y: x
    format: currency_compact
rows:
  - c1
"""
        result = compile(yaml_content)

        assert not result.success
        err = next(e for e in result.errors if e.path.endswith("format"))
        assert err.hint is not None
        assert "style.number_format" in err.hint
        assert "layered" not in err.hint

    def test_line_formatter_at_chart_root_points_at_style_number_format(self):
        yaml_content = """title: Test
queries:
  q1:
    sql: SELECT 1 AS x
    source: test
charts:
  c1:
    type: line
    query: q1
    x: x
    y: x
    formatter: ",.0f"
rows:
  - c1
"""
        result = compile(yaml_content)

        assert not result.success
        err = next(e for e in result.errors if e.path.endswith("formatter"))
        assert err.hint is not None
        assert "style.number_format" in err.hint

    @pytest.mark.parametrize("chart_id", ["axis_x", "axis_y"])
    def test_chart_root_format_hint_ignores_chart_id_named_after_an_axis(
        self, chart_id
    ):
        """A chart whose id happens to be ``axis_x``/``axis_y`` and authors a
        chart-root ``format:`` must still get the chart-root hint
        (``style.number_format``), not an axis-specific hint. The axis lookup
        for this hint scans ``field_path`` for an ``axis_x``/``axis_y``
        segment; if that scan isn't bounded to the segments *under* the
        chart, it mistakes the chart's own id for an axis container."""
        import yaml

        body = {
            "title": "Test",
            "queries": {
                "q1": {"sql": "SELECT 1 AS x", "source": "test"},
            },
            "charts": {
                chart_id: {
                    "type": "line",
                    "query": "q1",
                    "x": "x",
                    "y": "x",
                    "format": "currency_compact",
                },
            },
            "rows": [chart_id],
        }
        result = compile(yaml.dump(body, sort_keys=False))

        assert not result.success
        err = next(e for e in result.errors if e.path.endswith("format"))
        assert err.hint is not None
        assert "style.number_format" in err.hint
        assert "style.axis_x.labels.format" not in err.hint

    @pytest.mark.parametrize(
        "axis_x_style",
        [
            pytest.param({"format": "%b"}, id="bare-format"),
            pytest.param({"labels": {"formatter": "%b"}}, id="labels-formatter"),
        ],
    )
    def test_axis_x_format_hint_points_at_axis_x_labels_format(self, axis_x_style):
        """An extra format-ish field anywhere under ``style.axis_x`` — bare
        ``format:`` (skipping the ``labels:`` nesting) or ``formatter:`` at
        the right nesting but the wrong leaf name — is unsupported. The hint
        must name the field an x-axis author would actually reach for, not
        the y-axis one, regardless of how deep the offending field sits
        (``_chart_type_from_error_path``'s reverse-scan finds the chart tag
        at any depth; the axis-name lookup for this hint must do the same)."""
        import yaml

        # scale.continuous.zero is a current-schema-only field (added in the
        # v0.4.0 migration); pairing it with the axis's format-ish field is
        # what makes the 0.3.1-spelling migration recognizer fail to match
        # this chart's style, so the offending field reaches Pydantic as a
        # genuine extra-field error instead of being silently migrated away
        # first — the only state that exercises this hint at all.
        axis_x_style = {**axis_x_style, "scale": {"continuous": {"zero": False}}}
        body = {
            "title": "Test",
            "queries": {
                "q1": {
                    "sql": "SELECT '2026-01-01'::date AS d, 1 AS v",
                    "source": "test",
                }
            },
            "charts": {
                "c1": {
                    "type": "area",
                    "query": "q1",
                    "x": "d",
                    "y": "v",
                    "style": {"axis_x": axis_x_style},
                }
            },
            "rows": ["c1"],
        }
        result = compile(yaml.dump(body, sort_keys=False))

        assert not result.success
        err = next(e for e in result.errors if e.path.endswith(("format", "formatter")))
        assert err.hint is not None
        assert "style.axis_x.labels.format" in err.hint
        assert "style.axis_y.labels.format" not in err.hint
        assert "style.number_format" not in err.hint

    def test_axis_y_format_hint_still_points_at_axis_y_labels_format(self):
        """The y-axis nested case already named the right field; keep it that
        way after branching the x-axis case out."""
        yaml_content = """title: Test
queries:
  q1:
    sql: SELECT '2026-01-01'::date AS d, 1 AS v
    source: test
charts:
  c1:
    type: area
    query: q1
    x: d
    y: v
    style:
      axis_y:
        format: ",.0f"
        scale:
          continuous:
            zero: false
rows:
  - c1
"""
        result = compile(yaml_content)

        assert not result.success
        err = next(e for e in result.errors if e.path.endswith("format"))
        assert err.hint is not None
        assert "style.axis_y.labels.format" in err.hint

    def test_axis_format_hints_name_only_fields_that_actually_validate(self):
        """A diagnostic hint naming a field that does not exist is the same
        class of defect it claims to fix. Extract every backtick field path
        from each axis hint and confirm it validates on a real chart.

        Blind spot: the extraction regex requires at least one dot, so a
        future single-segment recommendation (e.g. ``number_format:``) would
        be silently skipped rather than probed — ``assert field_paths`` only
        catches a hint with zero multi-segment paths, not a hint that mixes
        a valid multi-segment path with an unchecked single-segment one."""
        import re

        import yaml

        def hint_for_axis(axis: str, value: str) -> str:
            body = {
                "title": "Test",
                "queries": {
                    "q1": {
                        "sql": "SELECT '2026-01-01'::date AS d, 1 AS v",
                        "source": "test",
                    }
                },
                "charts": {
                    "c1": {
                        "type": "area",
                        "query": "q1",
                        "x": "d",
                        "y": "v",
                        "style": {
                            axis: {
                                "format": value,
                                "scale": {"continuous": {"zero": False}},
                            }
                        },
                    }
                },
                "rows": ["c1"],
            }
            result = compile(yaml.dump(body, sort_keys=False))
            assert not result.success
            err = next(e for e in result.errors if e.path.endswith("format"))
            assert err.hint is not None
            return err.hint

        def yaml_for_field_path(field_path: str, value: str) -> str:
            segments = field_path.split(".")
            node: object = value
            for segment in reversed(segments):
                node = {segment: node}
            chart = {"type": "area", "query": "q1", "x": "d", "y": "v"}
            assert isinstance(node, dict)
            chart.update(node)
            body = {
                "title": "Test",
                "queries": {
                    "q1": {
                        "sql": "SELECT '2026-01-01'::date AS d, 1 AS v",
                        "source": "test",
                    }
                },
                "charts": {"c1": chart},
                "rows": ["c1"],
            }
            return yaml.dump(body, sort_keys=False)

        checked_paths: set[str] = set()
        for axis, value in (("axis_x", "%b"), ("axis_y", ",.0f")):
            hint = hint_for_axis(axis, value)
            field_paths = re.findall(r"`([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)+):`", hint)
            assert field_paths, f"hint for {axis} named no field paths: {hint!r}"
            for field_path in field_paths:
                if field_path in checked_paths:
                    continue
                checked_paths.add(field_path)
                probe = yaml_for_field_path(field_path, value)
                probe_result = compile(probe)
                assert probe_result.success, (
                    f"hint named `{field_path}:`, which does not validate: "
                    f"{[e.message for e in probe_result.errors]}"
                )

    def test_table_format_at_chart_root_points_at_style_columns(self):
        yaml_content = """title: Test
queries:
  q1:
    sql: SELECT 1 AS amount
    source: test
charts:
  t1:
    type: table
    query: q1
    format: currency_compact
rows:
  - t1
"""
        result = compile(yaml_content)

        assert not result.success
        err = next(e for e in result.errors if e.path.endswith("format"))
        assert err.hint is not None
        assert "style.columns" in err.hint

    def test_kpi_format_at_chart_root_uses_moved_field_hint(self):
        """`format:` at the KPI chart root has its own moved-field validator (mirrors
        glyph/tone), so it should not fall through to the generic same-chart-family
        hint — it should point straight at style.value.format."""
        yaml_content = """title: Test
queries:
  q1:
    sql: SELECT 1 AS value
    source: test
charts:
  c1:
    type: kpi
    query: q1
    value: value
    format: "$,.2f"
rows:
  - c1
"""
        result = compile(yaml_content)

        assert not result.success
        err = next(e for e in result.errors if "format" in e.message.lower())
        assert "style.value.format" in err.message

    def test_string_formatter_uses_same_style_migration_hint(self):
        yaml_content = """title: Test
queries:
  q1:
    sql: SELECT 1 AS x
    source: test
charts:
  c1:
    type: line
    query: q1
    x: x
    y: x
    style:
      height: 240
rows:
  - c1
"""
        result = compile(yaml_content)

        assert not result.success
        err = next(e for e in result.errors if e.hint and "height" in e.hint.lower())
        assert "chart.height must be set at the chart root" in err.hint
        assert "not under style:" in err.hint


class TestNormalizationExtraForbiddenErrors:
    """Tests for extra-forbidden errors during normalization (not parse).

    These test the PydanticValidationError handler in compile() around
    normalize_board, ensuring field paths are surfaced (not just the message).
    """

    def test_extra_field_in_style_shows_path(self):
        """Extra field in style.charts should show the full path."""
        yaml_content = """title: Test
queries:
  q1:
    sql: SELECT 1
    source: test
charts:
  my_chart:
    type: bar
    query: q1
    x: date
    y: amount
style:
  charts:
    bogus_field: red
rows:
  - my_chart
"""
        result = compile(yaml_content)

        assert not result.success
        assert len(result.errors) >= 1
        # result.errors is list[Diagnostic] — join messages to check path
        error_msgs = " ".join(e.message for e in result.errors)

        # Full root-relative path so users know WHERE the error is
        assert "style.charts.bogus_field" in error_msgs

    def test_multiple_extra_fields_all_surfaced(self):
        """Multiple extra fields should all appear in the error output."""
        yaml_content = """title: Test
queries:
  q1:
    sql: SELECT 1
    source: test
charts:
  my_chart:
    type: bar
    query: q1
    x: date
    y: amount
style:
  charts:
    bad_one: 1
    bad_two: 2
rows:
  - my_chart
"""
        result = compile(yaml_content)

        assert not result.success
        # Each extra field is its own Diagnostic — join paths to check both
        all_field_paths = " ".join(e.path or "" for e in result.errors)

        # Both extra fields must appear with full root-relative paths
        assert "style.charts.bad_one" in all_field_paths
        assert "style.charts.bad_two" in all_field_paths

    def test_extra_field_in_nested_style_section(self):
        """Extra field in style.charts.axis should show nested path."""
        yaml_content = """title: Test
queries:
  q1:
    sql: SELECT 1
    source: test
charts:
  my_chart:
    type: bar
    query: q1
    x: date
    y: amount
style:
  charts:
    axis:
      nonexistent_prop: true
rows:
  - my_chart
"""
        result = compile(yaml_content)

        assert not result.success
        error_msgs = " ".join(e.message for e in result.errors)

        # Full nested path from root
        assert "style.charts.axis.nonexistent_prop" in error_msgs


class TestDotSeparatedFieldPaths:
    """Field paths in compile errors use dot notation, not arrows."""

    def test_extra_field_uses_dots_in_message(self):
        yaml_content = """title: Test
queries:
  q1:
    sql: SELECT 1
    source: test
charts:
  my_chart:
    type: bar
    query: q1
    x: date
    y: amount
style:
  charts:
    bogus_key: red
rows:
  - my_chart
"""
        result = compile(yaml_content)

        assert not result.success
        error_msgs = " ".join(e.message for e in result.errors)

        assert "style.charts.bogus_key" in error_msgs
        assert " -> " not in error_msgs

    def test_extra_field_uses_dots_in_field_path(self):
        yaml_content = """title: Test
queries:
  q1:
    sql: SELECT 1
    source: test
charts:
  my_chart:
    type: bar
    query: q1
    x: date
    y: amount
style:
  charts:
    bogus_key: red
rows:
  - my_chart
"""
        result = compile(yaml_content)

        assert not result.success
        all_field_paths = " ".join(e.path or "" for e in result.errors)

        assert "style.charts.bogus_key" in all_field_paths
        assert " -> " not in all_field_paths

    def test_nested_extra_field_uses_dots(self):
        yaml_content = """title: Test
variables:
  region:
    input: select
    values: [North, South]
rows: []
"""
        result = compile(yaml_content)

        assert not result.success
        error = result.errors[0]

        assert "variables.region" in error.message
        assert "variables.region.values" in error.message
        assert " -> " not in error.message
        assert error.path == "variables.region.values"


class TestIntegration:
    """Integration tests for end-to-end error formatting."""

    def test_full_error_message_format(self):
        """Test complete error message has all components."""
        yaml_content = """title: Test Dashboard
description: Testing error messages

queries:
  sales_query:
    sql: SELECT * FROM sales
    source: test_db

charts:
  revenue_chart:
    title: Revenue
    type: bars
    query: sales_query
    x: date
    y: amount

rows:
  - revenue_chart
"""
        result = compile(yaml_content)

        # Should fail due to invalid chart type 'bars'
        assert not result.success
        assert len(result.errors) > 0

        error_msg = str(result.errors[0])

        # After implementation, the error message should contain:
        # 1. Line number reference
        # 2. The invalid value 'bars'
        # 3. Suggestion for 'bar'
        # 4. List of valid types

        # Error should mention the chart name or chart field
        assert "revenue_chart" in error_msg.lower() or "chart" in error_msg.lower()

    def test_multiple_errors_all_formatted(self):
        """Test that multiple errors are all properly formatted."""
        yaml_content = """title: Test
queries:
  q1:
    sql: SELECT 1
    source: test
charts:
  chart1:
    type: bars
    query: q1
  chart2:
    type: kpi
    query: q1
rows:
  - chart1
  - chart2
"""
        result = compile(yaml_content)

        # Should have errors (kpi without value, possibly also bars invalid type)
        assert not result.success

        # Verify we get at least one error
        assert len(result.errors) >= 1

        # All errors should be properly formatted
        all_msgs = " ".join(str(e) for e in result.errors).lower()
        # At least kpi/value error should appear
        assert "kpi" in all_msgs or "value" in all_msgs or "chart2" in all_msgs

        # Each error message should be non-empty and contain relevant info
        for error in result.errors:
            error_msg = str(error)
            assert len(error_msg) > 0
            # Error messages should not be raw Python exception traces
            assert "Traceback" not in error_msg


class TestCollapseUnionValidationErrors:
    """Tests for union-aware collapse of Pydantic validation errors.

    These tests pin the fix for the 164-error firehose produced by invalid
    layout rows. Each test verifies that the collapse logic produces ≤3
    structured errors per input row and suppresses phantom union-branch noise.
    """

    def test_inline_board_row_with_invalid_style_produces_few_errors(self):
        """One row with {title, text, style} and invalid style.row-gap → ≤3 errors.

        This is the canonical repro: AuthoredBoard.rows tries str, AuthoredBoard,
        ChartPatch, dict[str, ChartPatch] for every item.
        With a {title+text+style} dict the match is AuthoredBoard; only its
        extra_forbidden field error should survive.
        """
        from pydantic import ValidationError as PydanticValidationError

        from dbt_charts.core.compile.models.board.authored import AuthoredBoard
        from dbt_charts.core.compile.parse.yaml_error_formatter import (
            format_validation_errors_structured,
        )

        yaml_content = """title: Test
rows:
  - title: "Section"
    text: "Some text"
    style:
      row-gap: 10px
"""
        import yaml

        data = yaml.safe_load(yaml_content)
        try:
            AuthoredBoard(**data)
        except PydanticValidationError as e:
            errors = format_validation_errors_structured(e, yaml_content)
            # Key assertions: collapsed to few errors
            assert len(errors) <= 3, (
                f"Expected ≤3 errors, got {len(errors)}: "
                f"{[err.message for err in errors]}"
            )
            # No phantom AuthoredChart branch errors when input has 'text' key
            for err in errors:
                assert "AuthoredChart" not in err.message, (
                    f"Phantom AuthoredChart branch noise: {err.message!r}"
                )
            # Each error has field_path and code
            for err in errors:
                assert err.path is not None and err.path != "", (
                    f"Error missing field_path: {err}"
                )
                assert err.code.startswith("ERR-"), (
                    f"Error code should start with 'ERR-': {err.code!r}"
                )
        else:
            pytest.fail("Expected ValidationError not raised")

    def test_inline_board_row_code_is_err_compile(self):
        """Collapsed errors use compile-domain ERR-* or ERR-INTERNAL codes (no bare strings)."""
        from pydantic import ValidationError as PydanticValidationError

        from dbt_charts.core.compile.models.board.authored import AuthoredBoard
        from dbt_charts.core.compile.parse.yaml_error_formatter import (
            format_validation_errors_structured,
        )

        yaml_content = """title: Test
rows:
  - title: "Section"
    text: "Some text"
    style:
      row-gap: 10px
"""
        import yaml

        data = yaml.safe_load(yaml_content)
        try:
            AuthoredBoard(**data)
        except PydanticValidationError as e:
            errors = format_validation_errors_structured(e, yaml_content)
            for err in errors:
                assert err.code.startswith("ERR-"), (
                    f"Expected ERR-* code, got {err.code!r}"
                )
        else:
            pytest.fail("Expected ValidationError not raised")

    def test_line_number_populated_when_yaml_content_provided(self):
        """Structured errors get a SourceRange once the caller's source map
        stamps them — the formatter itself only authors ``.path``.

        A resolved line with no known file has nowhere to land — SourceRange.file
        is required, never a sentinel (D-08). Real compile() callers always thread
        a file (compile_file() resolves the project-relative path); this test
        supplies one explicitly to exercise that same path via build_source_index
        + stamp_diagnostics, the exact pair compile() itself calls.
        """
        from pydantic import ValidationError as PydanticValidationError

        from dbt_charts.core.compile.models.board.authored import AuthoredBoard
        from dbt_charts.core.compile.parse.source_map import (
            build_source_index,
            stamp_diagnostics,
        )
        from dbt_charts.core.compile.parse.yaml_error_formatter import (
            format_validation_errors_structured,
        )

        yaml_content = """title: Test
rows:
  - title: "Section"
    text: "Some text"
    style:
      row-gap: 10px
"""
        import yaml

        data = yaml.safe_load(yaml_content)
        try:
            AuthoredBoard(**data)
        except PydanticValidationError as e:
            errors = format_validation_errors_structured(e, yaml_content)
            stamp_diagnostics(
                errors, build_source_index(yaml_content, "test.yml").source_map
            )
            # At least one error should have a line number when yaml_content provided
            lines = [err.range.start_line for err in errors if err.range is not None]
            assert lines, (
                "Expected at least one error with a line number; got none.\n"
                f"Errors: {errors}"
            )
        else:
            pytest.fail("Expected ValidationError not raised")

    def test_compile_result_errors_are_structured(self):
        """CompileResult.errors is list[Diagnostic], not list[CompilationError]."""
        from dbt_charts.core.diagnostics import Diagnostic

        yaml_content = """title: Test
rows:
  - title: "Section"
    text: "Some text"
    style:
      row-gap: 10px
"""
        result = compile(yaml_content)
        assert not result.success
        assert len(result.errors) > 0
        for err in result.errors:
            assert isinstance(err, Diagnostic), (
                f"Expected Diagnostic, got {type(err).__name__}: {err!r}"
            )

    def test_compile_result_errors_few_for_invalid_inline_board(self):
        """End-to-end: one bad inline board row → ≤3 Diagnostics in result."""
        yaml_content = """title: Test
rows:
  - title: "Section"
    text: "Some text"
    style:
      row-gap: 10px
"""
        result = compile(yaml_content)
        assert not result.success
        assert len(result.errors) <= 3, (
            f"Expected ≤3 errors, got {len(result.errors)}: "
            f"{[e.message for e in result.errors]}"
        )
        # Real error should be about row-gap (the actual invalid field)
        messages = " ".join(e.message for e in result.errors)
        assert "row-gap" in messages, f"Expected 'row-gap' in errors; got: {messages!r}"


# A fixture test against text-layout-lab.yml (from
# examples/playground-experimental/) is intentionally not covered here —
# that corpus is outside dbt-charts/.


class TestWrongShapeNestedStyleModel:
    """model_type Pydantic errors — scalar where a mapping is expected.

    Covers the repro: axis_x.label: "hi there" where AxisLabelStylePatch
    is expected. The error should use ERR-WRONG-SHAPE, not
    ERR-INTERNAL, and must show the available keys.
    """

    _REPRO_YAML = """\
title: Test
queries:
  users:
    sql: SELECT 1 AS x
    source: test
charts:
  users_by_department:
    type: bar
    query: users
    x: x
    y: x
    style:
      axis_x:
        labels: hi there
"""

    def _get_errors(self, yaml_content: str) -> list:
        import yaml as _yaml
        from pydantic import ValidationError as PydanticValidationError

        from dbt_charts.core.compile.models.board.authored import AuthoredBoard
        from dbt_charts.core.compile.parse.yaml_error_formatter import (
            format_validation_errors_structured,
        )

        data = _yaml.safe_load(yaml_content)
        try:
            AuthoredBoard(**data)
        except PydanticValidationError as e:
            return format_validation_errors_structured(e, yaml_content)
        else:
            pytest.fail("Expected ValidationError not raised")

    def test_wrong_shape_nested_style_model_shows_available_keys(self):
        """axis_x.labels scalar → ERR-WRONG-SHAPE with key list, not ERR-INTERNAL."""
        errors = self._get_errors(self._REPRO_YAML)
        assert len(errors) == 1, f"Expected 1 error, got {len(errors)}: {errors}"
        err = errors[0]
        assert err.code == "ERR-WRONG-SHAPE", (
            f"Expected ERR-WRONG-SHAPE, got {err.code!r}. message: {err.message!r}"
        )
        # Hint must name some of the available keys
        hint = err.hint or ""
        for key in ("font", "angle", "max_width"):
            assert key in hint, f"Expected key {key!r} in hint, got: {hint!r}"

    def test_wrong_shape_nested_style_model_has_line_number(self):
        """Structured error points at the 'labels: hi there' line, once stamped
        against the source map built from the same text (the formatter itself
        only authors ``.path``)."""
        from dbt_charts.core.compile.parse.source_map import (
            build_source_index,
            stamp_diagnostics,
        )

        errors = self._get_errors(self._REPRO_YAML)
        assert len(errors) == 1
        stamp_diagnostics(
            errors, build_source_index(self._REPRO_YAML, "test.yml").source_map
        )
        err = errors[0]
        assert err.range is not None, "Expected a line number in the structured error"
        # Find what line 'labels: hi there' is on
        lines = self._REPRO_YAML.splitlines()
        label_line = next(
            (i + 1 for i, ln in enumerate(lines) if ln.strip().startswith("labels:")),
            None,
        )
        assert label_line is not None, "Could not find 'labels:' in YAML"
        assert err.range.start_line == label_line, (
            f"Expected line {label_line} (labels: hi there), got {err.range.start_line}"
        )

    def test_wrong_shape_not_df_unknown_internal(self):
        """model_type errors must not fall through to ERR-INTERNAL."""
        errors = self._get_errors(self._REPRO_YAML)
        for err in errors:
            assert err.code != "ERR-INTERNAL", (
                f"model_type error fell through to ERR-INTERNAL: {err.message!r}"
            )

    def test_wrong_shape_non_axis_x_model(self):
        """model_type error on axis_y.labels shows ERR-WRONG-SHAPE (non-axis-x path)."""
        yaml_content = self._REPRO_YAML.replace("axis_x:", "axis_y:")
        errors = self._get_errors(yaml_content)
        assert len(errors) == 1
        err = errors[0]
        assert err.code == "ERR-WRONG-SHAPE", (
            f"Expected ERR-WRONG-SHAPE for axis_y.label, got {err.code!r}"
        )
        hint = err.hint or ""
        for key in ("font", "angle", "max_width"):
            assert key in hint, (
                f"Expected key {key!r} in hint for axis_y case: {hint!r}"
            )

    def test_wrong_shape_list_input_also_uses_code(self):
        """model_type fires for list inputs too; hint must say 'expects a mapping'."""
        yaml_content = self._REPRO_YAML.replace("labels: hi there", "labels: [a, b]")
        errors = self._get_errors(yaml_content)
        assert len(errors) == 1
        err = errors[0]
        assert err.code == "ERR-WRONG-SHAPE"
        hint = err.hint or ""
        assert "expects a mapping" in hint, (
            f"Hint must say 'expects a mapping' for list input, got: {hint!r}"
        )
        # Must NOT claim "not a scalar" — input is a list, not a scalar
        assert "not a scalar" not in hint, (
            f"Hint must not say 'not a scalar' for list input, got: {hint!r}"
        )
