"""Shared helper: find dangling $ref targets in a generated JSON Schema dict.

Used by test_completion_catalog.py to assert every $ref in a generated schema
resolves to a real definitions entry. A bare "#" (self-reference to the
document root) is always valid.

A duplicate of this helper exists outside dbt-charts/, for a caller there
that can't import across the dbt-charts/apps boundary.
"""

from __future__ import annotations

import re
from typing import Any

_REF_RE = re.compile(r"^#/definitions/([A-Za-z0-9_]+)$")


def find_dangling_refs(schema: dict[str, Any]) -> set[str]:
    """Return the set of $ref target names with no matching definitions entry.

    Walks every string value in the schema looking for '#/definitions/<name>'
    refs and checks each name against schema['definitions']. '#' is exempt
    (it means "the document root," which is always present).
    """
    definitions = schema.get("definitions", {})
    refs: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "$ref" and isinstance(value, str) and value != "#":
                    match = _REF_RE.match(value)
                    if match:
                        refs.add(match.group(1))
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    return {name for name in refs if name not in definitions}
