"""Callout family resolved style slice."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from dbt_charts.core.compile.models.primitives import (
    BorderStyle,
    ResolvedFontStyle,
    ToneLiteral,
)
from dbt_charts.core.compile.models.style.theme import PaddingStyle


class ResolvedCalloutElementStyle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    font: ResolvedFontStyle
    y_offset: float


class ResolvedCalloutStyle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    preferred_width: float
    tone: ToneLiteral
    background: str
    border: BorderStyle
    padding: PaddingStyle
    section_gap: float
    bold_font_weight: str
    title: ResolvedCalloutElementStyle
    message: ResolvedCalloutElementStyle


__all__ = ["ResolvedCalloutElementStyle", "ResolvedCalloutStyle"]
