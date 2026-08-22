"""OSS inspect module — schema sources, resolver, search, and HTML templates.

The profiler engine (TableInspector, detectors, cache I/O) lives in the
private ``dbt-charts-super-schema`` package. This module only contains the
open-source components: DbtSchemaSource, LayeredSchemaResolver, schema
search, and the HTML inspect templates.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dbt_charts.core.inspect.renderer import (
        InspectProfileCompileError,
        render_inspect_dashboard,
        resolve_source_name,
        validate_inspect_variables,
    )

# Static list of available inspect templates.
# Template files live in dbt_charts/core/inspect/templates/{name}.yml
INSPECT_TEMPLATES: list[str] = [
    "categorical_column",
    "date_column",
    "model",
    "numeric_column",
    "quality",
    "string_column",
]

__all__ = [
    "render_inspect_dashboard",
    "resolve_source_name",
    "InspectProfileCompileError",
    "validate_inspect_variables",
    "INSPECT_TEMPLATES",
]

# Submodule (sources/, db_types, etc.) imports run this __init__ first, so
# these re-exports must not eagerly pull in renderer's (and transitively
# core.compile's) heavy import chain just to expose INSPECT_TEMPLATES.
_LAZY_ATTRS: dict[str, tuple[str, str]] = {
    "InspectProfileCompileError": (
        "dbt_charts.core.inspect.renderer",
        "InspectProfileCompileError",
    ),
    "render_inspect_dashboard": (
        "dbt_charts.core.inspect.renderer",
        "render_inspect_dashboard",
    ),
    "resolve_source_name": ("dbt_charts.core.inspect.renderer", "resolve_source_name"),
    "validate_inspect_variables": (
        "dbt_charts.core.inspect.renderer",
        "validate_inspect_variables",
    ),
}


def __getattr__(name: str) -> Any:
    try:
        module_path, attr_name = _LAZY_ATTRS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    module = importlib.import_module(module_path)
    value = getattr(module, attr_name)
    globals()[name] = value  # cache: repeated access is O(1) and `is` identity holds
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_ATTRS))
