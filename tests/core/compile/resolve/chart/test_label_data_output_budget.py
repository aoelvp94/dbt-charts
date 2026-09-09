"""Regression: prepare_label_data() must draw from the open render-scoped
template-output budget, not bypass it.

`labels.template` is an authored, cascade-settable board field
(SliceLabelsStyle.template) whose validator only parses syntax — full
`{% for %}` loops are accepted, so the amplification shape
(compile/template/output_budget.py's module docstring) is reachable through
it from inside an open render_dashboard() scope.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dbt_charts.core.compile.errors import TemplateOutputTooLargeError
from dbt_charts.core.compile.resolve.chart.label_data import prepare_label_data
from dbt_charts.core.compile.template.output_budget import template_output_budget

# See output_budget.py's module docstring: individually under Jinja's
# MAX_RANGE sandbox cap, but the product is enormous.
_AMPLIFICATION_TEMPLATE = (
    "{% for i in range(9999) %}{% for j in range(9999) %}x{% endfor %}{% endfor %}"
)


def _labels(template: str) -> SimpleNamespace:
    return SimpleNamespace(template=template, where=None)


class TestPrepareLabelDataDrawsFromTheOpenBudget:
    def test_amplification_template_raises_under_an_open_scope(self) -> None:
        with (
            template_output_budget(1000),
            pytest.raises(TemplateOutputTooLargeError) as exc_info,
        ):
            prepare_label_data(
                [{"x": 1}],
                _labels(_AMPLIFICATION_TEMPLATE),
                context_extras=lambda row, index: {},
            )
        # Bounded peak, not the full product materialized.
        assert exc_info.value.fields["emitted_bytes"] < 1000 * 10

    def test_cumulative_across_rows(self) -> None:
        """One row's template output stays under the ceiling; enough rows
        of it must still trip the shared budget — the bound is render-wide,
        not per row."""
        rows = [{"x": i} for i in range(20)]
        with (
            template_output_budget(100),
            pytest.raises(TemplateOutputTooLargeError),
        ):
            prepare_label_data(
                rows,
                _labels("{% for i in range(15) %}x{% endfor %}"),  # 15 bytes/row
                context_extras=lambda row, index: {},
            )

    def test_small_template_under_ceiling_is_unaffected(self) -> None:
        with template_output_budget(1000):
            result = prepare_label_data(
                [{"x": 1}],
                _labels("value: {{ x }}"),
                context_extras=lambda row, index: {},
            )
        assert result[0]["__dbt_label"] == ["value: 1"]

    def test_no_bound_without_an_open_scope(self) -> None:
        result = prepare_label_data(
            [{"x": 1}],
            _labels("value: {{ x }}"),
            context_extras=lambda row, index: {},
        )
        assert result[0]["__dbt_label"] == ["value: 1"]
