"""Tests for compile/models/style/authored/__init__.py's ChartStylePatch."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.models.style.authored import ChartStylePatch


@pytest.mark.parametrize("sizing_key", ["aspect_ratio", "min_height", "max_height"])
def test_spark_bar_sizing_keys_rejected_outright(sizing_key: str) -> None:
    """spark_bar always uses fixed sizing — aspect_ratio/min_height/max_height
    have no effect regardless of where they're authored, so nesting them under
    style.spark_bar.* must be rejected outright, not redirected to the top of
    style: (which is an equally silent no-op for this family)."""
    with pytest.raises(ValidationError, match="not supported on spark_bar"):
        ChartStylePatch(spark_bar={sizing_key: 2.0})
