"""Tests for plain vs rich Diagnostic rendering.

Rendered through a real Rich ``Console`` to ``StringIO`` so the assertions
catch both the Panel-wrapper decision and Rich's own ANSI/markup
suppression — not just the conditional branch taken inside
``print_diagnostics``.
"""

from __future__ import annotations

import io
import json
import re
from unittest.mock import patch

import pytest
from rich.console import Console

from dbt_charts.cli._error_format import emit_diagnostics_jsonl, print_diagnostics
from dbt_charts.core.diagnostics import ERR_INTERNAL, Diagnostic
from dbt_charts.core.diagnostics.codes_query import WARN_FANOUT_RISK
from dbt_charts.core.diagnostics.diagnostic import SourceRange

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_BOX_CHARS = re.compile(r"[╭╮╰╯│─]")


def _make_error() -> Diagnostic:
    return Diagnostic.from_code(
        ERR_INTERNAL,
        message="Something went wrong",
        hint="Try this fix",
        range=SourceRange(file="charts/dashboard.yml", start_line=42, end_line=42),
    )


def _render(err: Diagnostic, *, plain: bool) -> str:
    """Run print_diagnostics through a real Console captured to StringIO."""
    buf = io.StringIO()
    fake = Console(file=buf, force_terminal=not plain, no_color=plain, width=100)
    with patch("dbt_charts.cli._console.Console", return_value=fake):
        print_diagnostics([err])
    return buf.getvalue()


@pytest.fixture
def err() -> Diagnostic:
    return _make_error()


def test_plain_mode_has_no_chrome(err: Diagnostic) -> None:
    """In plain mode: no Panel borders, no ANSI, and inline markup is stripped."""
    output = _render(err, plain=True)
    assert not _BOX_CHARS.search(output), f"Box chars in plain output:\n{output!r}"
    assert not _ANSI.search(output), f"ANSI codes in plain output:\n{output!r}"
    # Body content (with markup tags consumed by Rich) is still readable.
    assert "ERR-INTERNAL" in output
    assert "Something went wrong" in output
    assert "Hint: Try this fix" in output
    assert "At: charts/dashboard.yml:42" in output
    assert "Docs: dct docs errors" in output


def test_rich_mode_has_panel_chrome(err: Diagnostic) -> None:
    """In rich mode the surrounding Panel renders box chars."""
    output = _render(err, plain=False)
    assert _BOX_CHARS.search(output), f"Expected box chars in rich output:\n{output!r}"
    assert "ERR-INTERNAL" in output


def test_detail_and_evidence_reach_rendered_output() -> None:
    """A query diagnostic's detail/evidence (e.g. the offending table names
    for a fanout warning) must reach the printed body, not just `fields`.

    Regression: from_query_diagnostic.py deliberately stops concatenating
    detail/evidence into `message` (they're typed `fields` values instead),
    but print_diagnostics only read code/message/hint/fix/field/range —
    nothing rendered `fields`, so a fanout warning's table names were
    silently dropped from CLI output.
    """
    diag = Diagnostic.from_code(
        WARN_FANOUT_RISK,
        message="1:N join with aggregation (3.2x fanout) — verify aggregate correctness",
        fields={
            "severity": "warning",
            "confidence": 0.9,
            "detail": "Aggregate expressions reference columns from tables: orders, order_items",
            "evidence": [
                "Relationship: orders ↔ order_items (one-to-many, 3.2x fanout, confidence 90%)"
            ],
        },
    )
    output = _render(diag, plain=True)
    assert "orders" in output
    assert "order_items" in output


def test_query_name_is_rendered_in_message() -> None:
    """A DbtChartsError.from_code-constructed Diagnostic carries the query name
    as provenance only (from_code bypasses _format_message's "(query: name)"
    suffix). print_diagnostics must still surface it — otherwise the migrated
    (from_code) adapter path silently drops query attribution that the legacy
    path still prints."""
    diag = Diagnostic.from_code(
        ERR_INTERNAL,
        message="Warehouse could not resolve a column or table reference: boom.",
        query="broken_query",
    )
    output = _render(diag, plain=True)
    assert "(query: broken_query)" in output


def test_jsonl_keeps_nullable_range_fields_explicit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A rangeless diagnostic goes out as `"range": null`, not as a missing key.

    The JSONL stream is read by machines that branch on the field. Dropping the
    key leaves `undefined` on the other side — a value JSON cannot express, and
    one a reader has no way to tell from a shape it does not understand.
    """
    emit_diagnostics_jsonl([Diagnostic.from_code(ERR_INTERNAL, message="no position")])

    payload = json.loads(capsys.readouterr().err.strip())
    assert payload["range"] is None


def test_jsonl_keeps_columnless_range_explicit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    diag = Diagnostic.from_code(
        ERR_INTERNAL,
        message="line-level only",
        range=SourceRange(file="charts/b.yml", start_line=13, end_line=13),
    )

    emit_diagnostics_jsonl([diag])

    payload = json.loads(capsys.readouterr().err.strip())
    assert payload["range"] == {
        "file": "charts/b.yml",
        "start_line": 13,
        "end_line": 13,
        "columns": None,
    }
