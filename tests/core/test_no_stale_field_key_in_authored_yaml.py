"""Guard against the renamed ``field:`` key reappearing in authored YAML.

Pre-launch the data-binding key was renamed from ``field:`` to ``column:``.
Every place in authored dbt charts YAML that used ``field:`` was codemoded.
This test prevents regressions: a new example that copies old syntax or a
careless paste-from-docs will be caught here before it lands.

Scope: authored dbt charts surfaces under ``dbt-charts/examples``, the package
defaults tree, and the package inspect templates. dbt model trees
(``**/models/**``, where ``field:`` is dbt's ``relationships`` test argument)
and Looker migrator outputs and Looker corpus JSON live outside these roots
and are naturally out of scope — they either carry raw Looker API payloads
(where ``field`` is Looker's native key) or feed verbatim into Vega-Lite specs
(where ``field`` is VL's own data-binding key).

The same guard over ``apps/evals/charts`` and root ``tests/fixtures`` is
intentionally not covered here, since those roots are outside dbt-charts/.
"""

from __future__ import annotations

import re
from pathlib import Path  # noqa: F401  used in type annotations

from .._paths import DBT_CHARTS_DIR, DBT_CHARTS_PKG_DIR

_AUTHORED_YAML_ROOTS = [
    DBT_CHARTS_DIR / "examples",
    DBT_CHARTS_PKG_DIR / "core" / "defaults",
    DBT_CHARTS_PKG_DIR / "core" / "inspect" / "templates",
]

# Match lines whose first non-whitespace content is ``field:`` or ``- field:``.
# Scoped to authored data-binding usage — prose in comments is not a problem.
_FIELD_KEY_RE = re.compile(r"^[ \t]*(-[ \t]+)?field:(?:[ \t]|$)")


# `dbt_packages` holds vendored dbt code; `models` is a dbt project's own model
# tree. In both, `field:` is *dbt's* key — the argument to a `relationships`
# test (`to: ref(...)`, `field: id`), not dbt charts' data-binding key. Same
# reasoning the module docstring gives for the Looker roots: the token belongs
# to another language there. No authored dbt charts chart or board lives under a
# models/ tree.
_EXCLUDE_PARTS = {"dbt_packages", "models"}


def _iter_authored_yaml_files() -> list[Path]:
    paths: list[Path] = []
    for root in _AUTHORED_YAML_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix in {".yml", ".yaml"} and not _EXCLUDE_PARTS.intersection(
                path.parts
            ):
                paths.append(path)
    return paths


def test_no_authored_yaml_uses_old_field_key() -> None:
    offenders: list[tuple[Path, int, str]] = []
    for path in _iter_authored_yaml_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _FIELD_KEY_RE.match(line):
                offenders.append(
                    (path.relative_to(DBT_CHARTS_DIR), lineno, line.rstrip())
                )
    if offenders:
        msg = (
            "Authored YAML still uses the renamed `field:` data-binding key "
            "(pre-launch rename to `column:` is complete):\n"
        ) + "\n".join(f"  {p}:{ln}: {line}" for p, ln, line in offenders)
        raise AssertionError(msg)
