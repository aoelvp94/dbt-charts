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
