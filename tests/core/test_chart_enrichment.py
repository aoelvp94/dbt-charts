"""Tests for chart enrichment behavior."""

import pytest

from dbt_charts.core.compile.resolve.chart.enrich import (
    ColumnProfile,
    _pick_scale,
)

# Chart types where zero anchoring is optional (smart-auto heuristic applies).
_OPTIONAL_ZERO_TYPES = ("line", "scatter", "area")


class TestSmartAutoZero:
    """Smart auto-zero heuristic: extend to 0 when data_min/data_max <= 0.25.

    Only applies to chart types where zero is optional (line, scatter).
    """

    @pytest.mark.parametrize(
        ("data_min", "data_max", "expected_zero"),
        [
            # ratio = 0.25 (at threshold) → extend to 0 (zero: None, let VL default)
            (120, 480, None),
            # ratio ≈ 0.0125 (clearly close to 0) → extend to 0
            (50, 4000, None),
            # ratio ≈ 0.41 (above threshold) → fit-to-data (zero: False)
            (75000, 183000, False),
            # ratio ≈ 0.89 (very tight) → fit-to-data (zero: False)
            (7300, 8200, False),
            # ratio ≈ 0.71 (above threshold) → fit-to-data (zero: False)
            (0.65, 0.92, False),
        ],
    )
    def test_line_chart_auto_zero_heuristic(
        self, data_min: float, data_max: float, expected_zero: bool | None
    ) -> None:
        """Line chart with auto zero uses ratio threshold to decide domain."""
        profile = ColumnProfile(min_val=data_min, max_val=data_max)
        result = _pick_scale(profile, chart_type="line")
        if expected_zero is None:
            # extend to zero: either no override or zero=True
            assert result is None or result.get("zero") is not False
        else:
            assert result is not None
            assert result.get("zero") is False

    @pytest.mark.parametrize("chart_type", _OPTIONAL_ZERO_TYPES)
    def test_optional_zero_chart_types_apply_heuristic(self, chart_type: str) -> None:
        """Heuristic applies consistently to all optional-zero chart types."""
        # (75k, 183k) ratio=0.41 — should be fit-to-data on optional-zero types
        profile = ColumnProfile(min_val=75000, max_val=183000)
        result = _pick_scale(profile, chart_type=chart_type)
        assert result is not None
        assert result.get("zero") is False

    def test_bar_skips_optional_zero_branch_for_mid_range(self) -> None:
        """Bar skips the optional-zero branch for mid-range data (ratio=0.41).

        Bar falls through to the non-optional-zero path (always zero=True for
        all-positive data) to avoid truncated bars — a known misleading chart
        pattern.
        """
        # (75k, 183k) ratio=0.41 — bar is not optional-zero, so always zero:True.
        profile = ColumnProfile(min_val=75000, max_val=183000)
        result = _pick_scale(profile, chart_type="bar")
        assert result is not None
        assert result.get("zero") is True


class TestQueryResultColumnDescriptions:
    def test_stores_descriptions(self):
        from dbt_charts.core.execute.adapters.base import QueryResult

        descs = {"a": ("a", "INTEGER", None, None, None, None, None)}
        result = QueryResult(data=[{"a": 1}], column_descriptions=descs)
        assert result.column_descriptions == descs

    def test_defaults_none(self):
        from dbt_charts.core.execute.adapters.base import QueryResult

        result = QueryResult(data=[{"a": 1}])
        assert result.column_descriptions is None

    def test_backward_compatible(self):
        from dbt_charts.core.execute.adapters.base import QueryResult

        result = QueryResult(data=[{"x": 1}], columns=["x"], error=None)
        assert result.data == [{"x": 1}]
        assert result.column_descriptions is None
        assert result.is_success
