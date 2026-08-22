"""The authored column surface.

Count derivation is not tested here -- it is no longer a property of this
model. The renderer decides count and width together from the measure
(``dbt-charts/tests/core/test_column_packer.py`` for the arithmetic,
``test_prose_columns.py`` for the delivered line length).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.models.style.theme import TextColumnStyle


def test_width_field_rejected():
    """An authored column width is a pixel measure; only max_chars is offered."""
    with pytest.raises(ValidationError):
        TextColumnStyle(width=200)  # type: ignore[call-arg]
