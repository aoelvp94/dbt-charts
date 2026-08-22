"""BoardRecording captures a resolved board's rows for later replay."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile.compiler import compile as compile_board
from dbt_charts.core.diagnostics.base import DbtChartsError
from dbt_charts.core.execute.adapters import build_adapter_registry
from dbt_charts.core.execute.executor import Executor
from dbt_charts.core.execute.recording import (
    BoardRecording,
    load_board_recording,
    record_board,
)
from dbt_charts.core.render.board_resolve import build_resolved_board

_YAML = """
title: Recording Board
queries:
  channel_mix:
    columns: [month, signups]
    values:
      - ["2026-01-01", 90]
      - ["2026-02-01", 105]
charts:
  mix:
    query: channel_mix
    type: bar
    x: month
    y: signups
rows:
  - mix
"""


def _build_executor(tmp_path: Path) -> tuple[object, Executor, dict[str, object]]:
    result = compile_board(_YAML)
    assert result.success, result.errors
    assert result.board is not None
    project = FilesystemProject(tmp_path)
    executor = Executor(
        result.board,
        build_adapter_registry(project),
        query_registry=result.query_registry,
    )
    variables: dict[str, object] = {}
    resolved, _ = build_resolved_board(result.board, executor, variables)
    return resolved, executor, variables


def test_record_board_captures_rows_by_query(tmp_path: Path) -> None:
    resolved, executor, variables = _build_executor(tmp_path)

    recording = record_board(resolved, executor, variables)

    assert recording.rows_by_query["channel_mix"] == [
        {"month": "2026-01-01", "signups": 90},
        {"month": "2026-02-01", "signups": 105},
    ]


def test_record_board_captures_variables_and_timestamp(tmp_path: Path) -> None:
    resolved, executor, variables = _build_executor(tmp_path)

    before = datetime.now(timezone.utc)
    recording = record_board(resolved, executor, variables)
    after = datetime.now(timezone.utc)

    assert recording.variables == variables
    assert before <= recording.recorded_at <= after


def test_record_board_provenance_empty_for_non_dbt_queries(tmp_path: Path) -> None:
    resolved, executor, variables = _build_executor(tmp_path)

    recording = record_board(resolved, executor, variables)

    assert recording.provenance == {}


def test_board_recording_round_trips_through_json(tmp_path: Path) -> None:
    resolved, executor, variables = _build_executor(tmp_path)
    recording = record_board(resolved, executor, variables)

    reloaded = load_board_recording(recording.model_dump_json().encode())

    assert reloaded == recording


def test_load_board_recording_raises_on_malformed_json() -> None:
    with pytest.raises(DbtChartsError) as exc_info:
        load_board_recording(b"{not json")

    assert exc_info.value.code is not None
    assert exc_info.value.code.code == "ERR-BOARD-RECORDING-INVALID"


def test_load_board_recording_raises_on_schema_mismatch() -> None:
    with pytest.raises(DbtChartsError):
        load_board_recording(b'{"unexpected_field": true}')


def test_board_recording_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        BoardRecording(
            recorded_at=datetime.now(timezone.utc),
            variables={},
            rows_by_query={},
            provenance={},
            extra_field="nope",  # type: ignore[call-arg]
        )
