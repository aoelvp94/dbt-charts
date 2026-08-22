"""TDD tests for ConditionalRule font field regrouping.

These tests drive the refactor: run them first to confirm they fail,
implement the changes, then confirm they pass.
"""

import pytest
from pydantic import ValidationError


class TestConditionalRuleFontModel:
    def test_nested_font_color_and_weight(self):
        from dbt_charts.core.compile.models.chart.authored import (
            ConditionalRule,
        )

        rule = ConditionalRule.model_validate(
            {
                "lt": 0,
                "background": "#fee2e2",
                "font": {"color": "#991b1b", "weight": "bold"},
            }
        )
        assert rule.font is not None
        assert rule.font.color == "#991b1b"
        assert rule.font.weight == "bold"
        assert rule.background == "#fee2e2"

    def test_italic_only_rule_is_valid(self):
        from dbt_charts.core.compile.models.chart.authored import (
            ConditionalRule,
        )

        rule = ConditionalRule.model_validate({"lt": 0, "font": {"style": "italic"}})
        assert rule.font is not None
        assert rule.font.style == "italic"

    def test_strikethrough_rule_is_valid(self):
        from dbt_charts.core.compile.models.chart.authored import (
            ConditionalRule,
        )

        rule = ConditionalRule.model_validate(
            {"lt": 0, "font": {"decoration": "line-through"}}
        )
        assert rule.font is not None
        assert rule.font.decoration == "line-through"

    def test_flat_font_weight_is_rejected(self):
        from dbt_charts.core.compile.models.chart.authored import (
            ConditionalRule,
        )

        with pytest.raises(ValidationError):
            ConditionalRule.model_validate({"lt": 0, "font_weight": "bold"})

    def test_flat_color_is_rejected(self):
        from dbt_charts.core.compile.models.chart.authored import (
            ConditionalRule,
        )

        with pytest.raises(ValidationError):
            ConditionalRule.model_validate({"lt": 0, "color": "#991b1b"})

    def test_no_style_override_still_rejected(self):
        from dbt_charts.core.compile.models.chart.authored import (
            ConditionalRule,
        )

        with pytest.raises(ValidationError):
            ConditionalRule.model_validate({"lt": 0})

    def test_rule_rejects_invalid_font_weight(self):
        from dbt_charts.core.compile.models.chart.authored import (
            ConditionalRule,
        )

        for bad in ("italic", "extra-bold", "250"):
            with pytest.raises(ValidationError):
                ConditionalRule.model_validate({"eq": "x", "font": {"weight": bad}})

    def test_empty_font_block_is_rejected(self):
        """font: {} carries no render-effective fields — must be rejected."""
        from dbt_charts.core.compile.models.chart.authored import (
            ConditionalRule,
        )

        with pytest.raises(ValidationError, match="at least one style override"):
            ConditionalRule.model_validate({"lt": 0, "font": {}})

    def test_font_with_only_non_cf_fields_is_rejected(self):
        """font.size / font.family are not conditional-formatting fields — not enough alone."""
        from dbt_charts.core.compile.models.chart.authored import (
            ConditionalRule,
        )

        with pytest.raises(ValidationError, match="at least one style override"):
            ConditionalRule.model_validate({"lt": 0, "font": {"family": "serif"}})

        with pytest.raises(ValidationError, match="at least one style override"):
            ConditionalRule.model_validate({"lt": 0, "font": {"size": 20}})
