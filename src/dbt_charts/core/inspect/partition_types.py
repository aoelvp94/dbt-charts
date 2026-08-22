"""Typed warehouse partition metadata shared by inspect sources and agent API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

PartitionType = Literal[
    "time",
    "ingestion",
    "range",
    "clustering",
    "unpartitioned",
    "none",
]


class PartitionEntry(BaseModel):
    """One partition row from the warehouse."""

    partition_id: str
    row_count: int | None = None
    size_bytes: int | None = None
    last_modified: datetime | None = None


class TablePartitions(BaseModel):
    """Normalized partition metadata for a single table."""

    column: str | None = None
    type: PartitionType
    entries: list[PartitionEntry] = Field(
        default_factory=list, description="Individual partition values for this column."
    )
    # False means this adapter path cannot report partition metadata.
    supported: bool
