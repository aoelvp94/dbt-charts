"""Tests for the registered-view render pipeline (core API function).

Covers the extracted render_registered_view function:
- Returns None when no route matches.
- Returns RenderSuccess with HTML when a route matches and renders cleanly.
- Returns RenderError when the source is unknown (registry query fails).
- Links in rendered HTML carry the url_prefix when link_context is supplied.

These tests drive through the real registered-view expansion pipeline using a
DuckDB source. They confirm the same behaviour as the serve integration tests
but at the core-API level — no HTTP layer involved.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import duckdb
import pytest

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.project import Project
from dbt_charts.core.registered_views.render_pipeline import (
    RenderError,
    RenderSuccess,
    render_registered_view,
)


@pytest.fixture
def project_with_duckdb(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> Project:
    """Return a minimal project with a DuckDB source."""
    db_path = tmp_path / "wh.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("CREATE TABLE orders (id INTEGER, status VARCHAR)")
    conn.close()
    (tmp_path / "dbt_charts.yml").write_text(
        f"sources:\n  wh:\n    type: duckdb\n    path: '{db_path}'\n"
    )
    (tmp_path / "charts").mkdir()
    return local_project(tmp_path)


def _make_adapter_registry(project: Project) -> object:
    """Build a real adapter registry for the given project."""
    from dbt_charts.core.execute.adapters import build_adapter_registry

    return build_adapter_registry(
        project,
        read_only=False,
        allow_external_access_in_readonly=False,
        duckdb_config=None,
        profile_type="duckdb",
        target="dev",
    )


class TestRenderRegisteredViewNoMatch:
    def test_unknown_path_returns_none(self, project_with_duckdb: Project) -> None:
        """A path that matches no registered route returns None."""
        adapter_registry = _make_adapter_registry(project_with_duckdb)
        result = render_registered_view(
            request_path="/no/such/path/",
            project=project_with_duckdb,
            adapter_registry=adapter_registry,
            result_cache=None,
        )
        assert result is None


class TestRenderRegisteredViewSuccess:
    def test_data_root_returns_render_success(
        self, project_with_duckdb: Project
    ) -> None:
        """GET /data/ with a real source produces a RenderSuccess with HTML."""
        adapter_registry = _make_adapter_registry(project_with_duckdb)
        result = render_registered_view(
            request_path="/data/",
            project=project_with_duckdb,
            adapter_registry=adapter_registry,
            result_cache=None,
        )
        assert result is not None
        assert isinstance(result, RenderSuccess)
        assert len(result.html) > 0
        assert "wh" in result.html

    def test_data_source_returns_render_success(
        self, project_with_duckdb: Project
    ) -> None:
        """GET /data/wh/ with a known source produces a RenderSuccess with HTML."""
        adapter_registry = _make_adapter_registry(project_with_duckdb)
        result = render_registered_view(
            request_path="/data/wh/",
            project=project_with_duckdb,
            adapter_registry=adapter_registry,
            result_cache=None,
        )
        assert result is not None
        assert isinstance(result, RenderSuccess)
        assert len(result.html) > 0


class TestRenderRegisteredViewLinkContext:
    def test_root_applied_to_data_links(self, project_with_duckdb: Project) -> None:
        """Links inside a registered-view page carry the root prefix when provided.

        /data/ source links are ``/data/<source>/`` root-relative paths. With a
        Cloud root they must become ``/{org}/{project}/d/data/<source>/``.
        Without a root they must stay root-relative.
        """
        from dbt_charts.core.render.board_links import LinkContext

        adapter_registry = _make_adapter_registry(project_with_duckdb)

        # Without root: links are root-relative /data/...
        no_root = render_registered_view(
            request_path="/data/",
            project=project_with_duckdb,
            adapter_registry=adapter_registry,
            result_cache=None,
        )
        assert isinstance(no_root, RenderSuccess)
        assert "/data/wh" in no_root.html
        assert "/myorg/myproject/d/data/" not in no_root.html

        # With Cloud root: links become /{org}/{project}/d/data/...
        with_root = render_registered_view(
            request_path="/data/",
            project=project_with_duckdb,
            adapter_registry=adapter_registry,
            result_cache=None,
            link_context=LinkContext(root="/myorg/myproject/d"),
        )
        assert isinstance(with_root, RenderSuccess)
        assert "/myorg/myproject/d/data/wh" in with_root.html
        assert '"/data/wh"' not in with_root.html

    def test_empty_root_leaves_links_root_relative(
        self, project_with_duckdb: Project
    ) -> None:
        """link_context with empty root (dct serve boards-at-root) leaves links unchanged."""
        from dbt_charts.core.render.board_links import LinkContext

        adapter_registry = _make_adapter_registry(project_with_duckdb)
        result = render_registered_view(
            request_path="/data/",
            project=project_with_duckdb,
            adapter_registry=adapter_registry,
            result_cache=None,
            link_context=LinkContext(root=""),
        )
        assert isinstance(result, RenderSuccess)
        assert "/data/wh" in result.html


class TestRenderRegisteredViewUnknownSource:
    def test_unknown_source_returns_render_error(
        self, project_with_duckdb: Project
    ) -> None:
        """An unknown source name returns a RenderError with a BoardRenderResult."""
        adapter_registry = _make_adapter_registry(project_with_duckdb)
        result = render_registered_view(
            request_path="/data/bogus/",
            project=project_with_duckdb,
            adapter_registry=adapter_registry,
            result_cache=None,
        )
        assert result is not None
        assert isinstance(result, RenderError)
        assert result.dashboard is not None
        assert result.dashboard.status == "failed"


class _StopAtExpand(Exception):
    """Raised by a spied expand_registered_view to short-circuit before compile/execute."""


class TestRenderRegisteredViewSourceTypeIsNotADialect:
    """A source `type` is a connector kind, not a sqlglot dialect. csv/json/
    parquet are file sources and dbt_profile's real dialect lives in the
    profile — sqlglot raises rather than degrading on an unknown dialect
    name, so the resolver must guard and raise a structured error (which
    exits the pipeline as a RenderError), not let a bare ValueError escape.

    Captures the lazy resolver via a route with no pre-template query
    (`/data/<source>/` — same isolation trick as
    TestRenderRegisteredViewResolvesSourceDialect below) so this test
    exercises only the resolver's own guard, not the separate, pre-existing
    dbt_profile/file-source gap in the inspect resolver's schema-query path
    (out of scope here — see the task worksheet's Context section).
    """

    class _StubAdapterRegistry:
        def __init__(self, source_type: str) -> None:
            self._source_type = source_type

        def resolve_source_config(self, source: str) -> dict[str, str]:
            return {"type": self._source_type}

    @pytest.mark.parametrize("source_type", ["dbt_profile", "csv"])
    def test_non_dialect_source_type_raises_expansion_error_not_value_error(
        self,
        project_with_duckdb: Project,
        monkeypatch: pytest.MonkeyPatch,
        source_type: str,
    ) -> None:
        import dbt_charts.core.registered_views.render_pipeline as render_pipeline_mod
        from dbt_charts.core.registered_views.expander import ExpansionError

        captured: dict[str, object] = {}

        def spy(
            match: object,
            query_results: object,
            resolve_dialect: Callable[[], str | None] = lambda: None,
        ) -> object:
            captured["resolve_dialect"] = resolve_dialect
            raise _StopAtExpand

        monkeypatch.setattr(render_pipeline_mod, "expand_registered_view", spy)

        with pytest.raises(_StopAtExpand):
            render_registered_view(
                request_path="/data/bq/",
                project=project_with_duckdb,
                adapter_registry=self._StubAdapterRegistry(source_type),
                result_cache=None,
            )
        resolve_dialect = captured["resolve_dialect"]
        assert callable(resolve_dialect)
        with pytest.raises(ExpansionError, match=source_type):
            resolve_dialect()


class TestRenderRegisteredViewResolvesSourceDialect:
    """Regression: a BigQuery-typed source must reach the expander with its own
    dialect, not the ANSI default — the root cause of the /data/ 404 on BigQuery
    projects. Stops the pipeline right after dialect resolution (no real BigQuery
    connection needed) by spying on expand_registered_view and short-circuiting.

    Dialect resolution is lazy (a zero-arg resolver, not an already-resolved
    string, per TestRenderRegisteredViewSourceTypeIsNotADialect above). This
    test calls the captured resolver to confirm it resolves to the matched
    source's dialect when invoked.
    """

    class _StubAdapterRegistry:
        def resolve_source_config(self, source: str) -> dict[str, str]:
            return {"type": "bigquery"}

    def test_bigquery_source_dialect_reaches_expander(
        self,
        project_with_duckdb: Project,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import dbt_charts.core.registered_views.render_pipeline as render_pipeline_mod

        captured: dict[str, object] = {}

        def spy(
            match: object,
            query_results: object,
            resolve_dialect: Callable[[], str | None] = lambda: None,
        ) -> object:
            captured["resolve_dialect"] = resolve_dialect
            raise _StopAtExpand

        monkeypatch.setattr(render_pipeline_mod, "expand_registered_view", spy)

        with pytest.raises(_StopAtExpand):
            render_registered_view(
                request_path="/data/bq/",
                project=project_with_duckdb,
                adapter_registry=self._StubAdapterRegistry(),
                result_cache=None,
            )
        resolve_dialect = captured["resolve_dialect"]
        assert callable(resolve_dialect)
        assert resolve_dialect() == "bigquery"


class TestRenderRegisteredViewThreadsVariables:
    """Request query params must reach the render as variables.

    Without this, no registered view is interactive — details/expander toggles,
    tabs, and /data row-detail selection are all inert because the URL query
    string never reaches render().
    """

    def test_request_variables_reach_render(
        self, project_with_duckdb: Project, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sys

        from dbt_charts.core.render import render as real_render

        # The pipeline does `from dbt_charts.core.render import render` at call
        # time, resolving the package's re-exported name — patch that.
        render_pkg = sys.modules["dbt_charts.core.render"]

        captured: dict[str, object] = {}

        def spy(board: object, executor: object, **kwargs: object) -> object:
            captured.update(kwargs)
            return real_render(board, executor, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(render_pkg, "render", spy)
        adapter_registry = _make_adapter_registry(project_with_duckdb)
        result = render_registered_view(
            request_path="/inspector/wh/main/orders/",
            project=project_with_duckdb,
            adapter_registry=adapter_registry,
            result_cache=None,
            request_variables={"_details_probe": "true"},
        )
        assert result is not None
        assert captured.get("variables") == {"_details_probe": "true"}
