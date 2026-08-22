"""Emit shared chrome CSS custom properties from a resolved board theme."""

from __future__ import annotations

from dbt_charts.core.compile.models.style.resolved import ResolvedStyle


def chrome_css_variables(resolved_style: ResolvedStyle) -> dict[str, str]:
    """Map resolved theme fields to canonical ``--dbt-system-*`` custom properties."""
    radius = resolved_style.border.radius
    muted = resolved_style.variables.font.color
    assert muted is not None  # resolve_style() populates variables.font.color
    background = resolved_style.background
    palette = resolved_style.chart_defaults.palette
    assert palette  # resolve_style() populates charts.palette
    single_series_ink = resolved_style.chart_defaults.single_series_palette[0]
    return {
        "--dbt-system-background": background,
        "--dbt-system-shell-background": (
            f"color-mix(in oklch, {background} 92%, black)"
        ),
        "--dbt-system-brand": palette[0],
        "--dbt-system-text": resolved_style.font.color,
        "--dbt-system-muted": muted,
        "--dbt-system-accent": single_series_ink,
        "--dbt-system-input-background": resolved_style.variables.input.background,
        "--dbt-system-input-border": resolved_style.variables.border.color,
        # CSS border-style can't honor an explicit dash_array — lossy mapping to
        # the dashed/solid keyword is the accepted tradeoff for this surface.
        "--dbt-system-input-border-style": (
            "dashed" if resolved_style.variables.border.dash_array else "solid"
        ),
        "--dbt-system-menu-background": resolved_style.background,
        "--dbt-system-radius": f"{radius:g}px",
    }


def chrome_css_declarations(resolved_style: ResolvedStyle) -> str:
    """Semicolon-separated declarations for inline ``style`` on isolated chrome roots."""
    return "; ".join(
        f"{name}: {value}"
        for name, value in chrome_css_variables(resolved_style).items()
    )


def theme_to_css(resolved_style: ResolvedStyle) -> str:
    """Render a ``:root { … }`` block for page-level chrome injection."""
    return f":root{{{chrome_css_declarations(resolved_style)}}}"
