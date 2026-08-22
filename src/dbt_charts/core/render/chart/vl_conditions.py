"""Vega-Lite conditional color encoding helpers.

Converts Dataface ``ConditionalRule`` / ``ResolvedStyleChannel`` (mode="conditional")
into Vega-Lite ``condition`` arrays.  Shared by ``emitters/_channels.py`` and
``emitters/geo.py`` so the logic lives in one place.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, TypeAlias

from dbt_charts.core.compile.models.chart.authored import ConditionalRule
from dbt_charts.core.compile.models.chart.resolved import ResolvedStyleChannel

# VL encoding dict — heterogeneous by nature; Any is the honest choice here.
_VlEncoding: TypeAlias = dict[str, Any]

_OP_MAP: dict[str, str] = {
    "eq": "==",
    "ne": "!=",
    "lt": "<",
    "lte": "<=",
    "gt": ">",
    "gte": ">=",
}


def rule_to_vl_test(rule: ConditionalRule, field_ref: str) -> str:
    """Build a Vega-Lite ``condition.test`` expression for one rule.

    Binary ops map to ``_OP_MAP``. Extended predicates expand:
      - ``between [a, b]``  → ``(field >= a) && (field <= b)``
      - ``in [v1, v2, ...]``→ ``indexof([...], field) >= 0``
      - ``is_null: true``   → ``field == null``
      - ``is_null: false``  → ``field != null``
      - ``default: true``   → ``true`` (always matches)
    """
    if rule.default is True:
        return "true"
    if rule.is_null is True:
        return f"{field_ref} == null"
    if rule.is_null is False:
        return f"{field_ref} != null"
    if rule.between is not None:
        low, high = rule.between
        return (
            f"({field_ref} >= {json.dumps(low)}) && ({field_ref} <= {json.dumps(high)})"
        )
    if rule.in_ is not None:
        return f"indexof({json.dumps(list(rule.in_))}, {field_ref}) >= 0"
    pred_field, pred_val = rule.active_predicate()
    return f"{field_ref} {_OP_MAP[pred_field]} {json.dumps(pred_val)}"


def cf_rules_to_vl_condition(
    rules: Iterable[ConditionalRule],
    field_ref: str,
) -> _VlEncoding | None:
    """Build a VL conditional color encoding from CF rules.

    Only rules with ``background`` set contribute; returns ``None`` when
    no background rule exists.  The last rule in the list acts as the
    fallback ``value`` when it has ``default: true``.
    """
    rules_list = list(rules)
    conditions: list[_VlEncoding] = []
    fallback: str | None = None
    for rule in rules_list:
        if rule.background is None:
            continue
        if rule.default is True:
            fallback = rule.background
        else:
            conditions.append(
                {"test": rule_to_vl_test(rule, field_ref), "value": rule.background}
            )
    if not conditions and fallback is None:
        return None
    return {"condition": conditions, "value": fallback}


def resolved_channel_to_vl_condition(ch: ResolvedStyleChannel) -> _VlEncoding | None:
    """Convert a conditional-mode ``ResolvedStyleChannel`` to a VL encoding dict.

    Returns ``None`` when the channel carries no background rules.
    """
    field_ref = f"datum[{json.dumps(ch.data_field)}]"
    return cf_rules_to_vl_condition(ch.rules, field_ref)
