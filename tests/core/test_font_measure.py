import pytest


def test_neutral_font_measurer_reuses_one_process_cache():
    from dbt_charts.core import font_measure

    font_measure._font_measurers.clear()
    first = font_measure.get_font_measurer("Inter")
    second = font_measure.get_font_measurer("Inter")

    assert second is first
    assert len(font_measure._font_measurers) == 1


def test_neutral_font_measurer_propagates_strict_loading_errors(monkeypatch):
    from dbt_charts.core import font_measure

    def fail(_font_path: str):
        raise RuntimeError("boom")

    monkeypatch.setattr(font_measure, "_load_measurer", fail)

    with pytest.raises(RuntimeError, match="boom"):
        font_measure.get_font_measurer("Inter")


@pytest.mark.parametrize(
    ("weight", "expected"),
    [("normal", 400.0), ("bold", 700.0), ("bolder", 700.0), ("lighter", 300.0)],
)
def test_css_weight_to_axis_accepts_the_full_css_keyword_vocabulary(weight, expected):
    """Regression: 'bolder'/'lighter' are legal CSS font-weight keywords
    (CSS Fonts Module Level 4) and ResolvedFontStyle.weight is untyped
    str, so an author can legally write either -- css_weight_to_axis used
    to fall through to float('bolder') and raise a bare ValueError.
    """
    from dbt_charts.core.font_measure import css_weight_to_axis

    assert css_weight_to_axis(weight) == expected


def test_centered_baseline_offset_is_the_face_s_own_ascent_descent_split():
    """A centred line's content box straddles the middle, so the baseline sits
    ``(ascent - descent) / 2`` below it -- the face's ratio, not a constant.

    Read off the loaded face rather than pinned to a number: the value it
    replaced (``font_size * 0.35``) was one family's ratio applied to every
    other, and a test asserting a number would be the same mistake.
    """
    from dbt_charts.core.font_measure import centered_baseline_offset, get_font_measurer

    measurer = get_font_measurer("Inter")
    expected = (measurer.ascent_em - measurer.descent_em) / 2

    for size in (11.0, 24.0):
        assert centered_baseline_offset("Inter", size) == pytest.approx(expected * size)


def test_centered_baseline_offset_differs_between_two_vendored_faces():
    """It has to read the face, and this fails if it goes back to a constant."""
    from dbt_charts.core.font_measure import centered_baseline_offset

    assert centered_baseline_offset("Inter", 14.0) != pytest.approx(
        centered_baseline_offset("Source Serif 4", 14.0)
    )
