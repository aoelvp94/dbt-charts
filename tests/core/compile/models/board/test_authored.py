"""Tests for the retired `chart:` reference-form guard on layout items.

`_reject_chartref_dict` recognizes a pre-0.4.0 layout item shape
(`- chart: name / width: N / description: ...`) and raises a clear,
actionable message instead of the generic "Unknown field 'chart'" a bare
extra-forbidden rejection would produce. The guard matches on key set
(`v.keys() <= _CHARTREF_KEYS`), so it must recognize the shape under either
spelling of the non-rendering metadata field -- `description:` (how the
retired form was actually authored) and `notes:` (what a board mid-migration,
or written by someone copying current field names onto old structure, would
use instead).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.models.board.authored import AuthoredBoard


def test_chartref_form_with_description_raises_removed_form_message() -> None:
    raw = {"rows": [{"chart": "revenue", "width": 6, "description": "Old notes"}]}
    with pytest.raises(ValidationError, match="removed `chart:` reference form"):
        AuthoredBoard.model_validate(raw)


def test_chartref_form_with_notes_raises_removed_form_message() -> None:
    """Regression: before `notes` was added to `_CHARTREF_KEYS`, this shape fell
    through to a confusing "Unknown field 'chart'. Did you mean 'charts'?"
    instead of the clear removed-form message."""
    raw = {"rows": [{"chart": "revenue", "width": 6, "notes": "New notes"}]}
    with pytest.raises(ValidationError, match="removed `chart:` reference form"):
        AuthoredBoard.model_validate(raw)
