"""Tests for dbt_charts.agent_api.serve: startup composition for `dct serve`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from dbt_charts.agent_api.serve import ServeSetup, format_startup_failure, prepare_serve
from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.diagnostics import Diagnostic


@pytest.fixture
def project(tmp_path: Path) -> FilesystemProject:
    (tmp_path / "dbt_charts.yml").write_text("# project marker\n")
    return FilesystemProject(tmp_path)


class TestPrepareServe:
    def test_explicit_dialect_skips_inference(self, project: FilesystemProject) -> None:
        sentinel = object()
        with (
            patch("dbt_charts.core.serve.port.resolve_port", return_value=1234),
            patch("dbt_charts.core.project_roots.infer_dialect_from_dbt") as mock_infer,
            patch(
                "dbt_charts.core.serve.server.create_server",
                return_value=sentinel,
            ),
        ):
            result = prepare_serve(
                project,
                port=None,
                host="localhost",
                dialect="postgres",
                target=None,
                max_workers=None,
                no_cache=False,
                cache_path=None,
            )
        mock_infer.assert_not_called()
        assert isinstance(result, ServeSetup)
        assert result.dialect == "postgres"
        assert result.dialect_inferred is False
        assert result.app is sentinel
        assert result.port == 1234

    def test_infers_dialect_when_not_given(self, project: FilesystemProject) -> None:
        with (
            patch("dbt_charts.core.serve.port.resolve_port", return_value=1234),
            patch(
                "dbt_charts.core.project_roots.infer_dialect_from_dbt",
                return_value="bigquery",
            ),
            patch("dbt_charts.core.serve.server.create_server", return_value=object()),
        ):
            result = prepare_serve(
                project,
                port=None,
                host="localhost",
                dialect=None,
                target=None,
                max_workers=None,
                no_cache=False,
                cache_path=None,
            )
        assert isinstance(result, ServeSetup)
        assert result.dialect == "bigquery"
        assert result.dialect_inferred is True

    def test_no_dialect_inferred_falls_back_to_duckdb(
        self, project: FilesystemProject
    ) -> None:
        with (
            patch("dbt_charts.core.serve.port.resolve_port", return_value=1234),
            patch(
                "dbt_charts.core.project_roots.infer_dialect_from_dbt",
                return_value=None,
            ),
            patch("dbt_charts.core.serve.server.create_server", return_value=object()),
        ):
            result = prepare_serve(
                project,
                port=None,
                host="localhost",
                dialect=None,
                target=None,
                max_workers=None,
                no_cache=False,
                cache_path=None,
            )
        assert isinstance(result, ServeSetup)
        assert result.dialect == "duckdb"
        assert result.dialect_inferred is False

    def test_invalid_default_theme_env_returns_diagnostic(
        self, project: FilesystemProject, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DCT_DEFAULT_THEME", "nonexistent-theme-xyz")
        result = prepare_serve(
            project,
            port=None,
            host="localhost",
            dialect="duckdb",
            target=None,
            max_workers=None,
            no_cache=False,
            cache_path=None,
        )
        assert isinstance(result, Diagnostic)
        assert result.code == "ERR-INVALID-DEFAULT-THEME"

    def test_valid_default_theme_env_proceeds(
        self, project: FilesystemProject, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with (
            patch("dbt_charts.core.serve.port.resolve_port", return_value=1234),
            patch(
                "dbt_charts.core.project_roots.infer_dialect_from_dbt",
                return_value=None,
            ),
            patch("dbt_charts.core.serve.server.create_server", return_value=object()),
        ):
            monkeypatch.setenv("DCT_DEFAULT_THEME", "cream")
            result = prepare_serve(
                project,
                port=None,
                host="localhost",
                dialect="duckdb",
                target=None,
                max_workers=None,
                no_cache=False,
                cache_path=None,
            )
        assert isinstance(result, ServeSetup)

    def test_dataface_yml_validation_error_propagates_uncaught(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DCT_DEFAULT_THEME", raising=False)
        (tmp_path / "dbt_charts.yml").write_text("theme: cream\n", encoding="utf-8")
        project = FilesystemProject(tmp_path)
        with pytest.raises(ValidationError):
            prepare_serve(
                project,
                port=None,
                host="localhost",
                dialect="duckdb",
                target=None,
                max_workers=None,
                no_cache=False,
                cache_path=None,
            )


class TestFormatStartupFailure:
    def test_returns_startup_failed_diagnostic_with_detail(self) -> None:
        diagnostic = format_startup_failure(OSError("address already in use"))
        assert diagnostic.code == "ERR-STARTUP-FAILED"
        assert "address already in use" in str(diagnostic.model_dump())
