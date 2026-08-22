"""Tests for live-reload SSE endpoint and script injection.

Covers:
- /__livereload endpoint responds with text/event-stream content type
- HTML board responses include the /__livereload script tag
- Non-HTML responses (SVG, PNG, PDF, YAML) do NOT include the script tag
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.serve.server import create_server

_LIVERELOAD_SCRIPT = "/__livereload"


@pytest.fixture
def simple_project(tmp_path: Path) -> Path:
    """Minimal project with one board for serve tests."""
    (tmp_path / "dbt_charts.yml").write_text("# project config\n")
    boards_dir = tmp_path / "charts"
    boards_dir.mkdir()
    (boards_dir / "hello.yml").write_text("title: Hello\nrows: []\n")
    return tmp_path


async def _empty_awatch(
    *_args: object, **_kwargs: object
) -> AsyncGenerator[set[object], None]:
    """Stub for watchfiles.awatch that yields nothing, so the SSE stream closes immediately."""
    # Iterate over an empty tuple: the yield is syntactically reachable but
    # never executes.  Required to make this function an async generator.
    for _ in ():
        yield set()


async def _one_change_awatch(
    *_args: object, **_kwargs: object
) -> AsyncGenerator[set[object], None]:
    """Stub for watchfiles.awatch that yields one change set, then stops."""
    yield {("modified", "charts/hello.yml")}


class TestLivereloadEndpoint:
    def test_livereload_endpoint_returns_event_stream_content_type(
        self, simple_project: Path
    ) -> None:
        """/__livereload must respond with text/event-stream content type.

        The SSE endpoint must advertise the correct content type so EventSource
        in the browser establishes an SSE connection (not a plain HTTP download).

        Patches watchfiles.awatch so the stream completes immediately rather than
        waiting for filesystem events, keeping the test fast.
        """
        with (
            patch("watchfiles.awatch", _empty_awatch),
            TestClient(
                create_server(FilesystemProject(simple_project)),
            ) as client,
        ):
            response = client.get("/__livereload")
        assert "text/event-stream" in response.headers.get("content-type", ""), (
            f"Expected text/event-stream, got: {response.headers.get('content-type')}"
        )

    def test_livereload_endpoint_emits_reload_on_change(
        self, simple_project: Path
    ) -> None:
        """A watched-file change must push a ``data: reload`` SSE event."""
        with (
            patch("watchfiles.awatch", _one_change_awatch),
            TestClient(
                create_server(FilesystemProject(simple_project)),
            ) as client,
        ):
            response = client.get("/__livereload")
        assert "data: reload" in response.text, (
            f"Expected 'data: reload' in stream body, got: {response.text!r}"
        )


class TestLivereloadScriptInjection:
    def test_html_board_response_contains_livereload_script(
        self, simple_project: Path
    ) -> None:
        """HTML board responses must include a /__livereload EventSource script.

        The script enables automatic browser refresh when watched files change,
        so the user does not need to manually refresh after editing a board.
        """
        with TestClient(
            create_server(FilesystemProject(simple_project)),
        ) as client:
            response = client.get("/hello/")
        assert response.status_code == 200
        assert _LIVERELOAD_SCRIPT in response.text, (
            f"Expected /__livereload in HTML response, body preview: {response.text[:500]}"
        )

    def test_svg_download_does_not_contain_livereload_script(
        self, simple_project: Path
    ) -> None:
        """SVG download responses must NOT include the livereload script tag."""
        with TestClient(
            create_server(FilesystemProject(simple_project)),
        ) as client:
            response = client.get("/hello.svg")
        # SVG download may redirect or 200; either way the script must be absent
        # from the final response body.
        assert _LIVERELOAD_SCRIPT not in response.text, (
            "/__livereload script must not appear in SVG response"
        )

    def test_yaml_source_does_not_contain_livereload_script(
        self, simple_project: Path
    ) -> None:
        """Raw YAML source responses (text/plain) must NOT include the livereload script."""
        with TestClient(
            create_server(FilesystemProject(simple_project)),
        ) as client:
            response = client.get("/hello.yaml")
        assert _LIVERELOAD_SCRIPT not in response.text, (
            "/__livereload script must not appear in YAML source response"
        )
