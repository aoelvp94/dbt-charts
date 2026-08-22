"""Regression tests: style compiled models reject unknown fields via extra="forbid"."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.models.primitives import SpacingValues
from dbt_charts.core.compile.models.style.theme import PaddingStyle


@pytest.mark.parametrize(
    ("cls", "kwargs"),
    [
        (SpacingValues, {}),
        (PaddingStyle, {"left": 0, "right": 0, "top": 0, "bottom": 0}),
    ],
)
def test_extra_field_rejected(cls: type, kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        cls(**kwargs, bogus=True)  # type: ignore[call-arg]
