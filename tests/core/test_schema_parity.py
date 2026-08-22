"""Parity tests: ensure config/model registries are consistent."""

from __future__ import annotations


def test_dialect_aliases_in_config():
    """Dialect aliases in execution config are valid sqlglot dialect targets."""
    import sqlglot

    from dbt_charts.core.compile.config import get_execution_config

    aliases = get_execution_config().dialect_aliases
    for key, value in aliases.items():
        try:
            sqlglot.parse_one("SELECT 1", read=value)
        except Exception as exc:
            raise AssertionError(
                f"Dialect alias '{key}' → '{value}' is not a valid sqlglot dialect"
            ) from exc


def test_variable_defaults_parity():
    """_VARIABLE_DEFAULTS keys/values match Variable.model_fields defaults."""
    from pydantic_core import PydanticUndefinedType

    from dbt_charts.core.compile.models.variable.authored import Variable
    from dbt_charts.core.compile.validate.authoring_warnings import _VARIABLE_DEFAULTS

    model_defaults = {
        name: field.default
        for name, field in Variable.model_fields.items()
        if not isinstance(field.default, PydanticUndefinedType)
        and field.default is not None
        and not field.exclude
    }
    assert model_defaults == _VARIABLE_DEFAULTS
