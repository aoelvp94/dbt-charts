"""Guard tests for the dbt-charts package boundary.

Two invariants:

1. No ``.py`` under ``dbt-charts/`` imports a top-level ``tests``, ``scripts``,
   or ``evals`` module. The dbt-charts package is the dependency root; it must
   not reach into the monorepo's top-level scaffolding.

2. No directory under ``dbt-charts/tests/`` carries an ``__init__.py``. See
   ``test_dbt_charts_tests_tree_has_no_init_files`` for why.

A third invariant — no ``conftest.py`` anywhere in the repo mutates
``__path__`` — needs a full-repo walk, not just dbt-charts/, so it is
intentionally not covered here.

An absolute-dotted-import invariant used to live here too (``from
dbt-charts.tests... import``), guarding against a real but easy mistake when
the pre-rename top-level directory was a valid Python identifier. The
directory rename to ``dbt-charts`` made that mistake syntactically
impossible — a dotted import segment can't contain a hyphen, so no ``.py``
file can ever spell that import — and the guard was deleted along with it.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from ._paths import DBT_CHARTS_DIR

_TOP_LEVEL_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+(?:tests|scripts|evals)(?:\.|\s|$)",
    re.MULTILINE,
)

_SKIP_DIRS = {".venv", "node_modules", "__pycache__", ".pytest_cache"}


def _walk_dbt_charts_files(suffix: str):
    """Yield paths under DBT_CHARTS_DIR matching suffix, pruning _SKIP_DIRS subtrees."""
    for root, dirs, files in os.walk(DBT_CHARTS_DIR, topdown=True):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            if name.endswith(suffix):
                yield Path(root) / name


@pytest.fixture(scope="module")
def dbt_charts_py_files() -> list[tuple[Path, str]]:
    """Walk dbt-charts/ once, reading every ``.py`` file's source text."""
    return [
        (path, path.read_text(encoding="utf-8"))
        for path in _walk_dbt_charts_files(suffix=".py")
    ]


def test_dbt_charts_does_not_import_top_level_tests_or_scripts(
    dbt_charts_py_files: list[tuple[Path, str]],
) -> None:
    """No .py under dbt-charts/ may import from top-level tests/, scripts/, or evals/."""
    offenders = []
    for path, text in dbt_charts_py_files:
        if _TOP_LEVEL_IMPORT_RE.search(text):
            offenders.append(str(path.relative_to(DBT_CHARTS_DIR)))
    assert not offenders, (
        "Files under dbt-charts/ must not import from top-level tests/, "
        f"scripts/, or evals/. Offenders: {offenders}"
    )


def test_dbt_charts_tests_tree_has_no_init_files() -> None:
    """No directory under ``dbt-charts/tests/`` may carry an ``__init__.py``.

    ``dbt-charts/tests`` is a sibling of ``src/``, so it is not part of the
    installed ``dbt-charts`` package — ``find_spec("dbt-charts.tests")`` is None.
    pytest's module-identity resolution for files with no package root is
    involved enough (``resolve_pkg_root_and_module_name``,
    ``consider_namespace_packages``, the ``module_name_from_path`` fallback,
    all interacting) that this docstring has stated the exact mechanism
    wrong twice. Don't restate it from memory — verify against the installed
    ``_pytest.pathlib`` source, or an actual repro, before touching this
    paragraph again.

    What's empirically proven, not just reasoned about: a task
    measured 8 ``__init__.py`` files scattered through this tree causing 34 pytest
    collection errors (``ModuleNotFoundError: No module named
    'dbt-charts.tests'``) on narrow, single-file/single-directory runs — the
    documented inner loop — while the whole-tree run stayed green by
    accident. Deleting all 8 fixed it: 0 collection errors, confirmed by
    this test. That result is the actual justification for the invariant;
    trust the measurement over any prose explanation of why.
    """
    tests_root = DBT_CHARTS_DIR / "tests"
    offenders = [
        str(path.relative_to(DBT_CHARTS_DIR))
        for path in tests_root.rglob("__init__.py")
    ]
    assert not offenders, (
        "dbt-charts/tests must stay free of __init__.py — one makes its whole "
        "subtree unreachable as dbt-charts.tests.* in narrow pytest runs. "
        f"Offenders: {offenders}"
    )
