"""dbt Jinja rendering of source/profile config values.

These pin the contract that dataface resolves `{{ env_var(...) }}` (and the rest
of dbt's profile-rendering Jinja) through dbt's own ``ProfileRenderer`` — exactly
as dbt would — rather than a hand-rolled regex.
"""

from __future__ import annotations

import pytest

from dbt_charts.core.compile.sources.dbt_jinja import render_dbt_jinja_in_dict


class TestRenderDbtJinjaInDict:
    def test_env_var_default_used_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DF_TEST_VAR", raising=False)
        out = render_dbt_jinja_in_dict(
            {"path": "{{ env_var('DF_TEST_VAR', 'fallback.db') }}"}
        )
        assert out["path"] == "fallback.db"

    def test_env_var_value_wins_over_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DF_TEST_VAR", "/real/path.db")
        out = render_dbt_jinja_in_dict(
            {"path": "{{ env_var('DF_TEST_VAR', 'fallback.db') }}"}
        )
        assert out["path"] == "/real/path.db"

    def test_embedded_env_var_in_larger_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DB_HOST", "db.example.com")
        out = render_dbt_jinja_in_dict(
            {"dsn": "postgres://{{ env_var('DB_HOST') }}:5432"}
        )
        assert out["dsn"] == "postgres://db.example.com:5432"

    def test_plain_string_passthrough(self) -> None:
        out = render_dbt_jinja_in_dict({"path": "just/a/path/file.db"})
        assert out["path"] == "just/a/path/file.db"

    def test_missing_env_var_no_default_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # dbt's EnvVarMissingError is adapted to ValueError at the render boundary
        # so Pydantic validators surface it as a ValidationError, not a raw dbt error.
        monkeypatch.delenv("DF_TEST_MISSING", raising=False)
        with pytest.raises(ValueError, match="DF_TEST_MISSING"):
            render_dbt_jinja_in_dict({"host": "{{ env_var('DF_TEST_MISSING') }}"})

    def test_malformed_jinja_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="(?i)compil|jinja|error"):
            render_dbt_jinja_in_dict({"host": "literal {{ unclosed"})

    def test_resolves_nested_and_preserves_non_string_types(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DF_TEST_HOST", "db.example.com")
        monkeypatch.delenv("DF_TEST_SCHEMA", raising=False)
        out = render_dbt_jinja_in_dict(
            {
                "type": "postgres",
                "host": "{{ env_var('DF_TEST_HOST') }}",
                "port": 5432,
                "nested": {"schema": "{{ env_var('DF_TEST_SCHEMA', 'main') }}"},
            }
        )
        assert out == {
            "type": "postgres",
            "host": "db.example.com",
            "port": 5432,
            "nested": {"schema": "main"},
        }
        # int preserved as int, not stringified
        assert isinstance(out["port"], int)

    def test_resolves_env_var_inside_list_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """dbt's deep_map_render recurses into lists too (the old regex did not)."""
        monkeypatch.setenv("DF_TEST_ITEM", "resolved")
        out = render_dbt_jinja_in_dict(
            {"items": ["{{ env_var('DF_TEST_ITEM') }}", "plain"]}
        )
        assert out["items"] == ["resolved", "plain"]

    def test_password_keypath_defers_missing_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """dbt's SecretRenderer defers `password` rendering — a missing password
        env_var is left as a literal (fails at connect, not parse). We match dbt
        rather than re-deriving a stricter rule; passwords may contain `{{`/`%`."""
        monkeypatch.delenv("DF_TEST_PGPASS", raising=False)
        out = render_dbt_jinja_in_dict({"password": "{{ env_var('DF_TEST_PGPASS') }}"})
        assert out["password"] == "{{ env_var('DF_TEST_PGPASS') }}"
