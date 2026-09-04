"""AST counter for type-state rot in ``dbt_charts/core``, marker-aware.

The 2026-06 retro named the rot that makes AI-assisted work on dbt_charts.core fragile:
``| Any`` typed up to the render entrypoint, ``Optional`` / ``| None`` sprawl, and
silent fallbacks (``x or DEFAULT``, ``d.get(k, default)``, ``getattr(o, a, d)``)
where the merged config should be the single source of truth and a missing value
should *error*. Three further categories guard against Goodhart dodges that make a
count drop without typing anything: ``cast(...)`` calls, ``# type: ignore``
comments, and ``object`` used as a type annotation.

``count_type_state`` locates every rot site in one module's source and reports,
per category, the total and the *unmarked* total — the count that excludes sites
carrying a ``# type-state: <category> — <reason>`` marker on any line of the
site's span. Only the unmarked count is meaningful for gating: a marker is a
reviewed, reasoned exception (grammar matches this repo's ``# noqa: BLE001 —
<reason>`` convention), not a silent default.

This module has no pytest dependency — ``scripts/type_state_gate.py`` imports it
to compare ``dbt_charts/core`` at a merge base against HEAD, and
``tests/scripts/test_type_state_counter.py`` imports it for the detector's unit
tests.

The detector is intentionally approximate: it accepts false positives rather
than trying to be a perfect classifier. This matters more here than it did for
the freeze-floor ratchet this module replaced — that gate only forbade
*growth* against a baseline, so a false positive just held the line; this gate
blocks on *existence* on a touched line, so a false positive blocks the PR
outright. The escape hatch is the same either way: a reviewed
``# type-state: <category> — <reason>`` marker.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from collections.abc import Iterator
from dataclasses import dataclass

CATEGORIES = (
    "explicit_any",
    "optional",
    "silent_fallback",
    "cast",
    "type_ignore",
    "object_annotation",
)

# Literal node types that, as the right-hand side of `x or <literal>`, mark a
# silent default. `None` is excluded — `x or None` normalizes, it doesn't default.
_LITERAL_NODES = (ast.Constant, ast.Dict, ast.List, ast.Set, ast.Tuple)

# `# type: ignore` comments are dropped by the AST, so detect them from COMMENT
# tokens instead. Anchored at the token's start OR a `#` inside it — pyright
# honors the pragma wherever it appears in a comment (`# noqa: E501  # type:
# ignore[...]`, `## type: ignore`), so anchoring only at `^` would miss both.
# A comment that merely *mentions* the pragma in prose without a `#` right
# before it (`# see also type: ignore for context`) must still not create a
# phantom site with no pragma anywhere to mark.
_TYPE_IGNORE_RE = re.compile(r"(?:^|#)\s*type:\s*ignore")

# `# type-state: <category> — <reason>`. The separator group matches the
# em-dash this repo's `# noqa: BLE001 — <reason>` convention uses, plus the
# en-dash and hyphen an author is likely to type instead (the root AGENTS.md
# "never use em or en dashes" instruction makes a hyphen the default guess) —
# `_parse_markers` hard-errors on anything but the em-dash rather than
# silently treating the marker as absent. The reason group is optional in the
# regex itself so a marker missing it still parses far enough to validate the
# category name — a typo'd category must raise, not silently approve nothing.
_MARKER_RE = re.compile(
    r"#\s*type-state:\s*(?P<category>[A-Za-z_]+)(?:\s*(?P<sep>[—–-])\s*(?P<reason>.*))?"
)
_EM_DASH = "—"


@dataclass(frozen=True)
class Site:
    """One rot occurrence's line span, 1-indexed and end-inclusive."""

    lineno: int
    end_lineno: int


@dataclass(frozen=True)
class FileCounts:
    """Per-category totals and unmarked sites for one module's source."""

    totals: dict[str, int]
    unmarked_sites: dict[str, list[Site]]

    @property
    def unmarked(self) -> dict[str, int]:
        return {category: len(sites) for category, sites in self.unmarked_sites.items()}


def _is_none(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _fallback_call_delta(node: ast.Call) -> int:
    """1 if the call is a `.get(k, default)` or 3-arg `getattr(o, a, default)`."""
    func = node.func
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "get"
        and len(node.args) == 2
        and not node.keywords
    ):
        return 1
    if isinstance(func, ast.Name) and func.id == "getattr" and len(node.args) == 3:
        return 1
    return 0


def _annotation_nodes(tree: ast.AST) -> Iterator[ast.expr]:
    """Yield every annotation expression (arg, return type, and AnnAssign)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.annotation is not None:
            yield node.annotation
        elif (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.returns is not None
        ):
            yield node.returns
        elif isinstance(node, ast.AnnAssign):
            yield node.annotation


def _span(node: ast.expr) -> Site:
    # Parsed source always carries end_lineno; only hand-built AST nodes omit it.
    assert node.end_lineno is not None, "parsed AST node missing end_lineno"
    return Site(node.lineno, node.end_lineno)


def _find_sites(source: str) -> dict[str, list[Site]]:
    """Locate every rot site in one module's source, grouped by category."""
    sites: dict[str, list[Site]] = {category: [] for category in CATEGORIES}
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Name) and node.id == "Any") or (
            isinstance(node, ast.Attribute) and node.attr == "Any"
        ):
            sites["explicit_any"].append(_span(node))

        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "Optional"
        ):
            sites["optional"].append(_span(node))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            if _is_none(node.left) or _is_none(node.right):
                sites["optional"].append(_span(node))

        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            last = node.values[-1]
            if isinstance(last, _LITERAL_NODES) and not _is_none(last):
                sites["silent_fallback"].append(_span(node))
        elif isinstance(node, ast.Call) and _fallback_call_delta(node):
            sites["silent_fallback"].append(_span(node))

        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Name) and func.id == "cast") or (
                isinstance(func, ast.Attribute) and func.attr == "cast"
            ):
                sites["cast"].append(_span(node))

    # Anti-dodge: `: object` / `-> object` swaps Any for an equally-untyped
    # escape hatch. Count `object` only in annotation position (not base
    # classes or isinstance checks).
    for annotation in _annotation_nodes(tree):
        for sub in ast.walk(annotation):
            if isinstance(sub, ast.Name) and sub.id == "object":
                sites["object_annotation"].append(_span(sub))

    # Anti-dodge: `# type: ignore` forces a wrong type through. Comments are
    # not in the AST, so scan COMMENT tokens directly — the same discipline
    # `_parse_markers` uses, and for the same reason: a string literal or
    # docstring merely containing this text must not create a site.
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT and _TYPE_IGNORE_RE.search(token.string):
            lineno = token.start[0]
            sites["type_ignore"].append(Site(lineno, lineno))

    return sites


def _parse_markers(source: str) -> dict[int, str]:
    """Map line number (1-indexed) to the approved category on that line.

    Scans ``COMMENT`` tokens only, not raw text — a marker-shaped string
    inside a string literal or docstring must not parse as an approval, and a
    typo'd category inside a docstring (now a realistic thing to write, since
    ``dbt-charts/AGENTS.md`` documents the marker) must not hard-error the gate.
    An unrecognized category name, a separator that isn't the em-dash, or a
    missing/blank reason, in a real comment, is a hard error, not a silent
    miss — a typo must not look like an approval, neither must the wrong
    dash, and neither must a bare ``# type-state: <category>`` with nothing
    to review: a candidate line already holding a reasonless marker would
    otherwise look "free" to ``suggest_marker_line``, and a second marker
    pasted there is silently swallowed into the first marker's COMMENT token.
    """
    markers: dict[int, str] = {}
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        match = _MARKER_RE.search(token.string)
        if match is None:
            continue
        lineno = token.start[0]
        category = match.group("category")
        if category not in CATEGORIES:
            raise ValueError(
                f"Unknown type-state category {category!r} on line {lineno}: "
                f"{token.string.strip()}"
            )
        sep = match.group("sep")
        if sep is not None and sep != _EM_DASH:
            raise ValueError(
                f"type-state marker on line {lineno} uses {sep!r} instead of an "
                f"em-dash (—): {token.string.strip()}. Use "
                f"`# type-state: {category} — <reason>`."
            )
        reason = match.group("reason")
        if reason is None or not reason.strip():
            raise ValueError(
                f"type-state marker on line {lineno} has no reason: "
                f"{token.string.strip()}. Use "
                f"`# type-state: {category} — <reason>`."
            )
        markers[lineno] = category
    return markers


def _approve_sites(
    sites: list[Site], markers: dict[int, str], category: str
) -> list[Site]:
    """Consume each ``(lineno, category)`` marker against at most one site.

    Sites are matched narrowest-span first, so a marker on a multi-line call's
    closing line approves the innermost site covering it before a wider
    enclosing site can also claim it — one marker on one line must not
    silently approve every same-category site whose span happens to reach
    that line (ordinary formatting puts several `Any` annotations on one
    `def` line). The sort key is `(width, lineno, end_lineno)`, so ties (equal
    span width, e.g. several single-line sites on one line) break on `lineno`,
    then `end_lineno` — not on `_find_sites`' discovery order, which only
    survives as a tiebreaker for fully identical spans.
    """
    available = {lineno for lineno, marked in markers.items() if marked == category}
    narrowest_first = sorted(
        sites,
        key=lambda site: (site.end_lineno - site.lineno, site.lineno, site.end_lineno),
    )
    unmarked: list[Site] = []
    for site in narrowest_first:
        marker_line = next(
            (ln for ln in range(site.lineno, site.end_lineno + 1) if ln in available),
            None,
        )
        if marker_line is not None:
            available.discard(marker_line)
        else:
            unmarked.append(site)
    return sorted(unmarked, key=lambda site: (site.lineno, site.end_lineno))


def suggest_marker_line(source: str, category: str, site: Site) -> int | None:
    """A line inside *site*'s span where a new marker actually approves *site*.

    ``_approve_sites`` matches narrowest-span-first, so a marker on *site*'s
    own first line is not always followable: a narrower same-category
    sibling whose span also reaches that line is processed first and
    consumes it, leaving *site* still unmarked (a chained ``.get()`` ladder
    produces exactly this shape — three nested calls all starting on line 1
    but ending on different lines). Rather than deriving "narrower" as a
    local width comparison — ambiguous the moment two sites share an
    identical span, which is also the case the caller's explode-instruction
    already owns — this simulates pasting a marker at each candidate line
    and asks the real algorithm who claims it, using the file's actual other
    sites and markers as the background.

    Returns ``None`` when no line in the span resolves to *site* — every
    line is already claimed by a narrower (or identically-spanned) sibling,
    and the caller should tell the contributor to explode the statement
    instead of pointing at an unfollowable line.
    """
    sites = _find_sites(source)[category]
    markers = _parse_markers(source)
    for candidate in range(site.lineno, site.end_lineno + 1):
        if candidate in markers:
            continue
        trial_markers = dict(markers)
        trial_markers[candidate] = category
        if site not in _approve_sites(sites, trial_markers, category):
            return candidate
    return None


def count_type_state(source: str) -> FileCounts:
    """Count rot sites in one module's source, split into totals and unmarked."""
    sites = _find_sites(source)
    markers = _parse_markers(source)
    totals = {category: len(site_list) for category, site_list in sites.items()}
    unmarked_sites = {
        category: _approve_sites(site_list, markers, category)
        for category, site_list in sites.items()
    }
    return FileCounts(totals=totals, unmarked_sites=unmarked_sites)
