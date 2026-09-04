"""The Cloud API's wire contract: its boundaries, and its strictness.

``contract.py`` is imported by two worlds — the ``dct cloud`` client and
``apps/cloud``'s API views (the shared wire contract). What keeps that legal is that it depends on
neither: no engine internals, no Django. These tests are what turns a stray
import into a failure instead of a circular-dependency surprise months later.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from dbt_charts.cloud_client import contract

PACKAGE = Path(contract.__file__).resolve().parent
MODULES = sorted(PACKAGE.glob("*.py"))


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_there_are_modules_to_check() -> None:
    assert {p.name for p in MODULES} == {
        "__init__.py",
        "client.py",
        "config.py",
        "context.py",
        "contract.py",
        "errors.py",
    }


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_module_imports_neither_django_nor_the_engine(path: Path) -> None:
    """A shape the CLI parses cannot depend on the server that emits it."""
    assert "django" not in _imported_roots(path)
    assert "from dbt_charts.core" not in path.read_text(encoding="utf-8")


# RFC 8414 discovery and RFC 8628 device-grant response shapes are Cloud's
# OAuth toolkit's wire formats, not this package's contract -- they carry
# fields (scopes_supported, refresh_token, ...) this client never reads, so
# they get extra="ignore" instead. Every other model here is decided by
# `apps/cloud/apps/api/transport.py` alone and keeps extra="forbid".
THIRD_PARTY_WIRE_MODELS = {
    "AuthorizationServerMetadata",
    "DeviceAuthorization",
    "DeviceToken",
}


def test_every_model_forbids_unknown_fields() -> None:
    """``extra="forbid"`` everywhere except the third-party OAuth wire shapes:
    a field the server sends and this side has never heard of is a contract
    break, and the point of one definition is that it surfaces at the
    boundary rather than being silently dropped."""
    from pydantic import BaseModel

    models = [
        value
        for value in vars(contract).values()
        if isinstance(value, type)
        and issubclass(value, BaseModel)
        and value is not BaseModel
    ]
    assert models
    for model in models:
        expected = "ignore" if model.__name__ in THIRD_PARTY_WIRE_MODELS else "forbid"
        assert model.model_config.get("extra") == expected, model.__name__


def test_an_unknown_error_code_does_not_parse() -> None:
    with pytest.raises(ValidationError):
        contract.ApiError.model_validate({"code": "teapot", "message": "no"})


def test_field_errors_default_to_empty_rather_than_absent() -> None:
    """A caller can always read ``field_errors``; a non-validation failure just
    has none. One shape, not two."""
    error = contract.ApiError(
        code=contract.ErrorCode.NOT_FOUND, message="No organization 'acme'."
    )
    assert error.field_errors == {}
