"""Regression test: /inspect/{path} must not escape the project root.

_handle_inspect_route builds custom_relpath = f"charts/inspect/{template_name}.yml"
straight from the untrusted URL segment and hands it to project.exists /
project.read_text with no ".." rejection. A traversal-shaped template_name must
be rejected, not read a real file above the project root.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.serve.server import _handle_inspect_route


def test_inspect_route_rejects_path_traversal_template_name(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """A ".."-laden template_name must not read a file above the project root.

    Fails today because project.exists()/project.read_text() (server.py:712,745)
    have no containment check — the traversed custom_relpath resolves to a real
    file above the project root and its content is forwarded to
    render_inspect_dashboard.
    """
    project_root = tmp_path / "project"
    # charts/inspect/ must physically exist — the OS resolves ".." by walking
    # through real intermediate directories, not by string normalization.
    (project_root / "charts" / "inspect").mkdir(parents=True)
    secret = tmp_path / "secret.yml"
    secret.write_text("SECRET OUTSIDE ROOT\n")

    project = local_project(project_root)

    captured: list[str] = []

    def fake_render(template_yaml: str, *_args: object, **_kwargs: object) -> str:
        captured.append(template_yaml)
        return "<html>ok</html>"

    with patch(
        "dbt_charts.core.serve.server.render_inspect_dashboard",
        side_effect=fake_render,
    ):
        response = _handle_inspect_route(
            template_name="../../../secret",
            variables={},
            project=project,
        )

    assert not captured, (
        "render_inspect_dashboard must not be called with content read from "
        f"above the project root, got {captured!r}"
    )
    assert response.status_code == 404, (
        f"Expected traversal to be rejected with 404, got {response.status_code}"
    )
