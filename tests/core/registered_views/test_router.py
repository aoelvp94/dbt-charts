"""Tests for system view route matching and path-param extraction.

Purpose: Validate route compilation, matching, path-param extraction, and
         error handling for the registered-view router.
"""

import pytest

from dbt_charts.core.registered_views.models import RegisteredView
from dbt_charts.core.registered_views.router import (
    RouteMatch,
    RouteRouter,
    compile_route,
)


class TestCompileRoute:
    """Unit tests for route pattern compilation."""

    def test_route_requires_leading_slash(self) -> None:
        """Routes without a leading slash raise ValueError."""
        with pytest.raises(ValueError, match="leading slash"):
            compile_route("data/<source>/")

    def test_route_requires_trailing_slash(self) -> None:
        """Routes without a trailing slash raise ValueError."""
        with pytest.raises(ValueError, match="trailing slash"):
            compile_route("/data/<source>")

    def test_empty_param_name_raises(self) -> None:
        """An empty param name <> raises ValueError."""
        with pytest.raises(ValueError, match="empty"):
            compile_route("/data/<>/")

    def test_malformed_unclosed_angle_bracket_raises(self) -> None:
        """A segment starting with '<' but not ending with '>' raises ValueError."""
        with pytest.raises(ValueError, match="malformed param"):
            compile_route("/data/<source/")

    def test_malformed_unopened_angle_bracket_raises(self) -> None:
        """A segment ending with '>' but not starting with '<' raises ValueError."""
        with pytest.raises(ValueError, match="malformed param"):
            compile_route("/data/source>/")

    def test_malformed_inner_angle_bracket_raises(self) -> None:
        """A segment with '<' or '>' in the middle raises ValueError."""
        with pytest.raises(ValueError, match="malformed param"):
            compile_route("/data/so<urce>/")


class TestRouteMatching:
    """Route matching against real request paths."""

    @pytest.fixture
    def data_source_view(self) -> RegisteredView:
        return RegisteredView(
            name="data_source",
            route="/data/<source>/",
            template="data/source-index.yaml",
        )

    @pytest.fixture
    def data_schema_view(self) -> RegisteredView:
        return RegisteredView(
            name="data_schema",
            route="/data/<source>/<schema>/",
            template="data/schema-index.yaml",
        )

    @pytest.fixture
    def data_table_view(self) -> RegisteredView:
        return RegisteredView(
            name="data_table",
            route="/data/<source>/<schema>/<table>/",
            template="data/table-index.yaml",
        )

    @pytest.fixture
    def data_detail_view(self) -> RegisteredView:
        return RegisteredView(
            name="data_table_detail",
            route="/data/<source>/<schema>/<table>/detail/",
            template="data/table-detail.yaml",
        )

    @pytest.fixture
    def inspector_column_view(self) -> RegisteredView:
        return RegisteredView(
            name="inspector_column",
            route="/inspector/<source>/<schema>/<table>/<column>/",
            template="inspector/column.yaml",
        )

    # --- depth-1: source ---

    def test_source_depth_match(self, data_source_view: RegisteredView) -> None:
        """Source-depth route matches and extracts source param."""
        router = RouteRouter([data_source_view])
        result = router.match("/data/snowflake/")
        assert result is not None
        assert result.view.name == "data_source"
        assert result.path_params == {"source": "snowflake"}

    def test_source_depth_no_match_on_deeper_path(
        self, data_source_view: RegisteredView
    ) -> None:
        """Source-depth route does not match a schema-depth path."""
        router = RouteRouter([data_source_view])
        assert router.match("/data/snowflake/analytics/") is None

    # --- depth-2: schema ---

    def test_schema_depth_match(self, data_schema_view: RegisteredView) -> None:
        """Schema-depth route matches and extracts source+schema params."""
        router = RouteRouter([data_schema_view])
        result = router.match("/data/snowflake/analytics/")
        assert result is not None
        assert result.path_params == {"source": "snowflake", "schema": "analytics"}

    # --- depth-3: table ---

    def test_table_depth_match(self, data_table_view: RegisteredView) -> None:
        """Table-depth route matches and extracts all three params."""
        router = RouteRouter([data_table_view])
        result = router.match("/data/snowflake/analytics/sales/")
        assert result is not None
        assert result.path_params == {
            "source": "snowflake",
            "schema": "analytics",
            "table": "sales",
        }

    def test_table_depth_no_match_on_detail(
        self, data_table_view: RegisteredView
    ) -> None:
        """Table-depth route does not match a detail path."""
        router = RouteRouter([data_table_view])
        assert router.match("/data/snowflake/analytics/sales/detail/") is None

    # --- depth-4: detail (fixed segment, not a param) ---

    def test_detail_depth_match(self, data_detail_view: RegisteredView) -> None:
        """Detail route matches the fixed /detail/ segment and extracts three params."""
        router = RouteRouter([data_detail_view])
        result = router.match("/data/snowflake/analytics/sales/detail/")
        assert result is not None
        assert result.path_params == {
            "source": "snowflake",
            "schema": "analytics",
            "table": "sales",
        }
        # 'detail' must NOT appear as a path param — it is a fixed literal
        assert "detail" not in result.path_params

    def test_detail_depth_no_match_on_table(
        self, data_detail_view: RegisteredView
    ) -> None:
        """Detail route does not match the plain table path."""
        router = RouteRouter([data_detail_view])
        assert router.match("/data/snowflake/analytics/sales/") is None

    # --- inspector column depth ---

    def test_inspector_column_match(
        self, inspector_column_view: RegisteredView
    ) -> None:
        """Inspector column route extracts all four params."""
        router = RouteRouter([inspector_column_view])
        result = router.match("/inspector/snowflake/analytics/sales/revenue/")
        assert result is not None
        assert result.path_params == {
            "source": "snowflake",
            "schema": "analytics",
            "table": "sales",
            "column": "revenue",
        }

    # --- multi-route router: first-match semantics ---

    def test_router_picks_correct_depth(
        self,
        data_source_view: RegisteredView,
        data_schema_view: RegisteredView,
        data_table_view: RegisteredView,
        data_detail_view: RegisteredView,
    ) -> None:
        """Router returns the correct view at each depth when all are registered."""
        router = RouteRouter(
            [
                data_source_view,
                data_schema_view,
                data_table_view,
                data_detail_view,
            ]
        )
        src = router.match("/data/snowflake/")
        sch = router.match("/data/snowflake/analytics/")
        tbl = router.match("/data/snowflake/analytics/sales/")
        det = router.match("/data/snowflake/analytics/sales/detail/")

        assert src is not None and src.view.name == "data_source"
        assert sch is not None and sch.view.name == "data_schema"
        assert tbl is not None and tbl.view.name == "data_table"
        assert det is not None and det.view.name == "data_table_detail"

    def test_unregistered_path_returns_none(
        self, data_table_view: RegisteredView
    ) -> None:
        """A path that matches no route returns None — no exception."""
        router = RouteRouter([data_table_view])
        assert router.match("/unknown/path/") is None

    # --- trailing-slash tolerance: routes are directory-like ---

    def test_match_tolerates_missing_trailing_slash(
        self, data_schema_view: RegisteredView
    ) -> None:
        """A request path without its trailing slash matches the same route.

        Board links are emitted slashless (``/data/wh/analytics``); the router's
        routes are all directory-like (end in ``/``), so a request path is
        equivalent with or without its trailing slash.
        """
        router = RouteRouter([data_schema_view])
        with_slash = router.match("/data/snowflake/analytics/")
        without_slash = router.match("/data/snowflake/analytics")
        assert without_slash is not None
        assert without_slash.view.name == "data_schema"
        assert without_slash.path_params == {
            "source": "snowflake",
            "schema": "analytics",
        }
        # Both forms resolve identically.
        assert with_slash is not None
        assert without_slash.path_params == with_slash.path_params

    # --- param validation: no empty segments ---

    def test_empty_param_segment_does_not_match(
        self, data_source_view: RegisteredView
    ) -> None:
        """A path param that resolves to an empty string must not match."""
        router = RouteRouter([data_source_view])
        # "/data//" has an empty source segment
        assert router.match("/data//") is None

    def test_param_with_space_does_not_match(
        self, data_source_view: RegisteredView
    ) -> None:
        """Unencoded spaces in path params must not match (fail fast)."""
        router = RouteRouter([data_source_view])
        assert router.match("/data/snow flake/") is None


class TestRouteMatch:
    """RouteMatch data container tests."""

    def test_route_match_exposes_view_and_params(self) -> None:
        """RouteMatch carries the matched view and extracted path params."""
        view = RegisteredView(
            name="data_source",
            route="/data/<source>/",
            template="data/source-index.yaml",
        )
        match = RouteMatch(view=view, path_params={"source": "warehouse"})
        assert match.view is view
        assert match.path_params == {"source": "warehouse"}


class TestDuplicateViewNames:
    """Registry-level validation: duplicate names are rejected."""

    def test_duplicate_view_name_raises(self) -> None:
        """Two views with the same name raise ValueError at router construction."""
        v1 = RegisteredView(
            name="data_source",
            route="/data/<source>/",
            template="data/source-index.yaml",
        )
        v2 = RegisteredView(
            name="data_source",  # duplicate
            route="/data/<source>/other/",
            template="data/source-other.yaml",
        )
        with pytest.raises(ValueError, match="duplicate.*data_source"):
            RouteRouter([v1, v2])
