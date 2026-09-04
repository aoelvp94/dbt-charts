"""Generated. Do not edit by hand — run `just generate-schema-names`.

Source: list_built_in_themes() (compile/config.py), PREDEFINED_SPECS
(text/predefined_formats.py), list_palettes() and palette()
(compile/resolve/style/palette.py), VEGA_SCHEME_NAMES
(compile/models/primitives.py), get_theme_style() (compile/config.py).
"""

from __future__ import annotations

from typing import Literal

# Built-in theme stems offered as `theme:`/`extends:` value completions.
# Excludes the private `_base` completeness floor and diagnostic-only themes.
ThemeName = Literal[
    "clarity",
    "neon",
    "paper",
    "stark",
    "vivid",
]

# Named dbt charts palettes (sequential, diverging, categorical, scaffold, tone).
# Excludes hard-fail anti-pattern names and warn-alias migration names — neither
# is a real palette YAML entry, so list_palettes() already omits them.
# The whole index, which only `style.palettes` (the role map) accepts.
PaletteName = Literal[
    "category-6-tonal-blue",
    "category-6-tonal-brown",
    "category-6-tonal-green",
    "category-6-tonal-orange",
    "category-6-tonal-purple",
    "dbt-creams",
    "dbt-div-blue-red",
    "dbt-div-blue-red-dark",
    "dbt-div-coolwarm",
    "dbt-div-coolwarm-dark",
    "dbt-div-crimson-green",
    "dbt-div-crimson-green-dark",
    "dbt-div-orange-teal",
    "dbt-div-orange-teal-dark",
    "dbt-div-sunset",
    "dbt-div-sunset-dark",
    "dbt-grays",
    "dbt-seq-amber",
    "dbt-seq-amber-dark",
    "dbt-seq-blue",
    "dbt-seq-blue-dark",
    "dbt-seq-brown",
    "dbt-seq-brown-dark",
    "dbt-seq-gray",
    "dbt-seq-gray-dark",
    "dbt-seq-green",
    "dbt-seq-green-dark",
    "dbt-seq-purple",
    "dbt-seq-purple-dark",
    "dbt-seq-rust",
    "dbt-seq-rust-dark",
    "dbt-seq-teal",
    "dbt-seq-teal-dark",
    "editorial-10",
    "editorial-10-dark",
    "editorial-10-ghost",
    "editorial-10-ink",
    "editorial-10-light",
    "hero-6",
    "info",
    "negative",
    "positive",
    "tableau",
    "vivid-10",
    "vivid-10-dark",
    "vivid-10-ghost",
    "vivid-10-ink",
    "vivid-10-light",
    "warning",
]

# PaletteName minus the tone family — the names a `palette:` field takes.
# A tone is a colour-token source and resolves to no stops, so `palette()`
# refuses every one: naming a tone there parses and dies at resolve.
StopsPaletteName = Literal[
    "category-6-tonal-blue",
    "category-6-tonal-brown",
    "category-6-tonal-green",
    "category-6-tonal-orange",
    "category-6-tonal-purple",
    "dbt-creams",
    "dbt-div-blue-red",
    "dbt-div-blue-red-dark",
    "dbt-div-coolwarm",
    "dbt-div-coolwarm-dark",
    "dbt-div-crimson-green",
    "dbt-div-crimson-green-dark",
    "dbt-div-orange-teal",
    "dbt-div-orange-teal-dark",
    "dbt-div-sunset",
    "dbt-div-sunset-dark",
    "dbt-grays",
    "dbt-seq-amber",
    "dbt-seq-amber-dark",
    "dbt-seq-blue",
    "dbt-seq-blue-dark",
    "dbt-seq-brown",
    "dbt-seq-brown-dark",
    "dbt-seq-gray",
    "dbt-seq-gray-dark",
    "dbt-seq-green",
    "dbt-seq-green-dark",
    "dbt-seq-purple",
    "dbt-seq-purple-dark",
    "dbt-seq-rust",
    "dbt-seq-rust-dark",
    "dbt-seq-teal",
    "dbt-seq-teal-dark",
    "editorial-10",
    "editorial-10-dark",
    "editorial-10-ghost",
    "editorial-10-ink",
    "editorial-10-light",
    "hero-6",
    "tableau",
    "vivid-10",
    "vivid-10-dark",
    "vivid-10-ghost",
    "vivid-10-ink",
    "vivid-10-light",
]

# StopsPaletteName union Vega/Vega-Lite scheme names — the only closed set
# ScaleTargetConfig.palette accepts (it also forwards Vega scheme names
# straight through to VL's scale.scheme). Hard-fail and warn-alias scheme
# names (e.g. 'rainbow') are excluded — see _HARD_FAIL_NAMES/_WARN_ALIASES.
ScalePaletteName = Literal[
    "accent",
    "bluegreen",
    "blueorange",
    "bluepurple",
    "blues",
    "brownbluegreen",
    "browns",
    "category-6-tonal-blue",
    "category-6-tonal-brown",
    "category-6-tonal-green",
    "category-6-tonal-orange",
    "category-6-tonal-purple",
    "category10",
    "category20",
    "category20b",
    "category20c",
    "cividis",
    "dark2",
    "darkblue",
    "darkgold",
    "darkgreen",
    "darkmulti",
    "darkred",
    "dbt-creams",
    "dbt-div-blue-red",
    "dbt-div-blue-red-dark",
    "dbt-div-coolwarm",
    "dbt-div-coolwarm-dark",
    "dbt-div-crimson-green",
    "dbt-div-crimson-green-dark",
    "dbt-div-orange-teal",
    "dbt-div-orange-teal-dark",
    "dbt-div-sunset",
    "dbt-div-sunset-dark",
    "dbt-grays",
    "dbt-seq-amber",
    "dbt-seq-amber-dark",
    "dbt-seq-blue",
    "dbt-seq-blue-dark",
    "dbt-seq-brown",
    "dbt-seq-brown-dark",
    "dbt-seq-gray",
    "dbt-seq-gray-dark",
    "dbt-seq-green",
    "dbt-seq-green-dark",
    "dbt-seq-purple",
    "dbt-seq-purple-dark",
    "dbt-seq-rust",
    "dbt-seq-rust-dark",
    "dbt-seq-teal",
    "dbt-seq-teal-dark",
    "editorial-10",
    "editorial-10-dark",
    "editorial-10-ghost",
    "editorial-10-ink",
    "editorial-10-light",
    "goldgreen",
    "goldorange",
    "goldred",
    "greenblue",
    "greens",
    "greys",
    "hero-6",
    "inferno",
    "lightgreyred",
    "lightgreyteal",
    "lightmulti",
    "lightorange",
    "lighttealblue",
    "magma",
    "observable10",
    "orangered",
    "oranges",
    "paired",
    "pastel1",
    "pastel2",
    "pinkyellowgreen",
    "plasma",
    "purpleblue",
    "purplebluegreen",
    "purplegreen",
    "purpleorange",
    "purplered",
    "purples",
    "redblue",
    "redgrey",
    "redpurple",
    "reds",
    "redyellowblue",
    "redyellowgreen",
    "set1",
    "set2",
    "set3",
    "sinebow",
    "spectral",
    "tableau",
    "tableau10",
    "tableau20",
    "tealblues",
    "teals",
    "turbo",
    "viridis",
    "vivid-10",
    "vivid-10-dark",
    "vivid-10-ghost",
    "vivid-10-ink",
    "vivid-10-light",
    "warmgreys",
    "yellowgreen",
    "yellowgreenblue",
    "yelloworangebrown",
    "yelloworangered",
]

# Engine-predefined format names (PredefinedNumberFormat + PredefinedTimeFormat).
# A predefined name resolves to a d3 spec or native formatter at render time;
# a raw d3 spec or user style.formats alias is equally legal, so every field
# carrying this reads `FormatAlias | str` — the Literal names the shortcuts,
# it does not close the set. Kind-agnostic slots (`format:`) take this one;
# a slot that knows its kind takes the matching half below.
FormatAlias = Literal[
    "currency",
    "currency_full",
    "currency_whole",
    "date_short",
    "delta",
    "integer",
    "number",
    "number_full",
    "percent",
    "percent_delta",
    "percent_whole",
    "time_short",
    "year",
]

# The number half — PredefinedNumberFormat, i.e. every name resolving to a
# d3 *number* spec. What `number_format` offers and accepts.
NumberFormatAlias = Literal[
    "currency",
    "currency_full",
    "currency_whole",
    "delta",
    "integer",
    "number",
    "number_full",
    "percent",
    "percent_delta",
    "percent_whole",
    "year",
]

# The time half — PredefinedTimeFormat, i.e. every name resolving to a d3
# *time* spec. What `time_format` offers and accepts, beside a raw strftime
# spec like `%b %Y`.
TimeFormatAlias = Literal[
    "date_short",
    "time_short",
]

# Category role slot tokens, `category[1]`..`category[N]` — N is the widest
# palette any built-in theme binds to the `category` role. Pinning a category
# to a slot (rather than a hex) is what lets it re-skin with the theme, so
# these are the values worth completing. Like FormatAlias, the field carrying
# this reads `CategorySlotToken | str`: dotted palette tokens
# (`dbt-grays.muted`) and literal hex stay legal.
CategorySlotToken = Literal[
    "category[1]",
    "category[2]",
    "category[3]",
    "category[4]",
    "category[5]",
    "category[6]",
    "category[7]",
    "category[8]",
    "category[9]",
    "category[10]",
]
