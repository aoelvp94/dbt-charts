"""Structural guard: chart-emit code never consumes the authored ChartStylePatch.

Architectural directive (RJ, 2026-05-04):
    "The renderer should not need to know how the final result was reached.
     Whether it is theme default or user override, the result is the same. So
     ResolvedChart should only have the final result, effective_style + style
     patch on top, called resolved_style. The renderer code then must not have
     access to ChartStylePatch anymore."

Two bans survive as textual sweeps over the chart-emit subtree:

  1. ``ChartStylePatch`` — the board-wide authored patch. Emit code consumes
     resolved style models; only the cascade in ``compile/resolve/style/chart_context.py``
     handles the full chart Patch. The family-specific patches
     (``TableChartStylePatch``, ``BarChartStylePatch``, …) are deliberately
     NOT banned: ``vega_lite.py`` builds a synthetic ``TableChartStylePatch``
     to feed ``build_chart_style_context`` for donut attached-tables, which is
     cascade input, not a renderer reach-back. The typed axis-variant patch
     sentinels (``AxisXStylePatch``, ``AxisYStylePatch``, …) are likewise not
     banned — emit code consumes ``ResolvedChartsStyle`` and these narrow
     per-variant sentinels, never the full chart Patch.
  2. ``chart_local_axis_patch`` / ``axis_overrides_*`` — the PR #2144
     antipattern (parking the full patch on resolved and walking per-axis
     override sentinels at emit time). Render code reads merged axis state via
     ``resolved_axis_style``.

Why a structural test instead of behavior tests alone: the antipattern's whole
shape is "this name must not exist in this directory." Behavior tests pin
specific cases; only a sweep catches new instances added by future refactors.

Deliberately NOT swept: ``chart.style`` / ``resolved.style`` reads. That sweep
was written when emit code received a compiled ``Chart``, so ``chart.style``
meant "reading the authored patch". Emitters now receive a ``Resolved*Chart``
whose ``.style`` is the *resolved* model (``ResolvedBarStyle``, …), and reading
it is exactly what they are supposed to do — the text no longer distinguishes
the antipattern from correct code. Re-adding it would pin ~120 false positives.
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

from ..._paths import DBT_CHARTS_PKG_DIR

RENDER_CHART_DIR = DBT_CHARTS_PKG_DIR / "core" / "render" / "chart"


def _strip_strings_and_comments(source: str) -> str:
    """Return source with string/comment tokens replaced by spaces.

    Lets the sweeps ignore mentions of a banned name inside docstrings,
    comments, and error messages — including a comment that explains the ban
    itself. The antipattern is in code, not commentary.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError:
        return source
    redacted = source.splitlines()
    for tok in tokens:
        if tok.type not in (tokenize.STRING, tokenize.COMMENT):
            continue
        start_row, start_col = tok.start
        end_row, end_col = tok.end
        if start_row == end_row:
            line = redacted[start_row - 1]
            redacted[start_row - 1] = (
                line[:start_col] + " " * (end_col - start_col) + line[end_col:]
            )
        else:
            line = redacted[start_row - 1]
            redacted[start_row - 1] = line[:start_col] + " " * (len(line) - start_col)
            for r in range(start_row, end_row - 1):
                redacted[r] = " " * len(redacted[r])
            line = redacted[end_row - 1]
            redacted[end_row - 1] = " " * end_col + line[end_col:]
    return "\n".join(redacted)


def _emit_files() -> list[Path]:
    return sorted(
        p for p in RENDER_CHART_DIR.rglob("*.py") if "__pycache__" not in p.parts
    )


def _sweep(pattern: re.Pattern[str]) -> list[str]:
    """Return ``path:lineno: source`` for every code (non-comment) match."""
    offenders: list[str] = []
    for path in _emit_files():
        text = path.read_text(encoding="utf-8")
        original_lines = text.splitlines()
        for lineno, line in enumerate(
            _strip_strings_and_comments(text).splitlines(), start=1
        ):
            if pattern.search(line):
                rel = path.relative_to(RENDER_CHART_DIR)
                offenders.append(
                    f"{rel}:{lineno}: {original_lines[lineno - 1].strip()}"
                )
    return offenders


def test_scan_covers_the_emit_subtree() -> None:
    """The bans below are grep sweeps — a scan root that resolves to nothing
    makes every one of them vacuously true. Pin the root so a moved test file
    or a relocated source tree fails loudly here instead of silently
    disarming the guards.
    """
    assert RENDER_CHART_DIR.is_dir(), f"scan root does not exist: {RENDER_CHART_DIR}"
    scanned = _emit_files()
    assert len(scanned) > 20, (
        f"scan root {RENDER_CHART_DIR} yielded {len(scanned)} files — "
        "the chart-emit subtree is much larger than that"
    )


def test_emit_code_does_not_reference_chartstylepatch() -> None:
    """Chart-emit modules must not touch the board-wide ``ChartStylePatch``.

    The only legitimate consumer is the cascade in ``compile/resolve/style/chart_context.py``.
    The subtree currently has zero references, so there is no exclusion list —
    a genuine new boundary case should be argued in review, not pre-approved
    here.
    """
    offenders = _sweep(re.compile(r"\bChartStylePatch\b"))
    assert not offenders, (
        "Emit code references ChartStylePatch — only the cascade in "
        "compile/resolve/style/chart_context.py may consume the authored chart-wide Patch. "
        "Read merged values off the Resolved*Style instead:\n" + "\n".join(offenders)
    )


def test_emit_code_does_not_read_chart_local_axis_patch() -> None:
    """Guard against reintroducing the PR #2144 antipattern: storing the full
    ChartStylePatch on resolved as ``chart_local_axis_patch`` (or walking the
    per-axis ``axis_overrides_*`` sentinels directly) from the renderer.
    Render code reads the merged axis state via ``resolved_axis_style``;
    the override patches are cascade-internal, never consumed at emit time.
    """
    offenders = _sweep(re.compile(r"\bchart_local_axis_patch\b|\baxis_overrides_\w+"))
    assert not offenders, (
        "Renderer references ``chart_local_axis_patch`` — that field is the "
        "PR #2144 antipattern (full ChartStylePatch on resolved). Read the "
        "merged value via ``resolved_axis_style(...)`` instead:\n"
        + "\n".join(offenders)
    )
