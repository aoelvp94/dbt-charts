"""Theme-stage style classes: geoshape (choropleth) chart family."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from dbt_charts.core.compile.models.markers import (
    InheritSlot,
    SkipInheritSlots,  # noqa: F401  # pyright: ignore[reportUnusedImport] — required in module globals for model_rebuild() to resolve inherited base-class annotations
)
from dbt_charts.core.compile.models.style.theme._chart_base import (
    _GeoChartStyle,
)
from dbt_charts.core.compile.models.style.theme.marks import (
    GeoshapeMarkStyle,
)


class GeoshapeChartMarksStyle(BaseModel):
    """Geoshape-family mark overrides."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    geoshape: GeoshapeMarkStyle = Field(
        default_factory=GeoshapeMarkStyle,
        description="Geoshape mark overrides; inherits from global.",
    )


class GeoshapeChartStyle(_GeoChartStyle):
    """Geoshape (choropleth) chart style."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    marks: Annotated[
        GeoshapeChartMarksStyle, InheritSlot(from_path="Style.charts.marks")
    ] = Field(
        default_factory=GeoshapeChartMarksStyle,
        description="Geoshape-family mark overrides.",
    )
