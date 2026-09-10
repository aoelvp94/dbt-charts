"""Penalty-driven column packing.

The packer chooses where a line sequence breaks across columns. It follows
TeX's page-breaker model: every candidate break carries a cost, and the split
minimizing total cost wins. Balance is one cost term among several, so a widow
penalty can outrank a small imbalance -- which is the correct trade, and the
reason this is not a chain of if-then rules.
"""

from __future__ import annotations

import pytest

from dbt_charts.core.render.column_packer import (
    MAX_COLUMN_COUNT,
    PackUnit,
    pack_columns,
)


def paragraphs(*counts: int, advance: float = 20.0) -> list[PackUnit]:
    units: list[PackUnit] = []
    for block_id, n in enumerate(counts):
        units += [
            PackUnit(
                advance=advance,
                space_before=20.0 if (i == 0 and block_id > 0) else 0.0,
                block_id=block_id,
                line_index=i,
                line_total=n,
                splittable=True,
                keep_with_next=False,
            )
            for i in range(n)
        ]
    return units


class TestContinuousFlow:
    def test_a_paragraph_splits_across_a_boundary(self) -> None:
        """The whole point: one paragraph may occupy two columns."""
        units = paragraphs(12)
        assignment = pack_columns(units, columns=2)
        cols = set(assignment)
        assert cols == {0, 1}, "both columns must be used"
        # the single block appears in both columns
        blocks_in_0 = {
            u.block_id for u, c in zip(units, assignment, strict=True) if c == 0
        }
        blocks_in_1 = {
            u.block_id for u, c in zip(units, assignment, strict=True) if c == 1
        }
        assert blocks_in_0 == blocks_in_1 == {0}

    def test_lines_stay_in_document_order(self) -> None:
        units = paragraphs(5, 5, 5)
        assignment = pack_columns(units, columns=3)
        assert assignment == sorted(assignment), (
            "a column may not precede its own start"
        )


class TestWidowsAndOrphans:
    def test_no_orphan_first_line_at_a_column_bottom(self) -> None:
        """A paragraph must not contribute exactly its first line to a column."""
        units = paragraphs(4, 9)
        assignment = pack_columns(units, columns=2)
        for col in (0, 1):
            in_col = [u for u, c in zip(units, assignment, strict=True) if c == col]
            for block_id in {u.block_id for u in in_col}:
                lines = [u for u in in_col if u.block_id == block_id]
                total = lines[0].line_total
                if total > 1 and lines[0].line_index == 0 and len(lines) < total:
                    assert len(lines) >= 2, f"orphan in column {col}"

    def test_no_widow_last_line_alone_at_a_column_top(self) -> None:
        units = paragraphs(9, 4)
        assignment = pack_columns(units, columns=2)
        for col in (0, 1):
            in_col = [u for u, c in zip(units, assignment, strict=True) if c == col]
            for block_id in {u.block_id for u in in_col}:
                lines = [u for u in in_col if u.block_id == block_id]
                total = lines[0].line_total
                if (
                    total > 1
                    and lines[-1].line_index == total - 1
                    and len(lines) < total
                ):
                    assert len(lines) >= 2, f"widow in column {col}"


class TestUnsplittableAndKeepWithNext:
    def test_an_unsplittable_block_lands_in_one_column(self) -> None:
        units = paragraphs(6)
        units.append(
            PackUnit(
                advance=90.0,
                space_before=20.0,
                block_id=99,
                line_index=0,
                line_total=1,
                splittable=False,
                keep_with_next=False,
            )
        )
        units += paragraphs(6)
        assignment = pack_columns(units, columns=2)
        cols = {c for u, c in zip(units, assignment, strict=True) if u.block_id == 99}
        assert len(cols) == 1

    def test_a_heading_is_never_last_in_a_column(self) -> None:
        units = paragraphs(7)
        heading_at = len(units)
        units.append(
            PackUnit(
                advance=26.0,
                space_before=30.0,
                block_id=50,
                line_index=0,
                line_total=1,
                splittable=False,
                keep_with_next=True,
            )
        )
        units += paragraphs(7)
        assignment = pack_columns(units, columns=2)
        heading_col = assignment[heading_at]
        after = list(assignment[heading_at + 1 :])
        assert after[:2] == [
            heading_col,
            heading_col,
        ], "a heading must keep at least two following lines with it"


class TestBalance:
    def test_columns_are_balanced_when_nothing_forbids_it(self) -> None:
        units = paragraphs(10, 10)
        assignment = pack_columns(units, columns=2)
        heights = [
            sum(
                u.advance + u.space_before
                for u, c in zip(units, assignment, strict=True)
                if c == k
            )
            for k in (0, 1)
        ]
        assert abs(heights[0] - heights[1]) <= 2 * 20.0

    def test_balance_yields_to_a_widow_penalty(self) -> None:
        """Perfect balance that strands a line must lose to a slightly uneven split."""
        units = paragraphs(11, 11)
        assignment = pack_columns(units, columns=2)
        first_col_blocks = [
            u
            for u, c in zip(units, assignment, strict=True)
            if c == 0 and u.block_id == 1
        ]
        # if block 1 appears in column 0 at all, it must bring >= 2 lines
        if first_col_blocks:
            assert len(first_col_blocks) >= 2


class TestColumnOrder:
    def test_column_heights_are_non_increasing(self) -> None:
        """An uneven remainder belongs in the earlier column, never the later.

        Text is read top-left first, so a short first column beside a long
        second one reads as a mistake. A flat undershoot surcharge cannot
        express this -- every split has as many short columns as long ones --
        so the packer weights the surcharge by how early the column is.
        """
        for total in (7, 9, 11, 13, 15, 21):
            assignment = pack_columns(paragraphs(total), columns=2)
            heights = [assignment.count(k) for k in range(2)]
            assert heights == sorted(heights, reverse=True), (
                f"{total} lines split {heights}; earlier column must not be shorter"
            )

    def test_non_increasing_holds_for_three_columns(self) -> None:
        for total in (10, 14, 17, 20):
            assignment = pack_columns(paragraphs(total), columns=3)
            heights = [assignment.count(k) for k in range(3)]
            assert heights == sorted(heights, reverse=True), (
                f"{total} lines split {heights}"
            )


class TestViableColumnCount:
    def test_short_passages_stay_single_column(self) -> None:
        """Two columns of one line each is not a two-column layout."""
        from dbt_charts.core.render.column_packer import viable_column_count

        for lines in (1, 2, 4, 5):
            assert viable_column_count(lines, requested=3) == 1

    def test_count_steps_down_until_columns_are_worth_having(self) -> None:
        from dbt_charts.core.render.column_packer import (
            MIN_LINES_PER_COLUMN,
            viable_column_count,
        )

        assert viable_column_count(2 * MIN_LINES_PER_COLUMN, requested=3) == 2
        assert viable_column_count(3 * MIN_LINES_PER_COLUMN, requested=3) == 3

    def test_never_exceeds_what_the_width_allows(self) -> None:
        from dbt_charts.core.render.column_packer import viable_column_count

        assert viable_column_count(500, requested=2) == 2


class TestMeasurePlan:
    """Choosing the column count from the measure, not from ceil()."""

    def test_every_common_board_width_lands_in_the_readable_band(self) -> None:
        from dbt_charts.core.render.column_packer import plan_measure

        for slot in (1096.0, 900.0, 840.0, 672.0, 533.0, 460.0, 400.0, 320.0):
            plan = plan_measure(
                slot, char_width=6.146, gutter=29.4, ceiling=MAX_COLUMN_COUNT
            )
            chars = plan.column_width / 6.146
            assert 45 <= chars <= 80, f"{slot}px slot delivered {chars:.0f} chars"

    def test_it_fills_the_slot_whenever_an_integer_count_can(self) -> None:
        from dbt_charts.core.render.column_packer import plan_measure

        plan = plan_measure(
            1096.0, char_width=6.146, gutter=29.4, ceiling=MAX_COLUMN_COUNT
        )
        used = plan.columns * plan.column_width + (plan.columns - 1) * 29.4
        assert used == pytest.approx(1096.0, abs=1.0)
        assert plan.column_width * plan.columns > 1000, "the slot is filled"

    def test_multi_column_aims_at_66_not_at_the_cap(self) -> None:
        """Sustained reading accumulates return sweeps, so columns stay tight."""
        from dbt_charts.core.render.column_packer import plan_measure

        plan = plan_measure(
            1096.0, char_width=6.146, gutter=29.4, ceiling=MAX_COLUMN_COUNT
        )
        assert plan.columns > 1
        assert plan.column_width / 6.146 < 75

    def test_a_single_column_may_run_to_the_wcag_cap(self) -> None:
        """One column of few lines makes few sweeps, so it keeps more slot.

        533px gives 87 characters at one column and 41 at two -- neither is
        readable, so the measure wins. Capping at 80 rather than 66 leaves 41px
        of white space instead of 127px.
        """
        from dbt_charts.core.render.column_packer import plan_measure

        plan = plan_measure(
            533.0, char_width=6.146, gutter=29.4, ceiling=MAX_COLUMN_COUNT
        )
        assert plan.columns == 1
        assert plan.column_width < 533.0, "the remainder stays white space"
        assert plan.column_width / 6.146 == pytest.approx(80.0, abs=1.0)

    def test_a_short_passage_gets_a_narrow_column_not_the_whole_slot(self) -> None:
        """Length is no excuse for line length -- 1096px is 178 characters."""
        from dbt_charts.core.render.column_packer import plan_measure

        plan = plan_measure(1096.0, char_width=6.146, gutter=29.4, ceiling=1)
        assert plan.columns == 1
        assert plan.column_width / 6.146 == pytest.approx(80.0, abs=1.0)
        assert plan.column_width < 1096.0, "the remainder stays white space"

    def test_ceiling_never_raises_the_count(self) -> None:
        from dbt_charts.core.render.column_packer import plan_measure

        wide = plan_measure(
            1096.0, char_width=6.146, gutter=29.4, ceiling=MAX_COLUMN_COUNT
        )
        held = plan_measure(1096.0, char_width=6.146, gutter=29.4, ceiling=2)
        assert held.columns <= 2 < wide.columns + 1


class TestNarrowSlots:
    """A planned column must fit the slot it was planned for.

    Below the readable floor there is no good answer: the slot cannot hold a
    45-character line. The slot still wins, because a cramped line is a bad
    result and a clipped one is a destroyed result -- the containing SVG is a
    viewport, so anything wider than the slot is silently cut off, not spilled.
    """

    @pytest.mark.parametrize(
        "slot", [600.0, 500.0, 400.0, 340.0, 300.0, 260.0, 220.0, 180.0, 120.0]
    )
    def test_planned_columns_never_exceed_the_slot(self, slot: float) -> None:
        from dbt_charts.core.render.column_packer import plan_measure

        plan = plan_measure(
            slot, char_width=6.494, gutter=29.4, ceiling=MAX_COLUMN_COUNT
        )
        used = plan.columns * plan.column_width + (plan.columns - 1) * 29.4
        assert used <= slot + 0.5, (
            f"{slot:.0f}px slot planned {plan.columns} column(s) of "
            f"{plan.column_width:.0f}px -- text would be clipped, not wrapped"
        )
