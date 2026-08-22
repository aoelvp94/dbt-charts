"""Tests for the QueryDiagnostic -> Diagnostic adapter.

The adapter must build its message through the registered code's own
message_template (not a hand-built f-string matching it by coincidence) and
must fall back to the registry's fix_template when the validator didn't
supply an instance-specific recommendation.
"""

from __future__ import annotations

from dbt_charts.core.diagnostics.codes_query import WARN_FANOUT_RISK
from dbt_charts.core.diagnostics.from_query_diagnostic import from_query_diagnostic
from dbt_charts.core.inspect.query_validator import QueryDiagnostic


def test_query_diagnostic_rejects_a_code_outside_the_four_registered() -> None:
    """QueryDiagnostic.code must be one of the four registered query codes.

    A plain `code: str` field lost the guarantee a 4-member Literal used to
    give; a true Literal can't reference the registry's runtime `.code`
    values, so this is enforced in `__post_init__` instead.
    """
    import pytest

    with pytest.raises(ValueError, match="WARN-NOT-A-QUERY-CODE"):
        QueryDiagnostic(code="WARN-NOT-A-QUERY-CODE", severity="warning", message="x")


def test_message_is_built_from_the_registered_template() -> None:
    diag = QueryDiagnostic(
        code=WARN_FANOUT_RISK.code,
        severity="warning",
        message="join multiplies rows",
    )
    warning = from_query_diagnostic("sales_q", diag)
    assert warning.message.startswith("Query 'sales_q': join multiplies rows")


def test_recommendation_present_wins_over_registry_fix_template() -> None:
    diag = QueryDiagnostic(
        code=WARN_FANOUT_RISK.code,
        severity="warning",
        message="join multiplies rows",
        recommendation="Add a GROUP BY on order_id specifically",
    )
    warning = from_query_diagnostic("sales_q", diag)
    assert warning.fix == "Add a GROUP BY on order_id specifically"


def test_recommendation_absent_falls_back_to_registry_fix_template() -> None:
    """A QueryDiagnostic with no instance-specific advice still gets a fix."""
    diag = QueryDiagnostic(
        code=WARN_FANOUT_RISK.code,
        severity="warning",
        message="join multiplies rows",
        recommendation=None,
    )
    warning = from_query_diagnostic("sales_q", diag)
    assert warning.fix == WARN_FANOUT_RISK.fix_template
    assert warning.fix


def test_detail_and_evidence_become_typed_fields_not_message_text() -> None:
    """detail/evidence land in .fields, not concatenated into .message (D-10)."""
    diag = QueryDiagnostic(
        code=WARN_FANOUT_RISK.code,
        severity="warning",
        message="join multiplies rows",
        detail="orders JOIN line_items",
        evidence=("multiplicity: one-to-many",),
    )
    warning = from_query_diagnostic("sales_q", diag)
    assert "orders JOIN line_items" not in warning.message
    assert "multiplicity: one-to-many" not in warning.message
    assert warning.fields["detail"] == "orders JOIN line_items"
    assert warning.fields["evidence"] == ["multiplicity: one-to-many"]


def test_path_is_the_query_authoring_path() -> None:
    """query_name is already in scope at the call site — no mutation needed,
    just author `path` directly so this diagnostic is source-map-stampable."""
    diag = QueryDiagnostic(
        code=WARN_FANOUT_RISK.code, severity="warning", message="join multiplies rows"
    )
    warning = from_query_diagnostic("sales_q", diag)
    assert warning.path == "queries.sales_q.sql"
