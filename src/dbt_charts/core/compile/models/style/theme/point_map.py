"""Theme-stage style classes: point map chart family."""

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
    PointMarkStyle,
)


class PointMapChartMarksStyle(BaseModel):
    """Point map-family mark overrides."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    point: PointMarkStyle = Field(
        default_factory=PointMarkStyle,
        description="Point mark overrides; inherits from global.",
    )


class PointMapChartStyle(_GeoChartStyle):
    """Point map chart style."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    marks: Annotated[
        PointMapChartMarksStyle, InheritSlot(from_path="Style.charts.marks")
    ] = Field(
        default_factory=PointMapChartMarksStyle,
        description="Point-map-family mark overrides.",
    )
