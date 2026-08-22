"""Tests for the max_rows / max_result_bytes ExecutionConfig fields.

Mirrors TestExecutionConfigField in test_query_duration_cap.py: shipped
default is a positive int from default_config.yml, and the field rejects
non-positive overrides.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.config import get_execution_config
from dbt_charts.core.compile.models.config import ExecutionConfig

_VALID_BASE = {
    "max_workers": 4,
    "max_query_duration_seconds": 120,
    "max_glob_file_count": 1000,
    "max_rows": 1000000,
    "max_result_bytes": 52428800,
    "dialect_aliases": {},
}


class TestMaxRowsField:
    def test_shipped_default_is_positive_int(self) -> None:
        cfg = get_execution_config()
        assert isinstance(cfg.max_rows, int)
        assert cfg.max_rows > 0

    def test_zero_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="greater than 0"):
            ExecutionConfig.model_validate({**_VALID_BASE, "max_rows": 0})

    def test_negative_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="greater than 0"):
            ExecutionConfig.model_validate({**_VALID_BASE, "max_rows": -1})


class TestMaxResultBytesField:
    def test_shipped_default_is_positive_int(self) -> None:
        cfg = get_execution_config()
        assert isinstance(cfg.max_result_bytes, int)
        assert cfg.max_result_bytes > 0

    def test_zero_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="greater than 0"):
            ExecutionConfig.model_validate({**_VALID_BASE, "max_result_bytes": 0})

    def test_negative_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="greater than 0"):
            ExecutionConfig.model_validate({**_VALID_BASE, "max_result_bytes": -1})
