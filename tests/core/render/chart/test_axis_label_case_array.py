"""Tests for inject_axis_label_case's handling of a two-row array labelExpr.

The sub-day clock vocabulary's date-context row (time_unit_detect.py's
default_subday_label_expr_for) returns a JS array-literal string —
"[core, date_row]" — so Vega renders each element on its own <tspan> line.
Wrapping that whole string in a bare `upper(...)`/`lower(...)` call coerces
the array to a comma-joined string via JS's Array#toString before Vega's own
case function ever runs, collapsing both rows onto one line
("MIDNIGHT,AUG 11" instead of two lines). inject_axis_label_case must wrap
each array element independently instead.
"""

from __future__ import annotations

import types

from dbt_charts.core.render.chart.vl_field_maps import inject_axis_label_case


def _axis(case: str | None) -> types.SimpleNamespace:
    font = types.SimpleNamespace(case=case)
    labels = types.SimpleNamespace(font=font)
    return types.SimpleNamespace(labels=labels)


class TestInjectAxisLabelCaseScalar:
    def test_wraps_a_plain_expression(self) -> None:
        result = inject_axis_label_case({"labelExpr": "datum.label"}, _axis("upper"))
        assert result["labelExpr"] == "upper(datum.label)"

    def test_defaults_to_datum_label_when_no_expr_present(self) -> None:
        result = inject_axis_label_case({}, _axis("lower"))
        assert result["labelExpr"] == "lower(datum.label)"

    def test_no_op_for_unsupported_case_values(self) -> None:
        ax_vl = {"labelExpr": "datum.label"}
        result = inject_axis_label_case(ax_vl, _axis("title"))
        assert result == ax_vl


class TestInjectAxisLabelCaseArray:
    def test_wraps_each_row_of_a_two_row_array_independently(self) -> None:
        ax_vl = {
            "labelExpr": "[hours(datum.value) === 0 ? 'Midnight' : 'x', "
            "hours(datum.value) === 0 ? utcFormat(datum.value, '%b %-d') : '']"
        }
        result = inject_axis_label_case(ax_vl, _axis("upper"))
        expr = result["labelExpr"]
        assert expr.startswith("[") and expr.endswith("]")
        # Each row is independently wrapped -- never a single upper() call
        # around the whole array (which would stringify it via Array#toString).
        assert not expr.startswith("upper([")
        assert expr.count("upper(") == 2

    def test_array_wrap_does_not_stringify_the_two_rows(self) -> None:
        """Regression: a bare `upper([a, b])` coerces the array via JS's
        Array#toString, producing "A,B" as ONE string instead of Vega
        rendering two separate <tspan> lines. Simulate JS's toString
        semantics on the emitted expression's outer shape to confirm it is
        still a genuine two-element array literal, not a comma-joined
        string wrapped in a case call.
        """
        ax_vl = {"labelExpr": "['Midnight', utcFormat(datum.value, '%b %-d')]"}
        result = inject_axis_label_case(ax_vl, _axis("upper"))
        expr = result["labelExpr"]
        assert expr == "[upper('Midnight'), upper(utcFormat(datum.value, '%b %-d'))]"
