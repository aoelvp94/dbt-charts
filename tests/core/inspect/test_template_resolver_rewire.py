"""Structural regression tests for the inspect-template resolver rewire.

The bundled `dct inspect` templates must not carry any direct dependency on the
super_schema sidecar JSONs or hand-rolled `INFORMATION_SCHEMA` SQL — the rewire
moved schema-shaped panels onto `query: { type: schema, ... }`. This
file pins that contract so future edits don't quietly resurrect the old shape.
"""

from __future__ import annotations

from importlib.resources import files

_TEMPLATE_NAMES = (
    "model",
    "numeric_column",
    "categorical_column",
    "date_column",
    "string_column",
    "quality",
)


def _template_text(name: str) -> str:
    return (
        files("dbt_charts.core.inspect.templates").joinpath(f"{name}.yml").read_text()
    )


def test_no_super_schema_sidecar_reads() -> None:
    """No template reads ``read_json('....super_schema....json')`` directly.

    The sidecar JSON pipeline is gone. Schema-shaped panels go through the
    resolver; live panels stay on warehouse SQL.
    """
    for name in _TEMPLATE_NAMES:
        text = _template_text(name)
        assert "read_json" not in text, (
            f"{name}.yml still uses read_json — rewire to schema."
        )
        assert "super_schema" not in text, (
            f"{name}.yml still references super_schema — rewire to schema."
        )


def test_no_information_schema_in_templates() -> None:
    """No template carries hand-rolled INFORMATION_SCHEMA SQL.

    dbt-core's adapter introspection (via the resolver) is the canonical
    source for column inventory and types.
    """
    for name in _TEMPLATE_NAMES:
        text = _template_text(name).upper()
        assert "INFORMATION_SCHEMA" not in text, (
            f"{name}.yml still queries INFORMATION_SCHEMA — rewire to schema."
        )


def test_schema_panels_use_schema_query() -> None:
    """Each template that surfaces schema-shaped data declares a schema query.

    `model.yml` and `quality.yml` carry table-level schema panels.
    Per-column templates carry a column-level schema query.
    """
    for name in _TEMPLATE_NAMES:
        text = _template_text(name)
        assert "type: schema" in text, (
            f"{name}.yml has no schema query — rewire incomplete."
        )
