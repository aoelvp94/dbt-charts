"""Detectors must build message=/fix= from the registry's templates.

Every Diagnostic.from_code(...) construction site under dbt-charts/src/ must
derive `message` and `fix` from a WarningCode's message_template/fix_template
(via .format(...), a bare attribute reference, or a local variable computed
from one) — never a hand-built string literal or f-string. Hand-built
messages drift from the registry's documented wording (the single source of
truth for what a code means) and can't be kept in sync by the doc-url/registry
tooling.

The scan walks every *.py file under src/ structurally (ast.Call nodes for
Diagnostic.from_code), not an enumerated list of "the files that currently do
this" — a gate scoped around a known violator only proves the rule is
enforced where it's already followed.
"""

from __future__ import annotations

import ast

from ..._paths import DBT_CHARTS_PKG_DIR


def _is_diagnostic_from_code_call(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "from_code"
        and isinstance(func.value, ast.Name)
        and func.value.id == "Diagnostic"
    )


def _is_err_internal_call(node: ast.Call) -> bool:
    # ERR_INTERNAL's message_template is the literal passthrough "{message}"
    # (the unclassified-failure escape hatch) — a hand-written message there
    # *is* the template usage, not a bypass of it.
    return bool(
        node.args
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "ERR_INTERNAL"
    )


def _literal_message_or_fix_kwargs(source: str, filename: str) -> list[str]:
    """Return "<file>:<line>:<kwarg>" for each literal string/f-string passed
    to a Diagnostic.from_code(...) call's message= or fix= keyword argument.
    """
    violations: list[str] = []
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _is_diagnostic_from_code_call(node)):
            continue
        if _is_err_internal_call(node):
            continue
        for kw in node.keywords:
            if kw.arg not in ("message", "fix"):
                continue
            is_str_constant = isinstance(kw.value, ast.Constant) and isinstance(
                kw.value.value, str
            )
            if is_str_constant or isinstance(kw.value, ast.JoinedStr):  # f-string
                violations.append(f"{filename}:{node.lineno}:{kw.arg}")
    return violations


class TestScannerCatchesLiterals:
    """Prove the scanner itself flags a hand-built string before trusting it
    against the real source tree.
    """

    def test_flags_string_literal(self) -> None:
        src = 'Diagnostic.from_code(WARN_X, chart="c", message="hardcoded", fix=None)'
        assert _literal_message_or_fix_kwargs(src, "synthetic.py") == [
            "synthetic.py:1:message"
        ]

    def test_flags_fstring(self) -> None:
        src = (
            'Diagnostic.from_code(WARN_X, chart="c", message=f"bad {x}", '
            'fix="also bad")'
        )
        violations = _literal_message_or_fix_kwargs(src, "synthetic.py")
        assert violations == ["synthetic.py:1:message", "synthetic.py:1:fix"]

    def test_allows_template_format_and_attribute(self) -> None:
        src = (
            "Diagnostic.from_code(\n"
            "    WARN_X,\n"
            "    chart=chart_id,\n"
            "    message=WARN_X.message_template.format(chart_id=chart_id),\n"
            "    fix=WARN_X.fix_template,\n"
            ")"
        )
        assert _literal_message_or_fix_kwargs(src, "synthetic.py") == []


class TestDetectorsUseTemplates:
    def test_no_diagnostic_construction_uses_a_literal_message_or_fix(
        self,
    ) -> None:
        files = sorted(DBT_CHARTS_PKG_DIR.rglob("*.py"))
        assert files, f"No source files found under {DBT_CHARTS_PKG_DIR}"
        violations: list[str] = []
        for f in files:
            violations.extend(
                _literal_message_or_fix_kwargs(f.read_text(encoding="utf-8"), str(f))
            )
        assert violations == [], (
            "Diagnostic.from_code(...) built with a hand-written message/fix "
            f"instead of the registry's message_template/fix_template: {violations}"
        )
