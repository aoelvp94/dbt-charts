"""Chart sort and donut center total annotations."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from dbt_charts.core.compile.models.markers import DisplayText


class ChartSort(BaseModel):
    """Chart-level sort configuration for categorical axes."""

    model_config = ConfigDict(extra="forbid")

    by: str = Field(description="Column name to sort by.")
    order: Literal["asc", "desc"] = Field(
        default="asc", description="Sort direction (asc or desc)."
    )


class ChartTotal(BaseModel):
    """Donut center total: auto-rendered sum at the center of a donut, with author override."""

    model_config = ConfigDict(extra="forbid")

    visible: bool = Field(
        default=True,
        description=(
            "Whether to render the donut center total. Defaults True; set False to "
            "suppress the auto-rendered center on donuts whose theta values aren't a "
            "meaningful sum (e.g. pre-aggregated percentage shares)."
        ),
    )
    label: Annotated[str | None, DisplayText()] = Field(
        default=None, description="Caption text displayed below the center total value."
    )
