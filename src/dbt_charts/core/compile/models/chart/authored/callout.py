"""Authored callout chart — static message, no chrome, no query."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dbt_charts.core.compile.models.style.authored import CalloutChartStylePatch


class CalloutChart(BaseModel):
    """Static callout/message chart. Minimal — no chrome, no styling, no query."""

    model_config = ConfigDict(extra="forbid")

    type: Annotated[Literal["callout"], Field(description="Callout chart type.")]
    message: Annotated[str, Field(description="Static message content.")]
    title: Annotated[
        str | None,
        Field(
            default=None, description="Optional chart title shown above the message."
        ),
    ] = None
    style: Annotated[
        CalloutChartStylePatch | None,
        Field(default=None, description="Chart-local style overrides (tone)."),
    ] = None
    warnings_ignore: Annotated[
        list[str] | None,
        Field(
            default=None,
            description="Codes of render warnings to suppress for this chart.",
        ),
    ] = None

    @model_validator(mode="before")
    @classmethod
    def _reject_tone_at_chart_root(cls, data: Any) -> Any:
        if isinstance(data, dict) and "tone" in data:
            raise ValueError(
                "'tone:' has moved from the callout chart root into the style namespace.\n"
                "Use style.tone instead:\n\n"
                "  style:\n"
                "    tone: negative\n"
            )
        return data
