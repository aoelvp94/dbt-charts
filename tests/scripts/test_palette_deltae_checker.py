from __future__ import annotations

import importlib.util
import sys

import pytest

from .._paths import DBT_CHARTS_DIR

_spec = importlib.util.spec_from_file_location(
    "palette_deltae_checker", DBT_CHARTS_DIR / "scripts" / "palette_deltae_checker.py"
)
assert _spec is not None and _spec.loader is not None
_checker = importlib.util.module_from_spec(_spec)
sys.modules["palette_deltae_checker"] = _checker
_spec.loader.exec_module(_checker)

analyze_palette = _checker.analyze_palette
delta_e_ciede2000 = _checker.delta_e_ciede2000
parse_hex_color = _checker.parse_hex_color
prefix_waterfall = _checker.prefix_waterfall
simulate_vision = _checker.simulate_vision


def test_prefix_waterfall_requires_at_least_two_colors() -> None:
    output = prefix_waterfall(
        [parse_hex_color("blue=#2d74b3", fallback_label="c1")],
        threshold=11.0,
    )

    assert output == [
        "Need at least 2 colors for --prefix-waterfall.",
        "Received: 1 color (blue).",
    ]


@pytest.mark.parametrize(
    ("lab1", "lab2", "expected"),
    [
        ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
        ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
        ((50.0, 2.8361, -74.0200), (50.0, 0.0, -82.7485), 3.4412),
        ((50.0, -1.3802, -84.2814), (50.0, 0.0, -82.7485), 1.0000),
    ],
)
def test_delta_e_ciede2000_matches_sharma_reference_pairs(
    lab1: tuple[float, float, float],
    lab2: tuple[float, float, float],
    expected: float,
) -> None:
    assert delta_e_ciede2000(lab1, lab2) == pytest.approx(expected, abs=1e-4)


def test_simulate_vision_linearizes_before_applying_matrix() -> None:
    result = simulate_vision((128 / 255, 128 / 255, 0.0), "deuteranopia")

    assert result == pytest.approx((0.2650, 0.2056, 0.0067), abs=1e-4)


def test_analyze_palette_reports_failures_for_identical_colors() -> None:
    output = analyze_palette(
        [
            parse_hex_color("left=#000000", fallback_label="c1"),
            parse_hex_color("right=#000000", fallback_label="c2"),
        ],
        threshold=11.0,
    )

    assert output[0].startswith("pair")
    assert "left-right" in output[2]
    assert "0.00 FAIL" in output[2]
    assert "Failing pair/vision combinations:" in output
