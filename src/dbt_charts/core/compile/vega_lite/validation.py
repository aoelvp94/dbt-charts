"""Helpers for validating Vega-Lite contracts (projection input + emission boundary)."""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter, ValidationError

from dbt_charts.core.compile.models.vega_lite.contracts import (
    Projection,
    TopLevelCompositeSpec,
    TopLevelSpec,
    TopLevelUnitSpec,
)

_PROJECTION_ADAPTER: TypeAdapter[Any] = TypeAdapter(Projection)
_TOP_LEVEL_SPEC_ADAPTER: TypeAdapter[Any] = TypeAdapter(TopLevelSpec)


def vl_field_name(field_name: str) -> str:
    if field_name == "schema_":
        return "$schema"
    if field_name.endswith("_"):
        return field_name[:-1]
    return field_name


SYSTEM_OWNED_TOP_LEVEL_SPEC_FIELDS = frozenset(
    {
        "$schema",
        "data",
        "mark",
        "encoding",
        "config",
        "projection",
        "transform",
        "params",
    }
)
TOP_LEVEL_SPEC_PASSTHROUGH_FIELDS = frozenset(
    vl_field_name(field_name)
    for field_name in (
        set(TopLevelUnitSpec.model_fields) | set(TopLevelCompositeSpec.model_fields)
    )
    if vl_field_name(field_name) not in SYSTEM_OWNED_TOP_LEVEL_SPEC_FIELDS
)


def _validate_with_adapter(
    value: Any,
    adapter: TypeAdapter[Any],
    field_name: str,
) -> Any:
    try:
        validated = adapter.validate_python(value)
    except ValidationError as exc:
        raise ValueError(
            f"{field_name} must conform to the Vega-Lite contract"
        ) from exc
    return validated


def _validate_with_adapter_plain(
    value: Any,
    adapter: TypeAdapter[Any],
    field_name: str,
) -> Any:
    """Validate and convert back to plain Python containers (for spec passthrough)."""
    from dbt_charts.core.utils import to_plain_dict

    return to_plain_dict(
        _validate_with_adapter(value, adapter=adapter, field_name=field_name)
    )


def validate_projection_definition(value: Any) -> str | Projection | None:
    """Validate authored projection against the Projection contract."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, Projection):
        return value
    return _validate_with_adapter(
        value, adapter=_PROJECTION_ADAPTER, field_name="projection"
    )


def validate_top_level_spec(value: dict[str, Any]) -> dict[str, Any]:
    """Validate an emitted Vega-Lite spec against the top-level contract.

    Returns a plain dict — this is the final emission boundary where the
    spec must be a JSON-serializable dict for the Vega-Lite renderer.
    """
    return _validate_with_adapter_plain(
        value, adapter=_TOP_LEVEL_SPEC_ADAPTER, field_name="spec"
    )
