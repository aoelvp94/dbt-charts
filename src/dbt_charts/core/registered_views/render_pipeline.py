"""Registered-view render pipeline — core API.

Purpose: Execute the full registered-view pipeline (match → query → expand →
         compile → execute → render) and return a typed success/error result.

This is a pure-core function. It knows nothing about HTTP: no Response, no
FastAPI, no starlette. The server handler in serve/server.py calls this and
maps the typed result to HTTP responses.

Public API:
- ``RenderSuccess`` — successful render; carries the HTML output string.
- ``RenderError`` — failed render; carries a ``BoardRenderResult`` ready for
  the server to pass to ``_render_structured_errors_html``.
- ``render_registered_view(request_path, project, adapter_registry, ...)``
  — full pipeline. Returns ``None`` when no route matches (caller falls
  through to regular file routing). Returns ``RenderSuccess | RenderError``
  when a route matches, whether or not rendering succeeds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from dbt_charts.core.registered_views.expander import (
    ExpansionError,
    TemplateLoadError,
    expand_registered_view,
)
from dbt_charts.core.registered_views.loader import load_builtin_registry
from dbt_charts.core.registered_views.query_runner import (
    RegistryQueryError,
    run_registry_queries,
)
from dbt_charts.core.registered_views.router import RouteRouter

if TYPE_CHECKING:
    from dbt_charts.core.board import BoardRenderResult
    from dbt_charts.core.execute.cache_backend import QueryResultCache
    from dbt_charts.core.project import Project
    from dbt_charts.core.render.board_links import LinkContext

# Module-level router — compiled once from the built-in registry at import time.
_BUILTIN_ROUTER: RouteRouter = RouteRouter(load_builtin_registry())

# Shared empty request-variables default. Callers (serve, Cloud) always pass the
# request's query params; this is the "no query params" case. A named constant
# (never mutated) keeps the parameter non-optional — see render_registered_view.
_NO_REQUEST_VARS: dict[str, str] = {}


@dataclass
class RenderSuccess:
    """Successful registered-view render.

    Attributes:
        html: The rendered HTML output.
    """

    html: str


@dataclass
class RenderError:
    """Failed registered-view render.

    The ``dashboard`` field is a ``BoardRenderResult`` with ``status="failed"``
    and the relevant error payload set. The server passes it to
    ``_render_structured_errors_html`` to produce the error page.

    Attributes:
        dashboard: BoardRenderResult describing the failure.
    """

    dashboard: BoardRenderResult


# Union result type for callers that want a single type annotation.
RenderResult = RenderSuccess | RenderError


def render_registered_view(
    request_path: str,
    project: Project,
    adapter_registry: Any,
    result_cache: QueryResultCache | None,
    max_workers: int | None = None,
    link_context: LinkContext | None = None,
    file_materializer: Any | None = None,
    request_variables: dict[str, str] = _NO_REQUEST_VARS,
) -> RenderResult | None:
    """Run the full registered-view pipeline for a request path.

    Matches ``request_path`` against the built-in router, runs any pre-template
    queries, expands the template, compiles and executes the resulting board,
    and renders it to HTML.

    Args:
        request_path: Absolute URL path, e.g. ``"/data/snowflake/analytics/"``.
        project: The project handle, used by the file-source materializer to
            read project-local data files.
        adapter_registry: Configured adapter registry with adapters for the
            sources declared in the project.
        result_cache: Optional persistent query-result cache for the project.
        max_workers: Maximum parallel query workers. ``None`` uses the project
            default.
        request_variables: URL query params for the request, threaded through as
            render variables so interactive views (details/expander toggles, tabs)
            can read their state from the URL. Empty (the default) renders with
            template defaults.
        link_context: Optional link-rewriting context. Cloud callers pass a
            ``LinkContext`` with ``root="/{org}/{project}/d"`` so that
            internal links (sibling tables, schema/source navigation) are emitted
            as ``/{org}/{project}/d/data/...`` rather than root-relative ``/data/...``
            which would 404 under the Cloud project scope. Leave ``None`` for
            ``dct serve`` (links stay root-relative).

    Returns:
        ``None`` when no registered route matches (caller falls through to
        regular file-based routing).
        ``RenderSuccess`` when a route matches and the board renders without errors.
        ``RenderError`` when a route matches but any step fails.
    """
    from sqlglot.dialects.dialect import Dialect as SqlglotDialect

    from dbt_charts.core.board import BoardRenderResult
    from dbt_charts.core.compile import compile_authored_board
    from dbt_charts.core.compile.sql_guard import sqlglot_dialect
    from dbt_charts.core.diagnostics import ERR_INTERNAL, Diagnostic
    from dbt_charts.core.diagnostics.base import DbtChartsError
    from dbt_charts.core.diagnostics.execution import ExecutionError
    from dbt_charts.core.execute import Executor
    from dbt_charts.core.execute.file_source_materializer import (
        default_local_materializer_factory,
    )
    from dbt_charts.core.render import render
    from dbt_charts.core.render.errors import RenderError as RenderExecError

    match = _BUILTIN_ROUTER.match(request_path)
    if match is None:
        return None

    # --- Step 1: run pre-template queries ---
    try:
        query_results = run_registry_queries(
            match.view, match.path_params, adapter_registry, cache=result_cache
        )
    except RegistryQueryError as exc:
        return RenderError(
            dashboard=BoardRenderResult(
                status="failed",
                board_error=Diagnostic.from_code(ERR_INTERNAL, message=str(exc)),
            )
        )

    # --- Step 1.5: build a lazy dialect resolver for the matched source ---
    # Routes below /data/<source>/ and /inspector/<source>/ have a `source`
    # path param, but only the leaf table/detail/column templates actually
    # call sql_identifier() — resolving the dialect eagerly here would touch
    # the adapter registry (and can fail loudly) even for index-level routes
    # that never quote an identifier at all, 200->422ing a source-less
    # project's `/data/` and `/inspector/<source>/` pages. Passing a thunk
    # instead defers the resolve_source_config() call to the first
    # sql_identifier() call inside the template, if any.
    source_param = match.path_params.get("source")

    def resolve_dialect() -> str | None:
        if source_param is None:
            return None
        try:
            source_config = adapter_registry.resolve_source_config(source_param)
        except DbtChartsError as exc:
            raise ExpansionError(str(exc)) from exc
        source_type = source_config["type"]
        # A source `type` is a connector kind, not necessarily a sqlglot
        # dialect — csv/json/parquet are file sources and dbt_profile's real
        # dialect lives in the profile, unknowable here. sqlglot raises
        # rather than degrading on an unknown name, so guard before quoting.
        if sqlglot_dialect(source_type) not in SqlglotDialect.classes:
            raise ExpansionError(
                f"Source {source_param!r} has type {source_type!r}, which has "
                "no SQL dialect dbt charts can use to quote identifiers (file "
                "sources and dbt_profile sources have no fixed SQL dialect)."
            )
        return source_type

    # --- Step 2: expand template into an AuthoredBoard ---
    try:
        authored = expand_registered_view(match, query_results, resolve_dialect)
    except (TemplateLoadError, ExpansionError) as exc:
        return RenderError(
            dashboard=BoardRenderResult(
                status="failed",
                board_error=Diagnostic.from_code(ERR_INTERNAL, message=str(exc)),
            )
        )

    # --- Step 3: compile ---
    # Registered-view boards are programmatically generated and ref-free, so no
    # base_dir context is needed (compilation raises if a ref is ever hit).
    compile_result = compile_authored_board(authored)
    if not compile_result.success:
        return RenderError(
            dashboard=BoardRenderResult(
                status="failed",
                validation_errors=compile_result.errors,
            )
        )

    board = compile_result.board
    if board is None:
        return RenderError(
            dashboard=BoardRenderResult(
                status="failed",
                board_error=Diagnostic.from_code(
                    ERR_INTERNAL, message="Compilation produced no board"
                ),
            )
        )

    # --- Step 4: execute + render ---
    try:
        # Injected materializer (Cloud) wins; otherwise a lazy local factory so a
        # fully-cached registered view never builds a DuckDB (see Executor).
        executor = Executor(
            board,
            adapter_registry=adapter_registry,
            query_registry=compile_result.query_registry,
            result_cache=result_cache,
            file_materializer=file_materializer,
            file_materializer_factory=(
                None
                if file_materializer is not None
                else default_local_materializer_factory(project)
            ),
        )
        render_result = render(
            board,
            executor,
            format="html",
            variables=request_variables,
            max_workers=max_workers,
            link_context=link_context,
        )
    except (ExecutionError, RenderExecError) as exc:
        return RenderError(
            dashboard=BoardRenderResult(
                status="failed",
                board_error=Diagnostic.from_code(ERR_INTERNAL, message=str(exc)),
            )
        )

    if render_result.board_error is None and not render_result.chart_errors:
        html_output = render_result.output
        html = (
            html_output.decode("utf-8")
            if isinstance(html_output, bytes)
            else str(html_output)
        )
        return RenderSuccess(html=html)

    return RenderError(
        dashboard=BoardRenderResult(
            status="failed",
            board_error=render_result.board_error,
            chart_errors=render_result.chart_errors,
        )
    )
