"""Runt control: a paragraph's last line should not hold a single short word.

A runt is a wrapping problem, not a packing one -- it is fixed by choosing a
different break inside the paragraph, not by moving lines between boxes. Off by
default: this wrapper is shared by every consumer of a published package.
"""

from __future__ import annotations

from mdsvg.fonts import WrapPiece, wrap_measured_pieces


def pieces(*widths: float) -> list[WrapPiece]:
    return [
        WrapPiece(
            text="w" * int(w),
            width=w,
            separator=" " if i else "",
            separator_width=4.0 if i else 0.0,
            meta=None,
        )
        for i, w in enumerate(widths)
    ]


class TestRuntControl:
    def test_off_by_default_leaves_a_single_word_last_line(self) -> None:
        lines = wrap_measured_pieces(pieces(40, 40, 40), max_width=100.0)
        assert len(lines[-1]) == 1, "default wrapping is unchanged"

    def test_enabled_pulls_a_word_down_to_the_last_line(self) -> None:
        lines = wrap_measured_pieces(
            pieces(40, 40, 40), max_width=100.0, avoid_runts=True
        )
        assert len(lines[-1]) >= 2, "last line must not be a lone word"

    def test_never_overflows_the_measure(self) -> None:
        lines = wrap_measured_pieces(
            pieces(40, 40, 40), max_width=100.0, avoid_runts=True
        )
        for line in lines:
            width = sum(p.width for p in line) + sum(
                p.separator_width for p in line[1:]
            )
            assert width <= 100.0 + 1e-9

    def test_single_line_paragraph_is_left_alone(self) -> None:
        lines = wrap_measured_pieces(pieces(30), max_width=100.0, avoid_runts=True)
        assert len(lines) == 1 and len(lines[0]) == 1

    def test_gives_up_rather_than_strand_the_penultimate_line(self) -> None:
        """Moving the only word off a two-word line would just relocate the runt."""
        lines = wrap_measured_pieces(pieces(90, 20), max_width=100.0, avoid_runts=True)
        assert [len(line) for line in lines] == [1, 1]
