"""Unit coverage for boards._dedupe_repeated_style_rules -- the purely textual
pass over a fully assembled board SVG that collapses CSS rule lines repeated
across `<style>` blocks. Safe because mdsvg's own class scoping
(`SVGRenderer._scoped_class`) names every `.md-*` rule from a hash of its own
style, so a byte-identical line always means an identical rule.
"""

from __future__ import annotations

from dbt_charts.core.render.boards import _dedupe_repeated_style_rules


def _style_block(*lines: str) -> str:
    return "  <style>\n" + "\n".join(lines) + "\n  </style>"


def test_identical_rule_in_two_blocks_collapses_to_one() -> None:
    line = "    .md-abc12345-text { fill: #111111; }"
    svg = f"<svg>{_style_block(line)}<g/>{_style_block(line)}</svg>"

    result = _dedupe_repeated_style_rules(svg)

    assert result.count("<style>") == 1
    assert result.count(line) == 1


def test_partial_overlap_keeps_only_the_new_lines() -> None:
    shared = "    .md-abc12345-mono { font-family: monospace; }"
    only_first = "    .md-abc12345-text { fill: #111111; }"
    only_second = "    .md-def45678-text { fill: #222222; }"
    svg = (
        f"<svg>{_style_block(shared, only_first)}<g/>"
        f"{_style_block(shared, only_second)}</svg>"
    )

    result = _dedupe_repeated_style_rules(svg)

    assert result.count(shared) == 1
    assert only_first in result
    assert only_second in result
    assert result.count("<style>") == 2


def test_block_left_with_no_lines_is_removed_entirely() -> None:
    line = "    .md-abc12345-text { fill: #111111; }"
    svg = f"<svg>{_style_block(line)}<g/>{_style_block(line)}</svg>"

    result = _dedupe_repeated_style_rules(svg)

    assert result.count("<style>") == 1
    # The second, now-empty block leaves nothing behind at its own position.
    assert result == f"<svg>{_style_block(line)}<g/></svg>"


def test_unrelated_content_is_untouched() -> None:
    svg = '<svg><text class="md-abc12345-text">Hello</text></svg>'

    assert _dedupe_repeated_style_rules(svg) == svg


def test_a_selector_with_no_embedded_hash_is_never_deduped() -> None:
    """Defends the eligibility regex's specificity: `.md-text` (no hash
    segment) never matches, only `.md-<hash>-text` does. mdsvg no longer
    emits the bare form anywhere, but the pass must not treat a plain-looking
    `.md-*` selector as eligible just because it starts with the same
    prefix -- only a genuinely content-addressed name is safe to collapse."""
    line = "    .md-text { font-family: serif; fill: #222222; }"
    svg = f"<svg>{_style_block(line)}<g/>{_style_block(line)}</svg>"

    result = _dedupe_repeated_style_rules(svg)

    assert result.count("<style>") == 2
    assert result.count(line) == 2


def test_distinct_rules_are_all_kept() -> None:
    line_a = "    .md-abc12345-text { fill: #111111; }"
    line_b = "    .md-def45678-text { fill: #222222; }"
    svg = f"<svg>{_style_block(line_a)}<g/>{_style_block(line_b)}</svg>"

    result = _dedupe_repeated_style_rules(svg)

    assert result.count("<style>") == 2
    assert line_a in result
    assert line_b in result


def test_no_style_block_leaves_no_blank_line_behind() -> None:
    """A fully-emptied block's own leading newline is consumed too, not just
    its tag lines -- otherwise every collapsed block leaves a stray blank
    line at its old position in the shipped output."""
    line = "    .md-abc12345-text { fill: #111111; }"
    svg = f"<svg>\n{_style_block(line)}<g/>\n{_style_block(line)}</svg>"

    result = _dedupe_repeated_style_rules(svg)

    assert result == f"<svg>\n{_style_block(line)}<g/></svg>"


def test_same_rule_in_two_separate_nested_svgs_is_not_deduped() -> None:
    """Regression: a per-chart "download as SVG/PNG/PDF" feature
    (apps/cloud/static_src/js/dashboard/init.js) walks up from a chart's own
    element to its *nearest* ancestor `<svg>` and treats that subtree as a
    standalone document, copying only the `<style>` nodes found within it.
    Two sibling nested `<svg>` elements (e.g. two columns of a nested-board
    layout) sharing an identical rule must each keep their own copy -- a
    downloaded chart from the second subtree would otherwise ship with no
    matching rule at all, even though the two subtrees look identical here."""
    line = "    .md-abc12345-text { fill: #111111; }"
    svg = (
        "<svg>"
        f'<svg width="1">{_style_block(line)}<text/></svg>'
        f'<svg width="2">{_style_block(line)}<text/></svg>'
        "</svg>"
    )

    result = _dedupe_repeated_style_rules(svg)

    assert result.count(line) == 2


def test_rule_in_an_ancestor_svg_does_not_cover_a_nested_svg() -> None:
    """A rule kept at the board root (or any ancestor `<svg>`) is not visible
    to the same download feature when it extracts a *nested* `<svg>` -- the
    nested subtree needs its own copy even though the outer one already has
    the identical rule."""
    line = "    .md-abc12345-text { fill: #111111; }"
    svg = f'<svg>{_style_block(line)}<svg width="1">{_style_block(line)}<text/></svg></svg>'

    result = _dedupe_repeated_style_rules(svg)

    assert result.count(line) == 2


def test_two_rules_in_the_same_nested_svg_still_dedupe() -> None:
    """The common case this pass exists for -- two charts sharing a style
    inside the *same* extractable `<svg>` subtree (e.g. two callouts on one
    board) -- still collapses, whether that subtree is the board root or a
    nested board column."""
    line = "    .md-abc12345-text { fill: #111111; }"
    svg = f'<svg width="1">{_style_block(line)}<text/>{_style_block(line)}<text/></svg>'

    result = _dedupe_repeated_style_rules(svg)

    assert result.count(line) == 1
