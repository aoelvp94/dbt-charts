"""Tests for the warehouse query attribution vocabulary.

Pin the behavior a warehouse cost model depends on:

- authored attribution is validated, never silently sanitized
- the engine's ``dbt_charts_`` namespace cannot be shadowed by an author
- runtime context accumulates across scopes and unwinds cleanly

The dbt-side transport is covered by ``execute/adapters/test_query_header.py``.
"""

from __future__ import annotations

import pytest

import dbt_charts.core.attribution as attribution_module
from dbt_charts.core.attribution import (
    attribute,
    connection_identity,
    current_attribution,
    set_surface,
    validate_attribution,
)


class TestValidateAttribution:
    def test_accepts_a_well_formed_pair(self) -> None:
        validate_attribution({"team": "architecture-analytics"})

    def test_accepts_an_empty_value(self) -> None:
        validate_attribution({"team": ""})

    def test_rejects_the_reserved_engine_prefix(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            validate_attribution({"dbt_charts_surface": "looker"})

    def test_rejects_the_unprefixed_app_key(self) -> None:
        """`app` is the cross-tool discriminator and sits outside the dbt_charts_ namespace,
        so nothing but this check stops an author shadowing it."""
        with pytest.raises(ValueError, match="reserved"):
            validate_attribution({"app": "looker"})

    def test_rejects_an_uppercase_key(self) -> None:
        with pytest.raises(ValueError, match="keys must match"):
            validate_attribution({"Cost Center": "data-platform"})

    def test_rejects_a_key_starting_with_a_digit(self) -> None:
        with pytest.raises(ValueError, match="keys must match"):
            validate_attribution({"2team": "x"})

    def test_rejects_a_value_with_spaces(self) -> None:
        with pytest.raises(ValueError, match="values must match"):
            validate_attribution({"team": "Architecture Analytics"})

    def test_rejects_an_over_long_value(self) -> None:
        with pytest.raises(ValueError, match="values must match"):
            validate_attribution({"team": "a" * 64})

    def test_names_the_offending_key(self) -> None:
        with pytest.raises(ValueError, match="cost_center"):
            validate_attribution({"cost_center": "Data Platform"})


class TestProcessSurface:
    def test_absent_until_an_entry_point_declares_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No surface is invented — a cost model never reads one nobody set."""
        monkeypatch.setattr(attribution_module, "_process_surface", {})
        assert "dbt_charts_surface" not in current_attribution()

    def test_set_surface_reaches_the_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(attribution_module, "_process_surface", {})
        set_surface("cloud")
        assert current_attribution()["dbt_charts_surface"] == "cloud"

    def test_a_scope_overrides_the_process_surface(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(attribution_module, "_process_surface", {})
        set_surface("serve")
        with attribute({"surface": "inspect"}, {}):
            assert current_attribution()["dbt_charts_surface"] == "inspect"
        assert current_attribution()["dbt_charts_surface"] == "serve"


class TestConnectionIdentity:
    """What may ride a pooled connection.

    A connection is shared by every source with the same connection identity, and a
    worker holds it across renders — so anything here must be true for every source
    and every query using it. Per-query and authored pairs ride the comment instead.
    """

    def test_carries_the_engine_constants(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(attribution_module, "_process_surface", {})
        assert connection_identity()["app"] == "dbt-charts"

    def test_carries_the_process_surface(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(attribution_module, "_process_surface", {})
        set_surface("serve")
        assert connection_identity()["dbt_charts_surface"] == "serve"

    def test_excludes_per_query_scope(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`dbt_charts_board` on a shared connection would label a second source's queries."""
        monkeypatch.setattr(attribution_module, "_process_surface", {})
        with attribute({"board": "revenue", "query": "monthly"}, {}):
            identity = connection_identity()
        assert "dbt_charts_board" not in identity
        assert "dbt_charts_query" not in identity

    def test_excludes_authored_attribution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two sources on one warehouse share a pool; a team here would mislabel one."""
        monkeypatch.setattr(attribution_module, "_process_surface", {})
        with attribute({}, {"team": "finance"}):
            assert "team" not in connection_identity()


class TestRuntimeContext:
    def test_absent_outside_any_scope(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(attribution_module, "_process_surface", {})
        assert current_attribution() == {}

    def test_scope_sets_prefixed_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(attribution_module, "_process_surface", {})
        with attribute({"surface": "cli"}, {}):
            assert current_attribution() == {"dbt_charts_surface": "cli"}

    def test_scope_unwinds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(attribution_module, "_process_surface", {})
        with attribute({"surface": "cli"}, {}):
            pass
        assert current_attribution() == {}

    def test_nested_scopes_merge(self) -> None:
        with (
            attribute({"surface": "cloud"}, {}),
            attribute({"board": "gtm/weekly-revenue"}, {}),
        ):
            current = current_attribution()
        assert current["dbt_charts_surface"] == "cloud"
        assert current["dbt_charts_board"] == "gtm-weekly-revenue"

    def test_inner_scope_overrides_the_same_key(self) -> None:
        with attribute({"surface": "cli"}, {}), attribute({"surface": "inspect"}, {}):
            assert current_attribution()["dbt_charts_surface"] == "inspect"

    def test_unset_fields_are_omitted_not_emitted_empty(self) -> None:
        with attribute({"surface": "cli"}, {}):
            assert "dbt_charts_board" not in current_attribution()

    def test_rejects_an_unknown_dimension(self) -> None:
        """A typo'd dimension is a caller bug, not a key that quietly vanishes."""
        with (
            pytest.raises(ValueError, match="unknown attribution dimension"),
            attribute({"surfce": "cli"}, {}),
        ):
            pass

    def test_engine_values_are_normalized_to_the_label_charset(self) -> None:
        """Engine-owned values are ours to normalize; authored ones are validated."""
        with attribute({"board": "GTM/Weekly Revenue"}, {}):
            assert current_attribution()["dbt_charts_board"] == "gtm-weekly-revenue"
