"""Guard: ``PanelRows(...)`` is constructed in exactly one module.

``NewType`` only stops the *accidental* case (any module can call
``PanelRows(rows)``); this test pins the deliberate, disciplined case —
``partition()``/``regroup()``/``map_panels()`` are the sole constructors,
mirroring dbt-charts/tests/core/render/chart/test_render_boundary.py's
grep-enforced style.
"""

from __future__ import annotations

import re

from ....._paths import DBT_CHARTS_PKG_DIR

_ALLOWED_RELPATH = "core/compile/resolve/chart/_chart_rows.py"

_CONSTRUCTOR_CALL = re.compile(r"\bPanelRows\(")


def test_panel_rows_constructed_only_in_chart_rows_module():
    # A wrong parents[] index silently resolves to a directory with no .py
    # files, so rglob yields nothing and this guard passes forever without
    # ever scanning real source.
    assert DBT_CHARTS_PKG_DIR.is_dir(), (
        f"DBT_CHARTS_PKG_DIR resolved to a non-directory: {DBT_CHARTS_PKG_DIR}"
    )
    offenders: list[str] = []
    for path in DBT_CHARTS_PKG_DIR.rglob("*.py"):
        relpath = path.relative_to(DBT_CHARTS_PKG_DIR).as_posix()
        if relpath == _ALLOWED_RELPATH:
            continue
        text = path.read_text(encoding="utf-8")
        if _CONSTRUCTOR_CALL.search(text):
            offenders.append(relpath)
    assert not offenders, (
        f"PanelRows(...) constructed outside {_ALLOWED_RELPATH}: {offenders}. "
        "Only partition()/regroup()/map_panels() may construct PanelRows."
    )
