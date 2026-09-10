"""What jsdom cannot check about the per-chart loading state.

Behavior (which groups are marked, what the glyph is built from, that the
state ends only when the host says so) is covered in
``libs/playground/tests/js/variables-loading-state.test.js``. jsdom has no
layout and no cascade, so two things stay pinned here: the CSS transform
properties that make the glyph turn in place (an SVG element animated with
``rotate()`` spins about the SVG origin unless ``transform-box`` and
``transform-origin`` say otherwise), and where the loading rules live — with
the host, beside the runtime that paints them, never in the artifact.
"""

from __future__ import annotations

from importlib.resources import files


def _artifact_styles() -> str:
    return (
        files("dbt_charts.core.render") / "templates" / "svg" / "styles.css"
    ).read_text(encoding="utf-8")


def test_glyph_rotates_about_its_own_center() -> None:
    from dbt_charts.core.render.controls import controls_runtime_source

    source = controls_runtime_source()
    assert "transformBox = 'fill-box'" in source
    assert "transformOrigin = 'center'" in source


def test_loading_rules_ship_with_the_host_not_the_artifact() -> None:
    """A static export never loads, and a stored render must not have to be
    rebuilt for a loading-state change to reach it: the rules live in the
    controls stylesheet the host injects, next to the runtime."""
    from dbt_charts.core.render.controls import controls_stylesheet

    host = controls_stylesheet()
    assert ".dbt-chart-loading > :not(.dbt-chart-spinner)" in host
    assert "@keyframes dbt-spin" in host
    artifact = _artifact_styles()
    assert "dbt-chart-loading" not in artifact
    assert "dbt-spin" not in artifact


def test_loading_class_is_namespaced() -> None:
    """A bare ``loading`` class collides with the host's stylesheet: DaisyUI's
    ``.loading`` component masks the element into its own spinner shape, which
    is what blanked every dependent chart in Cloud on a variable commit."""
    from dbt_charts.core.render.controls import controls_stylesheet

    assert ".dbt-chart.loading" not in controls_stylesheet()
    assert ".dbt-chart-loading {" in controls_stylesheet()
