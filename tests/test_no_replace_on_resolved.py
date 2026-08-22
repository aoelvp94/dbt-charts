"""Whole-tree guard: no ``Resolved*`` value is copied-with-update.

Decision D-01 (initiative make-resolved-models-a-final-read-only-boundary):
a ``Resolved*`` instance is created only after every decision it represents
has been made. No ``Resolved*`` instance may be passed to
``dataclasses.replace()`` or ``.model_copy(update=...)`` anywhere under
``dbt-charts/src`` — compile, execute, sizing, and render alike.

Detector shape mirrors ``scripts/type_state_counter.py``: intentionally
approximate, accepting false negatives on operands it cannot statically
classify, in exchange for a mechanical, no-allowlist gate. For each
function body, it
tracks the annotated type of parameters and local ``x: T = ...``
assignments; a ``dataclasses.replace(x, ...)`` or ``x.model_copy(update=...)``
call is a violation only when ``x``'s tracked annotation name starts with
``Resolved``. Unannotated locals (``x = some_call()``) are not tracked and so
cannot be flagged — a deliberate false-negative bias, not a loophole for the
cases this test does classify.

The gate is empty and carries no allowlist: at the time this test was
written, a whole-tree scan found zero qualifying call sites. Any new one is
a defect — either the operand shouldn't be ``Resolved*``-typed yet (finish
resolution earlier), or the value it copies from should never have been
built as ``Resolved*`` in the first place (see ``ChartStyleContext`` for the
sibling non-Resolved type these working values belong on instead).

This is the single canonical guard for "no mutated copy of a Resolved*
value" anywhere in the tree, including render/ — it supersedes and replaces
the older, render-only ``test_no_resolved_model_copy.py`` (deleted), which
banned every ``model_copy``/``replace`` call under ``render/`` regardless of
operand type rather than tracking ``Resolved*`` specifically. Don't
reintroduce a second, narrower-scoped guard for the same rule.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

from ._paths import DBT_CHARTS_DIR

SRC_DIR = DBT_CHARTS_DIR / "src"


def _annotation_name(node: ast.expr | None) -> str | None:
    """Return the leading identifier of a type annotation, or None.

    Handles ``ResolvedStyle``, ``ResolvedStyle | None``,
    ``"ResolvedStyle"`` (string forward ref), and
    ``Optional[ResolvedStyle]`` — enough shapes to catch this repo's actual
    annotation styles without a full typing evaluator.
    """
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        # Forward-ref string annotation: "ResolvedStyle" or "ResolvedStyle | None".
        head = node.value.split("|")[0].strip()
        head = head.split("[")[0].strip()
        return head or None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _annotation_name(node.left) or _annotation_name(node.right)
    if isinstance(node, ast.Subscript):
        # Optional[X] / X[...] — recurse into the subscripted name.
        return _annotation_name(node.value)
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_resolved_name(name: str | None) -> bool:
    return name is not None and name.startswith("Resolved")


class _FunctionScanner(ast.NodeVisitor):
    def __init__(self, relpath: str) -> None:
        self.relpath = relpath
        self.violations: list[tuple[str, int, str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._scan_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._scan_function(node)

    def _scan_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        resolved_locals: set[str] = set()
        all_args = [
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ]
        for arg in all_args:
            if _is_resolved_name(_annotation_name(arg.annotation)):
                resolved_locals.add(arg.arg)

        for child in ast.walk(node):
            if (
                isinstance(child, ast.AnnAssign)
                and isinstance(child.target, ast.Name)
                and _is_resolved_name(_annotation_name(child.annotation))
            ):
                resolved_locals.add(child.target.id)

        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            # dataclasses.replace(x, ...) / replace(x, ...)
            is_replace = (
                isinstance(func, ast.Attribute) and func.attr == "replace"
            ) or (isinstance(func, ast.Name) and func.id == "replace")
            if is_replace and child.args:
                operand = child.args[0]
                if isinstance(operand, ast.Name) and operand.id in resolved_locals:
                    self.violations.append(
                        (
                            self.relpath,
                            child.lineno,
                            f"dataclasses.replace({operand.id}, ...)",
                        )
                    )
            # x.model_copy(update=...)
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "model_copy"
                and isinstance(func.value, ast.Name)
                and func.value.id in resolved_locals
                and any(kw.arg == "update" for kw in child.keywords)
            ):
                self.violations.append(
                    (
                        self.relpath,
                        child.lineno,
                        f"{func.value.id}.model_copy(update=...)",
                    )
                )

        # Recurse into nested function/class definitions with their own scope.
        # self.visit (not generic_visit) so a directly-nested FunctionDef/
        # AsyncFunctionDef dispatches back into _scan_function and gets its
        # own resolved_locals from its own params — generic_visit would only
        # visit its children, skipping the node itself.
        for child in ast.iter_child_nodes(node):
            self.visit(child)


def _scan_file(path: Path) -> list[tuple[str, int, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    relpath = path.relative_to(SRC_DIR).as_posix()
    scanner = _FunctionScanner(relpath)
    scanner.visit(tree)
    return scanner.violations


def _all_violations() -> list[tuple[str, int, str]]:
    violations: list[tuple[str, int, str]] = []
    for root, dirs, files in os.walk(SRC_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                violations.extend(_scan_file(Path(root) / name))
    return violations


def test_scan_root_exists() -> None:
    """Without this, a directory rename silently turns the scan into a no-op."""
    assert SRC_DIR.is_dir()
    assert (SRC_DIR / "dbt_charts" / "core").is_dir()


def test_no_resolved_operand_reaches_replace_or_model_copy_update() -> None:
    """No dataclasses.replace()/model_copy(update=...) call may copy a Resolved* value.

    Empty gate, no allowlist — see module docstring for the detector's shape
    and its deliberate false-negative bias on unannotated locals.
    """
    violations = _all_violations()
    assert not violations, (
        "Found dataclasses.replace()/model_copy(update=...) call(s) whose operand "
        "is annotated Resolved* — a Resolved* value is construction-final and must "
        "never be copied-with-update. Fix resolution to produce the right value "
        "the first time, or move the working type off the Resolved* name (see "
        f"ChartStyleContext). Violations: {violations}"
    )
