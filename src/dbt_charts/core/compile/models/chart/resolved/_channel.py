"""Resolved style channel data type.

This module holds only the frozen dataclass that represents a single
resolved style channel — the OUTPUT of the channel parsing ENGINE in
``dbt_charts.core.compile.resolve.chart.channel``.  Placing the data type here lets the
render layer import the resolved IR without pulling in compile internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from dbt_charts.core.compile.models.chart.authored import ConditionalRule
from dbt_charts.core.compile.models.primitives import ResolvedScaleTarget


@dataclass(frozen=True)
class ResolvedStyleChannel:
    channel: str
    mode: Literal["series", "literal", "gradient", "conditional"]
    data_field: str = ""
    literal_value: Any = None
    scale: ResolvedScaleTarget | None = None
    rules: tuple[ConditionalRule, ...] = ()
    # When mode == "conditional", optional gradient fallback used when no
    # threshold rule matches.  Enables Looker-style "scale with rule override"
    # where threshold rules take priority and scale shows through otherwise.
    fallback_scale: ResolvedScaleTarget | None = None
