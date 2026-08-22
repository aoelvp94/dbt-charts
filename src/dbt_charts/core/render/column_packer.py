"""Penalty-driven column packing for flowed prose.

Chooses where a sequence of lines breaks across columns. The model is TeX's
page breaker rather than a set of rules: every candidate break carries a cost,
and the assignment minimising total cost wins.

Rules-with-precedence and penalties differ in an important way. Rules need an
explicit conflict order, and when no break satisfies all of them they have no
answer. Penalties resolve conflicts by arithmetic and always have an answer --
the least-bad one. That matters because widow avoidance, keep-with-next and
column balance routinely cannot all hold at once on real prose.

Balance is therefore a cost *term*, not a constraint. Print convention accepts
a ragged column bottom to avoid a stranded line, and encoding balance as an
assertion would invert that.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Not a tunable: infinity is how the DP spells "this break is illegal".
_FORBIDDEN = math.inf

# Deliberately hard-coded, not exposed to dbt_charts.yml (Dave, 2026-08-10):
# these are engine internals, not project-facing tuning. Do not "restore" them
# to typed config on the strength of core/AGENTS.md's general
# constants-belong-in-config guidance -- that guidance is overridden here.

# A column must earn this many lines to exist -- two columns of one line each
# is not a two-column layout.
MIN_LINES_PER_COLUMN = 6

# Most columns the search will consider. The measure caps the count long
# before this on any real board -- a bound on the search, not a design choice.
MAX_COLUMN_COUNT = 6

# Characters per line for flowed body prose. Bringhurst gives 66 as the ideal
# measure and 45-75 as satisfactory; WCAG 1.4.8 caps line length at 80. A
# single column aims higher than several: the cost of a long measure is the
# return sweep, and that cost accumulates with the depth of the passage, so a
# short passage held to one column can afford the ceiling.
_MULTI_COLUMN_AIM_CHARS = 66
_SINGLE_COLUMN_CHARS = 80
_MIN_CHARS = 45
# Ceiling for the multi-column readable band. Distinct from the authored
# TextColumnStyle.max_chars field, which means "the measure, used exactly" --
# this is the band this search will accept when picking a count on its own.
_MULTI_COLUMN_CEILING_CHARS = 75

# What each candidate column break costs the packer. Only the ratios carry
# meaning: a stranded line has to outrank the imbalance that avoiding it
# creates, which is why the line penalties sit three orders of magnitude
# above the balance terms below. Orphan and widow are kept as distinct
# constants (both 3000.0) rather than merged -- they are different
# typographic concepts (a paragraph's first line alone at a column foot vs.
# its last line alone at a column top), even though today they cost the same.
# Candidates for future exposure under `text:`, not `text.column:` -- orphans
# and widows apply to any fragmentation, not just columns (the same scope CSS
# uses).
_ORPHAN_PENALTY = 3000.0
_WIDOW_PENALTY = 3000.0
_INTERIOR_BREAK_PENALTY = 1.0  # mid-paragraph: fine, mildly preferred against
_BLOCK_BREAK_PENALTY = 0.0  # between blocks: the natural break

# Weight on squared height deviation, and the scale that puts it in the same
# units as the penalties above. Undershoot is surcharged more than overshoot,
# weighted by how early the column is, so an uneven remainder lands late.
_BALANCE_SCALE = 100.0
_BALANCE_UNDERSHOOT = 0.35


def viable_column_count(line_count: int, requested: int) -> int:
    """Largest column count up to ``requested`` that keeps columns worth having.

    Width alone decides how many columns *fit*; this decides how many are worth
    using given how much text there actually is. Two columns of one line each
    is not a two-column layout, and a short passage does not need columns
    anyway -- a long measure only punishes the reader once there are enough
    return sweeps for the cost to accumulate.
    """
    if requested <= 1 or line_count <= 0:
        return 1
    return max(1, min(requested, line_count // MIN_LINES_PER_COLUMN))


@dataclass(frozen=True)
class MeasurePlan:
    """How a slot divides into columns of readable width.

    ``columns * column_width + (columns - 1) * gutter`` may fall short of the
    slot. Some widths admit no integer count with a readable measure -- 533px
    gives 87 characters at one column and 41 at two -- and there the measure
    wins and the remainder stays white space, because unreadable type is a
    worse outcome than an unused strip.
    """

    columns: int
    column_width: float


def plan_measure(
    available: float,
    char_width: float,
    gutter: float,
    ceiling: int,
) -> MeasurePlan:
    """Divide ``available`` into columns whose measure reads well.

    Picks the count landing nearest the target, preferring to fill the slot.
    ``ceil(available / target_width)`` -- an earlier rule -- rounds up, so an
    840px slot became three columns of 42 characters when two of 66 were
    available.

    ``ceiling`` holds the count down when there is not enough text to fill
    more; it never raises it. Width is recomputed at the held count, so fewer
    columns means a capped measure and white space, not a wider line.
    """
    readable: list[tuple[float, int, float]] = []
    for count in range(1, ceiling + 1):
        width = (available - (count - 1) * gutter) / count
        if width <= 0.0:
            break
        single = count == 1
        aim = _SINGLE_COLUMN_CHARS if single else _MULTI_COLUMN_AIM_CHARS
        band_ceiling = _SINGLE_COLUMN_CHARS if single else _MULTI_COLUMN_CEILING_CHARS
        chars = width / char_width
        if _MIN_CHARS <= chars <= band_ceiling:
            readable.append((abs(chars - aim), count, width))
    if readable:
        _, count, width = min(readable)
        return MeasurePlan(columns=count, column_width=width)

    # Nothing fit the band. The measure wins over the slot: set columns at the
    # target width and leave the remainder as white space, because unreadable
    # type is a worse outcome than an unused strip.
    capped_width = _MULTI_COLUMN_AIM_CHARS * char_width
    count = max(1, min(ceiling, int((available + gutter) // (capped_width + gutter))))
    if count == 1:
        capped_width = _SINGLE_COLUMN_CHARS * char_width
    # Except it must never win past the slot's own edge. A slot narrower than
    # the readable floor has no good answer, and the least-bad one is a cramped
    # line: the containing SVG is a viewport, so a column wider than its slot is
    # silently clipped mid-word rather than spilled. Losing the reader's text is
    # worse than setting it tight.
    fits = (available - (count - 1) * gutter) / count
    return MeasurePlan(columns=count, column_width=min(capped_width, fits))


@dataclass(frozen=True)
class PackUnit:
    """One placeable line, or one whole unsplittable block.

    An unsplittable block reports itself as a single unit whose ``advance`` is
    its full height, so the packer treats every input the same way.
    """

    advance: float
    space_before: float
    block_id: int
    line_index: int
    line_total: int
    splittable: bool
    keep_with_next: bool

    @property
    def height(self) -> float:
        return self.advance + self.space_before


def _break_penalty(units: list[PackUnit], i: int) -> float:
    """Cost of breaking the column immediately after ``units[i]``."""
    if i >= len(units) - 1:
        return _FORBIDDEN  # nothing follows; not a real break point
    here, nxt = units[i], units[i + 1]

    # Never split an unsplittable block, and never separate a heading from the
    # opening of the text it introduces.
    if here.block_id == nxt.block_id and not here.splittable:
        return _FORBIDDEN
    if here.keep_with_next:
        return _FORBIDDEN
    if i >= 1 and units[i - 1].keep_with_next:
        return _FORBIDDEN  # only one line would follow the heading

    if here.block_id != nxt.block_id:
        return _BLOCK_BREAK_PENALTY

    # Same paragraph: how many of its lines fall either side of the break?
    before = here.line_index + 1
    after = here.line_total - before
    if before == 1:
        return _ORPHAN_PENALTY
    if after == 1:
        return _WIDOW_PENALTY
    return _INTERIOR_BREAK_PENALTY


def pack_columns(units: list[PackUnit], columns: int) -> list[int]:
    """Assign each unit to a column index, minimising total cost.

    Returns a list parallel to ``units``. Assignments are non-decreasing: a
    column never contains a unit that precedes one in an earlier column.
    """
    n = len(units)
    if n == 0:
        return []
    if columns <= 1:
        return [0] * n

    prefix = [0.0]
    for u in units:
        prefix.append(prefix[-1] + u.height)
    target = prefix[n] / columns

    penalty = [_break_penalty(units, i) for i in range(n)]

    # best[k][i] = min cost of placing units[:i] into k columns.
    inf = math.inf
    best = [[inf] * (n + 1) for _ in range(columns + 1)]
    take = [[0] * (n + 1) for _ in range(columns + 1)]
    best[0][0] = 0.0

    for k in range(1, columns + 1):
        for i in range(1, n + 1):
            # column k spans units[j:i]
            for j in range(k - 1, i):
                prior = best[k - 1][j]
                if prior == inf:
                    continue
                # cost of the break that ended the previous column
                brk = 0.0 if j == 0 else penalty[j - 1]
                if brk == inf:
                    continue
                height = prefix[i] - prefix[j]
                deviation = height - target
                normaliser = target * target
                cost = prior + brk
                if normaliser > 0.0:
                    earliness = columns - k + 1
                    lopsided = (
                        1.0 + _BALANCE_UNDERSHOOT * earliness
                        if deviation < 0.0
                        else 1.0
                    )
                    cost += (
                        lopsided * _BALANCE_SCALE * (deviation * deviation) / normaliser
                    )
                if cost < best[k][i]:
                    best[k][i] = cost
                    take[k][i] = j

    # Recover the split. If every arrangement was forbidden, fall back to an
    # even division rather than failing -- a rendered board beats an exception,
    # and the penalties have already been given their chance.
    if best[columns][n] == inf:
        per = math.ceil(n / columns)
        return [min(i // per, columns - 1) for i in range(n)]

    bounds = [n]
    i = n
    for k in range(columns, 0, -1):
        i = take[k][i]
        bounds.append(i)
    bounds.reverse()

    assignment = [0] * n
    for col in range(columns):
        for idx in range(bounds[col], bounds[col + 1]):
            assignment[idx] = col
    return assignment
