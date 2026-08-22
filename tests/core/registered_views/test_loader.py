"""Tests for the system view registry loader.

Purpose: Validate YAML loading, Pydantic model validation, built-in registry
         package loading, experimental-gating, and template lookup.
"""

import textwrap

import pytest

from dbt_charts.core.registered_views.loader import (
    RegistryLoadError,
    load_builtin_registry,
    load_registry_yaml,
    registered_view_prefixes,
    route_namespaces,
)


class TestLoadRegistryYaml:
    """Unit tests for parse+validate from a YAML string."""

    def test_minimal_valid_entry(self) -> None:
        """A minimal entry (name, route, template) parses cleanly."""
        raw = textwrap.dedent(
            """\
            views:
              - name: data_source
                route: /data/<source>/
                template: data/source-index.yaml
            """
        )
        views = load_registry_yaml(raw)
        assert len(views) == 1
        v = views[0]
        assert v.name == "data_source"
        assert v.route == "/data/<source>/"
        assert v.template == "data/source-index.yaml"

    def test_entry_with_queries(self) -> None:
        """An entry with a queries block parses and preserves query data."""
        raw = textwrap.dedent(
            """\
            views:
              - name: data_table
                route: /data/<source>/<schema>/<table>/
                template: data/table-index.yaml
                queries:
                  columns:
                    type: schema
                    source: "{{ path.source }}"
                    schema: "{{ path.schema }}"
                    table: "{{ path.table }}"
            """
        )
        views = load_registry_yaml(raw)
        assert len(views) == 1
        v = views[0]
        assert v.queries is not None
        assert "columns" in v.queries
        assert v.queries["columns"]["type"] == "schema"

    def test_missing_name_raises(self) -> None:
        """An entry without a name raises RegistryLoadError."""
        raw = textwrap.dedent(
            """\
            views:
              - route: /data/<source>/
                template: data/source-index.yaml
            """
        )
        with pytest.raises(RegistryLoadError):
            load_registry_yaml(raw)

    def test_missing_template_raises(self) -> None:
        """An entry without a template raises RegistryLoadError."""
        raw = textwrap.dedent(
            """\
            views:
              - name: data_source
                route: /data/<source>/
            """
        )
        with pytest.raises(RegistryLoadError):
            load_registry_yaml(raw)

    def test_duplicate_names_raise(self) -> None:
        """Two entries with the same name raise RegistryLoadError."""
        raw = textwrap.dedent(
            """\
            views:
              - name: data_source
                route: /data/<source>/
                template: data/source-index.yaml
              - name: data_source
                route: /data/<source>/other/
                template: data/source-other.yaml
            """
        )
        with pytest.raises(RegistryLoadError, match="duplicate.*data_source"):
            load_registry_yaml(raw)

    def test_empty_views_list_is_valid(self) -> None:
        """An empty views list is valid — no views returned."""
        raw = "views: []\n"
        views = load_registry_yaml(raw)
        assert views == []

    def test_missing_views_key_raises(self) -> None:
        """YAML without a top-level 'views' key raises RegistryLoadError."""
        raw = "not_views:\n  - name: x\n"
        with pytest.raises(RegistryLoadError, match="'views'"):
            load_registry_yaml(raw)

    def test_experimental_flag_parsed(self) -> None:
        """An entry marked experimental=true parses and sets the flag."""
        raw = textwrap.dedent(
            """\
            views:
              - name: data_source
                route: /data/<source>/
                template: data/source-index.yaml
                experimental: true
            """
        )
        views = load_registry_yaml(raw, include_experimental=True)
        assert views[0].experimental is True

    def test_experimental_defaults_false(self) -> None:
        """An entry without experimental defaults to False."""
        raw = textwrap.dedent(
            """\
            views:
              - name: data_source
                route: /data/<source>/
                template: data/source-index.yaml
            """
        )
        views = load_registry_yaml(raw)
        assert views[0].experimental is False


class TestExperimentalGating:
    """Tests for experimental view filtering."""

    def test_load_registry_yaml_excludes_experimental_by_default(self) -> None:
        """load_registry_yaml excludes experimental views when include_experimental=False."""
        raw = textwrap.dedent(
            """\
            views:
              - name: stable_view
                route: /data/<source>/
                template: data/source-index.yaml
              - name: experimental_view
                route: /experimental/<source>/
                template: experimental/source.yaml
                experimental: true
            """
        )
        views = load_registry_yaml(raw, include_experimental=False)
        assert len(views) == 1
        assert views[0].name == "stable_view"

    def test_load_registry_yaml_includes_experimental_when_requested(self) -> None:
        """load_registry_yaml includes experimental views when include_experimental=True."""
        raw = textwrap.dedent(
            """\
            views:
              - name: stable_view
                route: /data/<source>/
                template: data/source-index.yaml
              - name: experimental_view
                route: /experimental/<source>/
                template: experimental/source.yaml
                experimental: true
            """
        )
        views = load_registry_yaml(raw, include_experimental=True)
        assert len(views) == 2


class TestBuiltinRegistry:
    """Tests for loading the shipped registry.yaml package data."""

    def test_builtin_registry_loads(self) -> None:
        """load_builtin_registry() returns a non-empty list of views."""
        views = load_builtin_registry()
        assert len(views) > 0

    def test_builtin_registry_all_data_and_inspector_depths(self) -> None:
        """All nine required routes are present in the built-in registry."""
        views = load_builtin_registry()
        routes = {v.route for v in views}
        expected = {
            "/data/",
            "/data/<source>/",
            "/data/<source>/<schema>/",
            "/data/<source>/<schema>/<table>/",
            "/data/<source>/<schema>/<table>/detail/",
            "/inspector/<source>/",
            "/inspector/<source>/<schema>/",
            "/inspector/<source>/<schema>/<table>/",
            "/inspector/<source>/<schema>/<table>/<column>/",
        }
        assert expected <= routes

    def test_builtin_registry_no_duplicate_names(self) -> None:
        """Built-in registry has no duplicate view names."""
        views = load_builtin_registry()
        names = [v.name for v in views]
        assert len(names) == len(set(names))

    def test_builtin_registry_all_have_templates(self) -> None:
        """Every built-in view declares a template path."""
        views = load_builtin_registry()
        for v in views:
            assert v.template, f"View {v.name!r} has no template"

    def test_builtin_registered_views_are_not_experimental(self) -> None:
        """All built-in system views (data + inspector) are non-experimental by default."""
        views = load_builtin_registry()
        for v in views:
            assert not v.experimental, (
                f"Built-in view {v.name!r} is marked experimental; "
                "system views ship stable"
            )


class TestRegisteredViewPrefixes:
    """Tests for the route-namespace list Cloud mounts its URL patterns from."""

    def test_prefixes_are_distinct_first_seen_namespaces(self) -> None:
        """Each route's literal first segment is returned once, in registry order."""
        prefixes = registered_view_prefixes()
        # Both built-in namespaces are exposed, data before inspector.
        assert prefixes == ["data", "inspector"]

    def test_prefixes_are_literal_mountable_segments(self) -> None:
        """Every prefix is a non-empty literal segment Cloud can mount as a URL prefix."""
        for prefix in registered_view_prefixes():
            assert prefix
            assert "<" not in prefix
            assert "/" not in prefix

    def test_route_namespaces_rejects_param_first_route(self) -> None:
        """A route whose first segment is a path param fails loud, not silently mangled."""
        views = load_registry_yaml(
            textwrap.dedent(
                """\
                views:
                  - name: bad_param_first
                    route: /<vendor>/data/
                    template: bad/param-first.yaml
                """
            )
        )
        with pytest.raises(RegistryLoadError, match="literal namespace segment"):
            route_namespaces(views)

    def test_route_namespaces_rejects_rootless_route(self) -> None:
        """A bare '/' route (empty first segment) fails loud, same as a param-first one."""
        views = load_registry_yaml(
            textwrap.dedent(
                """\
                views:
                  - name: bad_root
                    route: /
                    template: bad/root.yaml
                """
            )
        )
        with pytest.raises(RegistryLoadError, match="literal namespace segment"):
            route_namespaces(views)

    def test_route_namespaces_dedups_preserving_order(self) -> None:
        """Repeated namespaces collapse to first-seen order."""
        views = load_registry_yaml(
            textwrap.dedent(
                """\
                views:
                  - name: b_root
                    route: /beta/
                    template: beta/root.yaml
                  - name: a_root
                    route: /alpha/<x>/
                    template: alpha/x.yaml
                  - name: b_deep
                    route: /beta/<x>/
                    template: beta/x.yaml
                """
            )
        )
        assert route_namespaces(views) == ["beta", "alpha"]
