"""Stateless view of compile-time schema constants for authoring agents."""

from __future__ import annotations

import typing

from pydantic import BaseModel, ConfigDict

from dbt_charts.core.compile.config import user_facing_theme_names
from dbt_charts.core.compile.models.chart.authored import (
    _INTERNAL_CHART_TYPES,
    AUTHORED_CHART_TYPE_TAGS,
    CHART_TYPE_DISPLAY,
    ChartType,
)
from dbt_charts.core.compile.models.variable.authored import VariableInputType


class ChartTypeDisplay(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    icon: str


class SchemaHints(BaseModel):
    model_config = ConfigDict(frozen=True)

    chart_types: list[str]
    input_types: list[str]
    theme_names: list[str]
    chart_type_display: dict[str, ChartTypeDisplay]


def schema_hints() -> SchemaHints:
    """Return compile-time schema constants for Dataface authoring agents.

    Takes no arguments and reads no process state. Two consecutive calls
    return equal results.
    """
    internal_values = {t.value for t in _INTERNAL_CHART_TYPES}
    chart_type_by_value = {t.value: t for t in ChartType}
    public_tags = [t for t in AUTHORED_CHART_TYPE_TAGS if t not in internal_values]
    return SchemaHints(
        chart_types=public_tags,
        input_types=list(typing.get_args(VariableInputType)),
        theme_names=user_facing_theme_names(),
        chart_type_display={
            tag: ChartTypeDisplay(
                label=CHART_TYPE_DISPLAY[chart_type]["label"],
                icon=CHART_TYPE_DISPLAY[chart_type]["icon"],
            )
            for tag in public_tags
            if (chart_type := chart_type_by_value.get(tag)) is not None
            and chart_type in CHART_TYPE_DISPLAY
        },
    )
