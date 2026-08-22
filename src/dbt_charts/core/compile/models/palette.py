"""Target Palette record model — unified palette shape.

The goal shape for all authored palette YAML files:
    {name, extends?, colors?, aliases?, description?}

Current status:
- tone/ family: already in this shape — round-trips correctly today.
- categorical/scaffold/sequential/diverging: still use legacy shapes
  (stops:, spine:, flat-key hex mapping). Migration pending.

No family/type discriminator. No subclasses.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

# Alias values: hex color string, another alias name, or 1-indexed slot ref (int).
PaletteAliasValue = str | int


class Palette(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    extends: str | None = None
    colors: list[str] | None = None
    aliases: dict[str, PaletteAliasValue] | None = None
    description: str | None = None
    # Authoring-aid / metadata fields; declared explicitly so extra="forbid"
    # doesn't reject them.
    family: str | None = None
    design_notes: str | None = None
    r8_validation: dict[str, Any] | None = None
