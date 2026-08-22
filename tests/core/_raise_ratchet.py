"""Shared AST walker for the raw-raise ratchet.

Flags bare `raise ValueError/TypeError/KeyError/RuntimeError(...)` calls —
these surface to users as ERR-INTERNAL, losing the structured code/fields the
diagnostic registry exists to provide. Two callers use this walker today:
tests/core/render/test_error_stamping.py (root: core/render/) and
tests/core/execute/test_error_stamping.py (root: core/execute/). Keep this
the single implementation — a new root gets a new thin test file that calls
into this module, not a forked copy of the visitor.

Precedent: tests/scripts/test_no_wrapper_script_creep.py (allowlist-gated AST
check).
"""

from __future__ import annotations

import ast
from pathlib import Path

BANNED_EXCEPTIONS = frozenset({"ValueError", "TypeError", "KeyError", "RuntimeError"})


class _RaiseVisitor(ast.NodeVisitor):
    """Collects (function-qualname, lineno) for banned bare-exception raises."""

    def __init__(self) -> None:
        self._stack: list[str] = []
        self.violations: list[tuple[str, int]] = []

    def _qualname(self) -> str:
        return ".".join(self._stack) if self._stack else "<module>"

    def _visit_scope(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    ) -> None:
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scope(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scope(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        exc = node.exc
        if (
            isinstance(exc, ast.Call)
            and isinstance(exc.func, ast.Name)
            and exc.func.id in BANNED_EXCEPTIONS
        ):
            self.violations.append((self._qualname(), node.lineno))
        self.generic_visit(node)


def find_violations(root: Path) -> dict[tuple[str, str], list[int]]:
    """Map (relative_path, qualname) -> line numbers of banned raises found today."""
    found: dict[tuple[str, str], list[int]] = {}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        visitor = _RaiseVisitor()
        visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
        for qualname, lineno in visitor.violations:
            found.setdefault((rel, qualname), []).append(lineno)
    return found


def assert_no_new_unstamped_raises(
    root: Path, allowlist: frozenset[tuple[str, str]], root_label: str
) -> None:
    """Every raw banned raise under `root` must be allowlisted or migrated."""
    found = find_violations(root)
    unlisted = sorted(key for key in found if key not in allowlist)
    assert not unlisted, (
        f"New unstamped raise(s) in the {root_label} module — stamp it with "
        "<Domain>Error.from_code(ERR_..., ...) using a code from the matching "
        "diagnostics/codes_*.py, or add a justified ALLOWLIST entry:\n"
        + "\n".join(
            f"  {rel}:{found[(rel, qualname)]} in {qualname}"
            for rel, qualname in unlisted
        )
    )


def assert_allowlist_has_no_stale_entries(
    root: Path, allowlist: frozenset[tuple[str, str]]
) -> None:
    """Allowlist entries must correspond to a real raise — forces cleanup on migration."""
    found = find_violations(root)
    stale = sorted(allowlist - found.keys())
    assert not stale, (
        "Stale ALLOWLIST entries no longer have a matching raise — remove them "
        f"(migration already happened, or the function/raise moved): {stale}"
    )
