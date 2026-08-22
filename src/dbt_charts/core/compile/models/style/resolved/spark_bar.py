"""SparkBar family resolved style slice."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from dbt_charts.core.compile.models.primitives import ResolvedFontStyle
from dbt_charts.core.compile.models.style.theme import SparkBarChartStyle


class ResolvedSparkBarStyle(BaseModel):
    """SparkBar family style slice projected from the style cascade."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    spark_bar: SparkBarChartStyle | None = Field(
        default=None,
        description=(
            "Resolved spark bar style (geometry, font, border) from the cascade. "
            "Not yet populated; value is set during resolution."
        ),
    )
    title_font: ResolvedFontStyle | None = Field(
        default=None,
        description="Baked title font (size/weight/family/…) from the width tier.",
    )


__all__ = ["ResolvedSparkBarStyle"]
