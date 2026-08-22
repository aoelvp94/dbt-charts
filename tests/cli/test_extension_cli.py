"""Smoke tests for dct init code|cursor|vscode extension dispatch.

IDE-installer smoke depth: assert arg validation + dispatch only.
No real IDE binary, network call, or warehouse connection is reached.
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from dbt_charts.cli.commands import extension
from dbt_charts.cli.main import app

runner = CliRunner()

_PATCH_TARGET = "dbt_charts.cli.commands.extension.install_extension"


def test_init_code_dispatches_to_install_extension() -> None:
    with patch(_PATCH_TARGET, return_value=0) as mock_install:
        result = runner.invoke(app, ["init", "code"], catch_exceptions=False)
    assert result.exit_code == 0
    mock_install.assert_called_once()
    editor_arg = mock_install.call_args[0][0]
    assert editor_arg == "code"


def test_init_cursor_dispatches_with_cursor_target() -> None:
    with patch(_PATCH_TARGET, return_value=0) as mock_install:
        result = runner.invoke(app, ["init", "cursor"], catch_exceptions=False)
    assert result.exit_code == 0
    mock_install.assert_called_once()
    editor_arg = mock_install.call_args[0][0]
    assert editor_arg == "cursor"


def test_init_vscode_aliases_to_code() -> None:
    # `dct init vscode` is an alias for `dct init code` (init_vscode in main.py).
    # It must dispatch with editor='code', not 'vscode'. Renaming the alias or
    # changing the dispatch target surfaces a loud failure here.
    with patch(_PATCH_TARGET, return_value=0) as mock_install:
        result = runner.invoke(app, ["init", "vscode"], catch_exceptions=False)
    assert result.exit_code == 0
    mock_install.assert_called_once()
    editor_arg = mock_install.call_args[0][0]
    assert editor_arg == "code", (
        "dct init vscode (init_vscode) must dispatch with editor='code', not 'vscode'"
    )


def test_install_extension_downloads_from_public_gcs_bucket(tmp_path: Path) -> None:
    """install_extension must fetch the VSIX from the public GCS bucket — no
    `gh` CLI, no GitHub auth, no private-repo release lookup."""
    fake_editor_bin = str(tmp_path / "code")
    Path(fake_editor_bin).write_text("", encoding="utf-8")
    fake_vsix_bytes = b"PK\x03\x04 fake-vsix-payload"

    captured_urls: list[str] = []

    def fake_urlopen(url, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        captured_urls.append(url)
        return io.BytesIO(fake_vsix_bytes)

    install_calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        install_calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    emitted: list[str] = []

    def _which(name: str) -> str | None:
        return fake_editor_bin if name == "code" else None

    with (
        patch("dbt_charts.cli.commands.extension.shutil.which", side_effect=_which),
        patch(
            "dbt_charts.cli.commands.extension.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ),
        patch("dbt_charts.cli.commands.extension.subprocess.run", side_effect=fake_run),
    ):
        rc = extension.install_extension("code", emit=emitted.append)

    assert rc == 0, f"emitted={emitted}"
    assert captured_urls == [
        "https://storage.googleapis.com/dataface-downloads/dataface-latest.vsix"
    ]
    assert len(install_calls) == 1
    assert install_calls[0][0] == fake_editor_bin
    assert "--install-extension" in install_calls[0]
    # No `gh` subprocess invocation should ever happen now — only the editor.
    for cmd in install_calls:
        assert Path(cmd[0]).name != "gh", cmd


def test_install_extension_no_longer_requires_gh(tmp_path: Path) -> None:
    """Even when `gh` is absent from PATH, install_extension must succeed."""
    fake_editor_bin = str(tmp_path / "cursor")
    Path(fake_editor_bin).write_text("", encoding="utf-8")

    def _which(name: str) -> str | None:
        # `gh` is deliberately missing; only `cursor` resolves.
        return fake_editor_bin if name == "cursor" else None

    def fake_urlopen(_url, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return io.BytesIO(b"PK\x03\x04")

    with (
        patch("dbt_charts.cli.commands.extension.shutil.which", side_effect=_which),
        patch(
            "dbt_charts.cli.commands.extension.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ),
        patch(
            "dbt_charts.cli.commands.extension.subprocess.run",
            return_value=subprocess.CompletedProcess(["cursor"], 0, "", ""),
        ),
    ):
        rc = extension.install_extension("cursor", emit=MagicMock())

    assert rc == 0
