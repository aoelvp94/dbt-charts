"""Invariant: `dct mcp serve` delegates to a commands/ module like every other verb."""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


def test_serve_command_routes_to_run_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """serve_command builds a FilesystemProject + cache and hands both to run_server."""
    from dbt_charts.cli.commands.mcp import serve_command
    from dbt_charts.cli.filesystem_project import FilesystemProject

    (tmp_path / "dbt_charts.yml").write_text("# project marker\n")
    monkeypatch.chdir(tmp_path)
    sentinel_cache = object()

    @contextmanager
    def fake_cache_ctx(
        project: object, *, no_cache: bool, cache_path: Path | None
    ) -> Generator[object]:
        yield sentinel_cache

    fake_run_server = AsyncMock()

    with (
        patch(
            "dbt_charts.agent_api.cache.project_cache_ctx", side_effect=fake_cache_ctx
        ),
        patch("dbt_charts.ai.mcp.run_server", fake_run_server),
    ):
        # Explicit --project-dir: @with_project resolves it outright (no marker
        # walk-up needed), matching every other with_project verb's contract.
        serve_command(project_dir=tmp_path)

    fake_run_server.assert_awaited_once()
    assert fake_run_server.await_args is not None
    called_project, called_cache = fake_run_server.await_args.args
    assert isinstance(called_project, FilesystemProject)
    assert called_cache is sentinel_cache
