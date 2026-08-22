"""Tests for the data alias typo lint.

Covers:
- validate_data_aliases() passes for valid aliases
- validate_data_aliases() errors with did-you-mean hint for typo'd aliases
- validate_data_aliases() is a no-op when no /data/ aliases are present
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from dbt_charts.agent_api.data_paths import validate_data_aliases
from dbt_charts.cli.filesystem_project import FilesystemProject


class TestValidateDataAliasesNoop:
    """No /data/ aliases → always passes."""

    def test_empty_aliases(self) -> None:
        errors = validate_data_aliases([], source_names=frozenset({"wh"}))
        assert errors == []

    def test_non_data_aliases_ignored(self) -> None:
        errors = validate_data_aliases(
            ["/reports/old-sales/", "/legacy/sales/"],
            source_names=frozenset({"wh"}),
        )
        assert errors == []


class TestValidateDataAliasesSourceCheck:
    """/data/ aliases check that the source segment is a configured source."""

    def test_valid_source_passes(self) -> None:
        errors = validate_data_aliases(
            ["/data/wh/"],
            source_names=frozenset({"wh"}),
        )
        assert errors == []

    def test_unknown_source_errors(self) -> None:
        errors = validate_data_aliases(
            ["/data/no_such_source/"],
            source_names=frozenset({"wh", "prod"}),
        )
        assert len(errors) == 1
        msg = errors[0]
        assert "no_such_source" in msg
        # Should include available sources as a hint
        assert "wh" in msg or "prod" in msg

    def test_schema_only_alias_valid_source_passes(self) -> None:
        """/data/<source>/<schema>/ passes when source is known."""
        errors = validate_data_aliases(
            ["/data/wh/analytics/"],
            source_names=frozenset({"wh"}),
        )
        assert errors == []

    def test_unknown_source_in_deep_alias_errors(self) -> None:
        """Source check applies to full /data/<source>/<schema>/<table>/ URLs too."""
        errors = validate_data_aliases(
            ["/data/bad_src/analytics/orders/"],
            source_names=frozenset({"wh"}),
        )
        assert len(errors) == 1
        assert "bad_src" in errors[0]


# ---------------------------------------------------------------------------
# annotate_with_data_lint integration
# ---------------------------------------------------------------------------

_BOARD_NO_DATA_ALIAS = """\
title: Plain Board
queries:
  q:
    type: values
    rows:
      - {n: 1}
charts:
  t:
    query: q
    type: table
rows:
  - t
"""


class TestAnnotateWithDataLint:
    """annotate_with_data_lint adds data alias errors to ValidateResult list."""

    def test_no_data_alias_no_extra_errors(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        board = tmp_path / "charts" / "plain.yml"
        board.parent.mkdir()
        board.write_text(_BOARD_NO_DATA_ALIAS)

        from dbt_charts.agent_api.validate import annotate_with_data_lint, validate

        project = local_project(tmp_path)
        result = validate(board, project=project)
        assert result.success is True

        annotated = annotate_with_data_lint([result], project=project)

        assert len(annotated) == 1
        assert annotated[0].success is True
        assert annotated[0].errors == []

    def test_typo_data_alias_becomes_error(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """A board aliasing /data/<unknown_source>/... errors at validate time."""
        board = tmp_path / "charts" / "override.yml"
        board.parent.mkdir()
        board.write_text(
            """\
title: Override
aliases:
  - /data/no_such_src/analytics/orders/
queries:
  q:
    type: values
    rows:
      - {n: 1}
charts:
  t:
    query: q
    type: table
rows:
  - t
"""
        )
        from dbt_charts.agent_api.validate import annotate_with_data_lint, validate

        project = local_project(tmp_path)
        result = validate(board, project=project)
        assert result.success is True  # compile passes (alias is valid syntax)

        annotated = annotate_with_data_lint([result], project=project)

        assert len(annotated) == 1
        assert annotated[0].success is False
        assert any("no_such_src" in e.message for e in annotated[0].errors)


# ---------------------------------------------------------------------------
# annotate_with_data_lint — no DB connection asserted
# ---------------------------------------------------------------------------


class TestAnnotateNoDBConnection:
    """annotate_with_data_lint must not open any warehouse connection."""

    def test_validate_does_not_build_adapter_registry(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """annotate_with_data_lint must not build an adapter registry."""
        board = tmp_path / "charts" / "override.yml"
        board.parent.mkdir()
        board.write_text(
            """\
title: Override
aliases:
  - /data/no_such_src/analytics/orders/
queries:
  q:
    type: values
    rows:
      - {n: 1}
charts:
  t:
    query: q
    type: table
rows:
  - t
"""
        )
        from dbt_charts.agent_api.validate import annotate_with_data_lint, validate

        project = local_project(tmp_path)
        result = validate(board, project=project)

        # No adapter registry may be constructed during annotate_with_data_lint.
        # Patching the constructor itself catches every build path, regardless of
        # how build_adapter_registry is imported at the call site.
        with patch(
            "dbt_charts.core.execute.adapters.adapter_registry.AdapterRegistry.__init__",
            side_effect=AssertionError(
                "adapter_registry must not be built during validate"
            ),
        ):
            annotated = annotate_with_data_lint([result], project=project)

        assert len(annotated) == 1
        assert annotated[0].success is False
        assert any("no_such_src" in e.message for e in annotated[0].errors)


_BOARD_WITH_TYPO_DATA_ALIAS = """\
title: Typo Board
aliases:
  - /data/no_such_src/analytics/orders/
queries:
  q:
    type: values
    rows:
      - {n: 1}
charts:
  t:
    query: q
    type: table
rows:
  - t
"""


class TestDataLintParity:
    """Data alias typo lint runs on both CLI (project_session.validate_paths) and MCP
    (validate_board tool handler) surfaces.

    The two must agree: if a typo'd /data/ alias is an error on CLI, it is also
    an error through MCP validate_board.
    """

    def test_mcp_validate_board_reports_data_alias_typo(self, tmp_path: Path) -> None:
        """MCP validate_board reports data alias typos, just like dct validate."""
        board = tmp_path / "charts" / "typo.yml"
        board.parent.mkdir()
        board.write_text(_BOARD_WITH_TYPO_DATA_ALIAS)

        from dbt_charts.agent_api.project_session import ProjectSession
        from dbt_charts.ai.context import DbtChartsAIContext
        from dbt_charts.ai.tools import dispatch_tool_call

        with ProjectSession.open(tmp_path) as project_session:
            ctx = DbtChartsAIContext(project_session=project_session)
            result = dispatch_tool_call(
                "validate_board",
                {"path": str(board)},
                context=ctx,
            )

        assert result["success"] is False, (
            "MCP validate_board should report data alias typo as an error"
        )
        # At least one error should mention the unknown source name
        errors = result.get("errors", [])
        assert any(
            "no_such_src" in (e.get("message", "") if isinstance(e, dict) else str(e))
            for e in errors
        ), f"Expected 'no_such_src' in MCP error messages, got: {errors}"

    def test_cli_and_mcp_agree_on_data_alias_typo(self, tmp_path: Path) -> None:
        """CLI (project_session.validate) and MCP (_handle_validate) return the same error for
        a /data/ alias typo — parity test pins the contract."""
        board = tmp_path / "charts" / "typo.yml"
        board.parent.mkdir()
        board.write_text(_BOARD_WITH_TYPO_DATA_ALIAS)

        from dbt_charts.agent_api.project_session import ProjectSession
        from dbt_charts.ai.context import DbtChartsAIContext
        from dbt_charts.ai.tools import dispatch_tool_call

        with ProjectSession.open(tmp_path) as project_session:
            # CLI path: project_session.validate_paths uses annotate_with_data_lint
            cli_results = project_session.validate_paths([board])
            cli_result = cli_results[0]

            # MCP path: dispatch_tool_call → _handle_validate
            ctx = DbtChartsAIContext(project_session=project_session)
            mcp_result = dispatch_tool_call(
                "validate_board",
                {"path": str(board)},
                context=ctx,
            )

        assert cli_result.success is False, "CLI must report data alias typo"
        assert mcp_result["success"] is False, "MCP must report data alias typo"

        cli_has_typo_msg = any("no_such_src" in e.message for e in cli_result.errors)
        mcp_errors = mcp_result.get("errors", [])
        mcp_has_typo_msg = any(
            "no_such_src" in (e.get("message", "") if isinstance(e, dict) else str(e))
            for e in mcp_errors
        )
        assert cli_has_typo_msg, "CLI error should mention 'no_such_src'"
        assert mcp_has_typo_msg, (
            f"MCP error should mention 'no_such_src'; got: {mcp_errors}"
        )
