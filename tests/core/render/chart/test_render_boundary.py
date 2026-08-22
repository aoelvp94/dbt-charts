"""Grep-enforced import-boundary tests for the render layer.

Rule: render/ must not import from compile internals — only from
compile/models/ (the frozen IR) and standard library / third-party.

Banned: compile.resolve.chart.channel, compile.resolve.style.palette,
        compile.resolve.style.axis_cascade, compile.resolve.style.chart_context,
        compile.resolve.style.scale, compile.resolve.chart.enrich, compile.colors
        (deleted — reintroduction guard), and the deleted v1 render modules
        (also reintroduction guards). compile.resolve.style.board and .tokens
        are NOT banned — compile/models/AGENTS.md documents a deliberate
        reach-back exception there (resolve_style, resolve_chart_style_context,
        resolve_cascaded_font, apply_emoji_to_family, et al). Two further
        symbol-level bans below (not whole-module) cover compile.merge
        (to_padding_style) and compile.data_table
        (apply_measure_format_to_data_table, resolved_axis_style).

Scanned root: all of render/, not just render/chart/ — except
render/terminal.py and render/terminal_charts.py. That pair renders a
*normalized* Chart directly (dct's terminal/CLI preview), never constructing
or receiving a Resolved* chart at all; the reach-back rule ("was this value
available before Resolved* was constructed?") has no Resolved* to apply
against there, so it is a structurally different, out-of-scope rendering
surface rather than a tracked exception to this guard. Every other file in
render/ is Resolved*-consuming and fully in scope, with no allowlist: any
banned import anywhere else fails immediately.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ...._paths import DBT_CHARTS_PKG_DIR

_RENDER_ROOT = DBT_CHARTS_PKG_DIR / "core" / "render"
_CHART_ROOT = _RENDER_ROOT / "chart"
_EMITTERS_DIR = _CHART_ROOT / "emitters"

# render/terminal.py + render/terminal_charts.py: pre-resolution normalized-Chart
# preview surface — see module docstring. Excluded from the banned-import scan
# by relative path from _RENDER_ROOT.
_OUT_OF_SCOPE_RELPATHS = frozenset({"terminal.py", "terminal_charts.py"})

# Banned compile internals — render must import resolved IR only.
_BANNED = frozenset(
    {
        "dbt_charts.core.compile.resolve.chart.channel",
        "dbt_charts.core.compile.resolve.style.palette",
        # axis_cascade.py and chart_context.py hold the per-chart cascade
        # internals; scale.py holds ruler/scale math never exposed to render.
        # board.py/tokens.py stay unbanned — see the module docstring.
        "dbt_charts.core.compile.resolve.style.axis_cascade",
        "dbt_charts.core.compile.resolve.style.chart_context",
        "dbt_charts.core.compile.resolve.style.scale",
        "dbt_charts.core.compile.resolve.chart.enrich",
        # compile/colors.py, deleted (relocated to the neutral
        # dbt_charts.core.colors leaf). No current hits — this entry exists
        # solely so a future re-introduction under compile/ fails here.
        "dbt_charts.core.compile.colors",
        # v1 render modules, all deleted. No current hits — these entries exist
        # solely so a future re-introduction fails here.
        "dbt_charts.core.render.chart.pipeline",
        "dbt_charts.core.render.chart.geo",
        "dbt_charts.core.render.chart.profile",
        "dbt_charts.core.render.chart.standard_renderer",
    }
)


def _is_banned(module: str) -> bool:
    return any(module == b or module.startswith(b + ".") for b in _BANNED)


def _banned_edges(path: Path) -> list[tuple[str, str, str]]:
    """Return (relpath, module, symbol) for every banned import in *path*.

    A plain ``import a.b.c`` has no imported symbol; it reports ``"*"``.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    rel = path.relative_to(_RENDER_ROOT).as_posix()
    edges: list[tuple[str, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            edges.extend(
                (rel, alias.name, "*") for alias in node.names if _is_banned(alias.name)
            )
        elif (
            isinstance(node, ast.ImportFrom) and node.module and _is_banned(node.module)
        ):
            edges.extend((rel, node.module, alias.name) for alias in node.names)
    return edges


def _all_banned_edges() -> set[tuple[str, str, str]]:
    return {
        e
        for f in _RENDER_ROOT.rglob("*.py")
        if f.relative_to(_RENDER_ROOT).as_posix() not in _OUT_OF_SCOPE_RELPATHS
        for e in _banned_edges(f)
    }


def test_render_root_exists() -> None:
    """The scanned root — and the out-of-scope exclusions — must exist.

    Without this, a directory rename silently turns every test in this file
    into a no-op over an empty glob — which is exactly how the ``v2/`` version
    of this guard passed for months while enforcing nothing. The exclusion
    check keeps a rename of terminal.py/terminal_charts.py from silently
    disabling the exclusion (i.e. scanning nothing where it used to scan
    those two files, rather than including them again).
    """
    assert _RENDER_ROOT.is_dir(), f"render root not found: {_RENDER_ROOT}"
    assert any(_RENDER_ROOT.rglob("*.py")), f"no Python files under {_RENDER_ROOT}"
    for relpath in _OUT_OF_SCOPE_RELPATHS:
        assert (_RENDER_ROOT / relpath).is_file(), (
            f"{relpath} not found under {_RENDER_ROOT} — update _OUT_OF_SCOPE_RELPATHS "
            "if it moved or was removed"
        )


def test_chart_root_exists() -> None:
    """The chart subtree scanned by the chart-specific tests below must exist."""
    assert _CHART_ROOT.is_dir(), f"chart render root not found: {_CHART_ROOT}"
    assert any(_CHART_ROOT.rglob("*.py")), f"no Python files under {_CHART_ROOT}"


def test_no_banned_compile_imports() -> None:
    """No render/ file imports banned compile internals.

    No allowlist: every reach-back has been projected into a Resolved* field;
    a banned import anywhere in scope fails immediately.
    """
    violations = sorted(
        f"{rel}: imports {sym!r} from {mod!r}" for rel, mod, sym in _all_banned_edges()
    )
    assert not violations, (
        "render/ must not import banned compile internals:\n" + "\n".join(violations)
    )


def _collect_import_symbols(path: Path) -> list[tuple[str, str]]:
    """Return (module, imported name) pairs for `from module import name`."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    pairs: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                pairs.append((node.module, alias.name))
    return pairs


def test_does_not_import_apply_presentation_defaults_from_standard_renderer() -> None:
    """apply_presentation_defaults must come from presentation.py.

    It was relocated to the shared leaf (presentation.py) so render code could call
    it without a reverse dependency on the v1 standard_renderer. That module is now
    deleted; this stays as a re-introduction guard.
    """
    violations: list[str] = []
    for py_file in _CHART_ROOT.rglob("*.py"):
        for mod, name in _collect_import_symbols(py_file):
            if (
                mod == "dbt_charts.core.render.chart.standard_renderer"
                and name == "apply_presentation_defaults"
            ):
                rel = py_file.relative_to(_CHART_ROOT)
                violations.append(
                    f"{rel}: imports apply_presentation_defaults from standard_renderer"
                )
    assert not violations, (
        "apply_presentation_defaults must be imported from presentation.py:\n"
        + "\n".join(violations)
    )


_FEATURES_DIR = _CHART_ROOT / "features"


def test_features_apply_takes_no_board_style() -> None:
    """No feature apply() method may accept a board_style parameter.

    All board-derived values are baked into the resolved chart at resolve time.
    This test is the permanent lock: any feature that reintroduces board_style
    in apply() will fail here.
    """
    violations: list[str] = []
    for feature_file in sorted(_FEATURES_DIR.glob("*.py")):
        if feature_file.name.startswith("_"):
            continue
        try:
            tree = ast.parse(feature_file.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "apply":
                for arg in node.args.args:
                    if arg.arg == "board_style":
                        violations.append(
                            f"{feature_file.name}: apply() has board_style param"
                        )
    assert not violations, (
        "apply() must not accept board_style — bake the values into Resolved* fields:\n"
        + "\n".join(violations)
    )


def test_emitters_emit_takes_no_board_style() -> None:
    """No emitter emit() method may accept a board_style parameter.

    All families are baked — the board_style param has been dropped from every
    emit() signature.  This test is the permanent lock: any new emitter that
    reintroduces board_style will fail here.
    """
    violations: list[str] = []
    for emitter_file in sorted(_EMITTERS_DIR.glob("*.py")):
        if emitter_file.name.startswith("_"):
            continue
        try:
            tree = ast.parse(emitter_file.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "emit"
            ):
                all_args = node.args.args + node.args.kwonlyargs + node.args.posonlyargs
                for arg in all_args:
                    if arg.arg == "board_style":
                        violations.append(
                            f"{emitter_file.name}: emit() has board_style param"
                        )
    assert not violations, (
        "emit() must not accept board_style — bake the values into Resolved*Style:\n"
        + "\n".join(violations)
    )


_BANNED_TICK_SYMBOLS = frozenset(
    {"nice_tick_values", "stacked_bar_totals_max", "stacked_totals_max"}
)


_TICK_VALUES_MODULE = "dbt_charts.core.compile.resolve.chart.tick_values"


def _uses_banned_module_symbol(
    path: Path, module: str, banned_symbols: frozenset[str]
) -> list[str]:
    """Return banned-symbol usages of *module* in *path*, via either import form.

    Catches both ``from <module> import <symbol>`` and ``import <module> as
    alias`` + ``alias.<symbol>(...)``. Scoped to imports from *this exact
    module* — a same-named symbol imported from an unrelated module must not
    trip the guard (see ``test_tick_helper_checker_ignores_the_neutral_module``).

    Shared by the tick-values, ``to_padding_style``, and
    ``apply_measure_format_to_data_table``/``resolved_axis_style``
    symbol-level bans below — each otherwise-legitimate module
    (``compile.merge``, ``compile.data_table``) has one or more banned
    exports among other sanctioned ones, so banning the whole module would
    be wrong (``row_height`` from ``compile.data_table`` is a sanctioned
    render import).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    violations: list[str] = []
    module_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module and node.names:
            for alias in node.names:
                if alias.name in banned_symbols:
                    violations.append(f"imports {alias.name!r} from {node.module!r}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module:
                    module_aliases.add(alias.asname or alias.name)
    if module_aliases:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr in banned_symbols
                and isinstance(node.value, ast.Name)
                and node.value.id in module_aliases
            ):
                violations.append(f"uses {node.value.id}.{node.attr}(...)")
    return violations


def _uses_banned_tick_symbol(path: Path) -> list[str]:
    return _uses_banned_module_symbol(path, _TICK_VALUES_MODULE, _BANNED_TICK_SYMBOLS)


def test_emitters_do_not_import_data_derived_tick_helpers() -> None:
    """Emitters must not import data-derived tick helpers from tick_values.py.

    ``nice_tick_values``, ``stacked_bar_totals_max``, and its thin dispatcher
    ``stacked_totals_max`` run at resolve() time and write their results into
    ``ay.tick_values``; emitters read that baked field.
    An emitter that imports these symbols from tick_values.py reintroduces a
    render-side data pass that belongs at compile time. Checked via both
    `from ... import ...` and `import ... as alias` + attribute access.

    ``numeric_domain_bounds`` is authored-config parsing, not a data reach-back,
    and is permitted. ``_measured_label_padding.py`` imports ``nice_tick_values``
    from the neutral ``dbt_charts.core.numeric`` leaf (a generic numeric primitive,
    not the Dataface-typed tick_values.py module) to estimate the widest
    plausible label width when no tick count is baked — that import is not this
    guard's concern and carries no allowlist entry.
    """
    violations: list[str] = []
    for emitter_file in sorted(_EMITTERS_DIR.glob("*.py")):
        rel = emitter_file.relative_to(_EMITTERS_DIR)
        violations.extend(f"{rel}: {v}" for v in _uses_banned_tick_symbol(emitter_file))
    assert not violations, (
        "emitters must not import data-derived tick helpers from tick_values.py; "
        "read ay.tick_values instead:\n" + "\n".join(violations)
    )


_MERGE_MODULE = "dbt_charts.core.compile.merge"
_BANNED_MERGE_SYMBOLS = frozenset({"to_padding_style"})

_DATA_TABLE_MODULE = "dbt_charts.core.compile.data_table"
# apply_measure_format_to_data_table is data_table.py's own symbol.
# resolved_axis_style is imported into data_table.py's namespace from the
# banned axis_cascade.py (see axis_offset()'s docstring) — any name a module
# imports is reachable through it via `from <module> import <name>` just
# like one it defines, so it needs the same symbol-level ban here or it
# leaks through this otherwise-legitimate module exactly like the four
# names round 1 found leaking through resolve/style/__init__.py.
_BANNED_DATA_TABLE_SYMBOLS = frozenset(
    {"apply_measure_format_to_data_table", "resolved_axis_style"}
)


def test_does_not_import_to_padding_style_from_merge() -> None:
    """render/ must not import to_padding_style from compile/merge.py.

    ``compile.merge`` is not itself banned (it is a general-purpose patch-merge
    engine with plenty of legitimate compile-side uses), but
    ``to_padding_style`` specifically bakes the resolved-padding coercion that
    render must read straight off ``Resolved*Style`` — a symbol-level ban,
    same shape as the tick-values one above, rather than banning the module.
    """
    violations: list[str] = []
    for py_file in _RENDER_ROOT.rglob("*.py"):
        rel = py_file.relative_to(_RENDER_ROOT)
        if rel.as_posix() in _OUT_OF_SCOPE_RELPATHS:
            continue
        violations.extend(
            f"{rel}: {v}"
            for v in _uses_banned_module_symbol(
                py_file, _MERGE_MODULE, _BANNED_MERGE_SYMBOLS
            )
        )
    assert not violations, (
        "render/ must not import to_padding_style from compile/merge.py — "
        "layout padding is baked into Resolved*Style at resolve time:\n"
        + "\n".join(violations)
    )


def test_does_not_import_measure_format_helper_from_data_table() -> None:
    """render/ must not import apply_measure_format_to_data_table or
    resolved_axis_style from data_table.py.

    ``compile.data_table`` is not itself banned (``row_height`` is a sanctioned
    render import). ``apply_measure_format_to_data_table`` specifically bakes
    measure-format inheritance into data_table entries at resolve time —
    render must read the baked ``format`` field, never re-derive it.
    ``resolved_axis_style`` reaches data_table.py's namespace only because it
    imports it from the banned ``resolve.style.axis_cascade`` module; banning
    it here too closes that reach-through.
    """
    violations: list[str] = []
    for py_file in _RENDER_ROOT.rglob("*.py"):
        rel = py_file.relative_to(_RENDER_ROOT)
        if rel.as_posix() in _OUT_OF_SCOPE_RELPATHS:
            continue
        violations.extend(
            f"{rel}: {v}"
            for v in _uses_banned_module_symbol(
                py_file, _DATA_TABLE_MODULE, _BANNED_DATA_TABLE_SYMBOLS
            )
        )
    assert not violations, (
        "render/ must not import apply_measure_format_to_data_table or "
        "resolved_axis_style from compile/data_table.py:\n" + "\n".join(violations)
    )


def test_tick_helper_checker_catches_module_alias_form(tmp_path: Path) -> None:
    """The checker must also flag `import ... as tv` + `tv.nice_tick_values(...)`.

    A plain `from <module> import <name>` scan misses a banned symbol reached via
    a module import and attribute access.
    """
    snippet = tmp_path / "sneaky_emitter.py"
    snippet.write_text(
        "import dbt_charts.core.compile.resolve.chart.tick_values as tv\n"
        "\n"
        "def f():\n"
        "    return tv.nice_tick_values(0, 1, 5)\n"
    )
    assert _uses_banned_tick_symbol(snippet)


def test_tick_helper_checker_ignores_the_neutral_module() -> None:
    """A symbol named ``nice_tick_values`` imported from core.numeric is not banned.

    The checker matches on the *module*, not just the symbol name — otherwise the
    legitimate ``dbt_charts.core.numeric`` import in _measured_label_padding.py
    would falsely trip this guard.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        snippet = Path(tmp) / "legit_emitter.py"
        snippet.write_text(
            "from dbt_charts.core.numeric import nice_tick_values\n"
            "\n"
            "def f():\n"
            "    return nice_tick_values(0, 1, 5)\n"
        )
        assert not _uses_banned_tick_symbol(snippet)
