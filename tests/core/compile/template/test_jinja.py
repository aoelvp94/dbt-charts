"""Tests for Jinja template resolution.

Tests the dbt_charts.core.compile.template.jinja module for resolving
Jinja templates in queries and other fields.
"""

import pytest

from dbt_charts.core.compile.errors import JinjaError
from dbt_charts.core.compile.template.jinja import (
    expand_query_refs,
    resolve_jinja_template,
)


class TestResolveJinjaTemplate:
    """Tests for resolve_jinja_template function."""

    def test_simple_variable(self):
        """Test resolving simple variable."""
        template = "Hello {{ name }}"
        variables = {"name": "World"}

        result = resolve_jinja_template(template, variables)

        assert result == "Hello World"

    def test_missing_variable_raises_error(self):
        """Test missing variable raises JinjaError."""
        import pytest

        from dbt_charts.core.compile.errors import JinjaError

        template = "Hello {{ name }}"
        variables = {}

        # Current implementation raises for undefined variables
        with pytest.raises(JinjaError):
            resolve_jinja_template(template, variables)

    def test_non_jinja_string(self):
        """Test non-Jinja string is returned as-is."""
        template = "This is a plain string"

        result = resolve_jinja_template(template, {})

        assert result == template

    def test_variable_with_default(self):
        """Test variable with default value using defined()."""
        # Use Jinja's 'default' filter which works with undefined
        template = "{{ name | default('Default') }}"
        variables = {}

        result = resolve_jinja_template(template, variables)

        assert result == "Default"

    def test_variable_with_value_and_default(self):
        """Test variable with value ignores default."""
        template = "{{ name or 'Default' }}"
        variables = {"name": "Custom"}

        result = resolve_jinja_template(template, variables)

        assert result == "Custom"

    def test_conditional_expression(self):
        """Test conditional expression."""
        template = "{% if active %}Active{% else %}Inactive{% endif %}"

        result_true = resolve_jinja_template(template, {"active": True})
        result_false = resolve_jinja_template(template, {"active": False})

        assert result_true == "Active"
        assert result_false == "Inactive"

    def test_for_loop(self):
        """Test for loop."""
        template = "{% for item in items %}{{ item }},{% endfor %}"
        variables = {"items": ["a", "b", "c"]}

        result = resolve_jinja_template(template, variables)

        assert result == "a,b,c,"

    def test_sql_with_variable(self):
        """Test SQL query with variable."""
        template = "SELECT * FROM orders WHERE region = '{{ region }}'"
        variables = {"region": "North"}

        result = resolve_jinja_template(template, variables)

        assert result == "SELECT * FROM orders WHERE region = 'North'"

    def test_list_variable(self):
        """Test list variable access."""
        template = "{{ dates[0] }} to {{ dates[1] }}"
        variables = {"dates": ["2024-01-01", "2024-12-31"]}

        result = resolve_jinja_template(template, variables)

        assert result == "2024-01-01 to 2024-12-31"

    def test_dict_variable(self):
        """Test dict variable access."""
        template = "{{ config.limit }}"
        variables = {"config": {"limit": 100}}

        result = resolve_jinja_template(template, variables)

        assert result == "100"


class TestSqlTemplates:
    """Tests for SQL template patterns."""

    def test_filter_in_sql(self):
        """Test conditional filter in SQL."""
        # Use 'is defined' to check for variable existence
        template = """
SELECT * FROM orders
WHERE 1=1
{% if region is defined %}
  AND region = '{{ region }}'
{% endif %}
"""
        result_with = resolve_jinja_template(template, {"region": "North"})

        assert "AND region = 'North'" in result_with

    def test_date_range_in_sql(self):
        """Test date range filter in SQL."""
        template = """
SELECT * FROM events
WHERE created_at BETWEEN '{{ start_date }}' AND '{{ end_date }}'
"""
        variables = {
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        }

        result = resolve_jinja_template(template, variables)

        assert "2024-01-01" in result
        assert "2024-12-31" in result

    def test_in_clause(self):
        """Test IN clause with list variable."""
        template = """
SELECT * FROM products
WHERE category IN ({{ categories | join(', ') }})
"""
        variables = {"categories": ["'A'", "'B'", "'C'"]}

        result = resolve_jinja_template(template, variables)

        assert "'A', 'B', 'C'" in result


class TestErrorHandling:
    """Tests for error handling in Jinja resolution."""

    def test_empty_template(self):
        """Test empty template."""
        result = resolve_jinja_template("", {})
        assert result == ""

    def test_none_variables(self):
        """Test None variables dict."""
        result = resolve_jinja_template("Hello", None)
        assert result == "Hello"


class TestExpandQueryRefs:
    """Tests for expand_query_refs.

    Verifies that nested {{ queries.* }} references are expanded in topological
    order so multi-level query composition works — and that nothing else in the
    SQL is touched on the way.
    """

    def test_single_level_reference(self):
        """One query referencing another — should work like before."""
        queries = {
            "base": {"sql": "SELECT id, name FROM users"},
            "wrapper": {"sql": "SELECT * FROM {{ queries.base }}"},
        }
        result = expand_query_refs("wrapper", queries)
        assert "SELECT id, name FROM users" in result
        assert "{{ queries." not in result

    def test_multi_level_reference(self):
        """style -> calc -> base chain should fully expand."""
        queries = {
            "base": {"sql": "SELECT id, name FROM users"},
            "calc": {"sql": "SELECT *, 1 AS flag FROM {{ queries.base }}"},
            "style": {"sql": "SELECT name, flag FROM {{ queries.calc }}"},
        }
        result = expand_query_refs("style", queries)
        assert "SELECT id, name FROM users" in result
        assert "{{ queries." not in result

    def test_sibling_reuse_of_shared_base(self):
        """Two queries referencing the same base should both resolve."""
        queries = {
            "base": {"sql": "SELECT id, amount FROM orders"},
            "summary_a": {"sql": "SELECT sum(amount) FROM {{ queries.base }}"},
            "summary_b": {"sql": "SELECT count(*) FROM {{ queries.base }}"},
        }
        result_a = expand_query_refs("summary_a", queries)
        result_b = expand_query_refs("summary_b", queries)
        assert "SELECT id, amount FROM orders" in result_a
        assert "SELECT id, amount FROM orders" in result_b
        assert "{{ queries." not in result_a
        assert "{{ queries." not in result_b

    def test_circular_dependency_raises_error(self):
        """Circular dependency should raise JinjaError."""
        queries = {
            "a": {"sql": "SELECT * FROM {{ queries.b }}"},
            "b": {"sql": "SELECT * FROM {{ queries.a }}"},
        }
        with pytest.raises(JinjaError, match="Circular query dependency"):
            expand_query_refs("a", queries)

    def test_no_query_references_passthrough(self):
        """Query without {{ queries.* }} returns its SQL unchanged."""
        queries = {
            "plain": {"sql": "SELECT 1 AS val"},
        }
        result = expand_query_refs("plain", queries)
        assert result == "SELECT 1 AS val"

    def test_reserved_word_query_name_referenced_raises(self):
        """A ref becomes a SQL alias — a reserved-word query name must fail fast."""
        from dbt_charts.core.compile.errors import CompilationError

        queries = {
            "order": {"sql": "SELECT 1 AS val"},
            "wrapper": {"sql": "SELECT val FROM {{ queries.order }}"},
        }
        with pytest.raises(CompilationError, match="reserved word"):
            expand_query_refs("wrapper", queries)

    def test_reserved_word_query_name_unreferenced_is_fine(self):
        """Only referenced names become aliases; an unreferenced reserved name is OK."""
        queries = {
            "order": {"sql": "SELECT 1 AS val"},
        }
        # `order` is never referenced via {{ queries.order }}, so no alias, no error.
        assert expand_query_refs("order", queries) == "SELECT 1 AS val"

    def test_variables_in_nested_queries_are_left_for_the_render(self):
        """A variable inside a referenced query comes through author-written.

        Expansion resolves references and nothing else. Substituting a value here
        would put it in template position for the parameterized render that
        follows, which is how a value stops being data.
        """
        queries = {
            "base": {"sql": "SELECT * FROM t WHERE region = '{{ region }}'"},
            "outer": {"sql": "SELECT count(*) FROM {{ queries.base }}"},
        }
        result = expand_query_refs("outer", queries)
        assert "region = '{{ region }}'" in result
        assert "{{ queries." not in result

    def test_three_level_chain(self):
        """A -> B -> C -> D should fully resolve."""
        queries = {
            "d": {"sql": "SELECT 1 AS x"},
            "c": {"sql": "SELECT x FROM {{ queries.d }}"},
            "b": {"sql": "SELECT x FROM {{ queries.c }}"},
            "a": {"sql": "SELECT x FROM {{ queries.b }}"},
        }
        result = expand_query_refs("a", queries)
        assert "SELECT 1 AS x" in result
        assert "{{ queries." not in result

    def test_query_with_object_attribute(self):
        """Queries passed as objects with .sql attribute should work."""

        class FakeQuery:
            def __init__(self, sql):
                self.sql = sql

        queries = {
            "base": FakeQuery("SELECT 1"),
            "outer": FakeQuery("SELECT * FROM {{ queries.base }}"),
        }
        result = expand_query_refs("outer", queries)
        assert "SELECT 1" in result
        assert "{{ queries." not in result

    @pytest.mark.parametrize(
        "helper_call",
        [
            "{{ filter('status', status) }}",
            "{{ filter_date_range('created_at', date_range) }}",
        ],
    )
    def test_a_composed_query_keeps_its_filter_helpers(self, helper_call: str) -> None:
        """A filter helper in a composed query survives expansion untouched.

        It has to: the helper is bound by the parameterized render further down,
        the same one that binds it for a query with no reference at all. Expansion
        neither evaluates it nor trips the raising compile-time stub.
        """
        queries = {
            "base": {"sql": "SELECT id, status, created_at FROM users"},
            "composed": {
                "sql": f"SELECT * FROM {{{{ queries.base }}}} WHERE {helper_call}"
            },
        }

        result = expand_query_refs("composed", queries)

        assert "SELECT id, status, created_at FROM users" in result
        assert "{{ queries." not in result
        assert helper_call in result


class TestResolveJinjaTemplateFilterBinding:
    """resolve_jinja_template's bind_filters hook — the masking that keeps
    filter() spans away from the raising compile-time stub so each can be bound
    from its own author-written text, while other callers keep that stub.

    Identity binding is used throughout: it isolates the masking half, which is
    what these cases are about."""

    def test_filter_call_raises_by_default(self) -> None:
        """Without bind_filters, {{ filter(...) }} still hits the raising stub —
        the safety behavior for callers that do not bind is unchanged."""
        from dbt_charts.core.compile.errors import CompilationError

        template = "SELECT * FROM t WHERE {{ filter('status', status) }}"
        with pytest.raises(CompilationError, match="no longer supported"):
            resolve_jinja_template(template, variables={"status": "active"})

    def test_masked_call_is_handed_to_the_binder_verbatim(self) -> None:
        """The binder receives the span as authored, while plain variables
        elsewhere in the template are resolved normally."""
        template = "SELECT * FROM t WHERE region = '{{ region }}' AND {{ filter('status', status) }}"
        result = resolve_jinja_template(
            template,
            variables={"region": "North", "status": "active"},
            bind_filters=lambda call: call,
        )
        assert "region = 'North'" in result
        assert "{{ filter('status', status) }}" in result

    @pytest.mark.parametrize("units", [[1], [1, 2]])
    def test_a_loop_may_emit_a_deferred_span_many_times(self, units: list[int]) -> None:
        """A masked span is body text; a {% for %} emits it once per iteration.

        This is the composed-query path, which every host reaches — Cloud
        included — so rejecting the repeat here broke boards that had nothing to
        do with the dbt adapter.
        """
        template = (
            "SELECT 1 FROM t WHERE "
            "{% for u in units %}{{ filter('region', region) }} OR {% endfor %} 1=0"
        )

        result = resolve_jinja_template(
            template,
            variables={"units": units, "region": "North"},
            bind_filters=lambda call: call,
        )

        assert result.count("{{ filter('region', region) }}") == len(units)

    @pytest.mark.parametrize(
        "spelling",
        [
            "{{- filter('status', status) }}",
            "{{ filter('status', status) -}}",
            "{{- filter('status', status) -}}",
        ],
    )
    def test_whitespace_control_spellings_are_deferred(self, spelling: str) -> None:
        """`{{-` / `-}}` is standard Jinja, not whitespace — it must still mask."""
        result = resolve_jinja_template(
            f"SELECT * FROM t WHERE {spelling}",
            variables={"status": "active"},
            bind_filters=lambda call: call,
        )

        assert spelling in result

    def test_filter_date_range_is_masked_too(self) -> None:
        template = (
            "SELECT * FROM t WHERE {{ filter_date_range('created_at', date_range) }}"
        )
        result = resolve_jinja_template(
            template,
            variables={"date_range": ["2025-01-01", "2025-03-31"]},
            bind_filters=lambda call: call,
        )
        assert "{{ filter_date_range('created_at', date_range) }}" in result
