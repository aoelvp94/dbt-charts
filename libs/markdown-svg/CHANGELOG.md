# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- CSS class names in the emitted `<style>` block and on the elements that wear
  them are now scoped to a hash of the renderer's own style: `.md-heading`
  becomes `.md-<hash>-heading`, and likewise for `text`, `mono`, `code`, `link`
  and `blockquote`. Inline SVG in an HTML page shares one global CSS scope, so
  two renders with different styles on one page previously collided — the last
  rule for a selector won for every SVG on the page. The hash is derived from
  the rule bodies, so it is stable across processes, and two renders of the
  same style still share a scope (their rules are identical anyway). Anything
  selecting the old bare class names must select the scoped form.

### Fixed

- `code-clip-*` clipPath ids (code blocks under `code_block_overflow="hide"`)
  derive from the block's content and geometry instead of `id()`. A CPython
  memory address made the rendered output differ between runs and could collide
  between two renders composited into one document.

- A heading opening a document no longer draws its own leading margin. Its
  `margin_top` separates it from the text above it; at the top of the box there
  is none, so it collapses — the same rule `BlockMetrics.leading_margin` already
  exists to let a caller apply to a block opening a column, now applied to the
  box the renderer draws for itself. Headings only: no other block type declares
  a leading margin, so nothing else moves. `render()`, `render_content()` and
  `measure()` all move together: the opening block, and everything under it,
  rises by that margin, and the block's reported height falls by it. Headings
  after any other block are unchanged.
- Text baselines are placed by the font's real ascent instead of assuming one em.
  Every first baseline used to sit exactly `font_size` below its line box top,
  which treats the ascent as 1em and drops the whole leading below the baseline;
  the CSS model splits the leading and puts the baseline at
  `half_leading + ascent`. Paragraphs, headings, blockquotes and list items move
  as a result —
  down for text whose line height leaves room (body prose at 1.4 moved ~0.7px),
  up for the tight line heights typical of headings (a 24px heading at 1.1 moved
  ~2.4px). Fenced code blocks and table cells are unaffected: they place their
  own text and size their own boxes on one model, so nothing misregisters within
  a line. Line advances, and therefore block heights, are unchanged throughout.
- Ordered-list numbers follow their item's text. The number shared a baseline
  with its item only because both were the same expression, so moving one moved
  the numbers off the words by 1-3px, growing with the font size; it now asks for
  that baseline explicitly. (Bullets needed no change: half a line box down is
  also the middle of the line's text, at any line height.)

### Added

- `fonts.FontMeasurer.ascent_em` / `.descent_em` — the face's `hhea` vertical
  metrics as em fractions. Both raise if the font never loaded rather than
  reporting zero.
- `renderer.SVGRenderer.heading_baseline(level)` and
  `.heading_line_box(level, block_height)` — where a heading's first baseline
  lands inside its block, and which part of that block is text rather than
  margin. Both describe a heading that opens its document, whose top margin has
  collapsed; the line box therefore starts at the block's own top edge. For
  callers that were deriving either by fitting a ratio to one font at one size.

### Changed

- `renderer.SVGRenderer.measure()` measures by running the same placement loop
  that draws, rather than its own copy of it. The two could disagree; a caller
  reserving space for prose it then renders would clip or float it.
- `fonts.FontMeasurer.measure()` now recognizes emoji clusters (pictographs,
  VS16-forced symbols, ZWJ sequences, flags, keycaps) and books one real
  emoji-advance width per visible glyph instead of measuring per codepoint.
  Most affected glyphs move from a quarter-em placeholder to the fixed
  emoji-advance width (~5x wider); a VS16-qualified symbol with a real glyph
  in the measured font (e.g. `↗️`) instead has that real, narrower advance
  discarded in favor of the same fixed width.
- `fonts.wrap_text_precise()` now returns `tuple[list[str], bool]` instead of
  `list[str]`: the second element is True when `max_lines` forced an ellipsis
  truncation. Callers that only need the lines unpack the first element.

- Code is now sized relative to the text it sits in. Previously inline code
  inherited its host block's size outright (1.0x) while fenced blocks used a
  hard-coded `base_font_size * 0.9`; both now derive from the new
  `Style.code_font_scale`. Inline code scales off its host block, so code inside
  a heading grows with the heading instead of dropping to a body-sized run;
  fenced blocks scale off `base_font_size`. Sizes snap to the nearest
  half-pixel. Setting `Style.code_font_size` still pins an absolute size and
  overrides the scale everywhere, unchanged.

  Rendered output moves for any style that did not set `code_font_size`: inline
  code shrinks from 1.0x to 0.9x of its host, and inline code in a heading now
  differs in size from inline code in body prose.

### Added

- `SVGRenderer.used_faces` — the set of supplied `FontFaces` a renderer has actually
  reached (`regular`, `bold`, `italic`, `bold_italic`, `mono`), accumulated across
  calls. For callers that package fonts alongside the SVG: which font files a render needs
  cannot be known beforehand, because italic is reached through markdown emphasis
  inside the text rather than through anything in the style.

- `nh3` (`>=0.3.3`) is now a required dependency. The raw-HTML sanitizer
  (`_sanitize_html`) uses `nh3.clean()` with an explicit tag, attribute, and
  URL-scheme allowlist instead of the previous regex approach. The parser-based
  walk closes three verified bypasses the regex could not block: `javascript:`
  hrefs on `<a>` elements, unquoted event-handler attributes (e.g.
  `onerror=...` without quotes), and SVG `<use href="javascript:...">` vectors.

## [2.1.0] - 2026-08-02

### Added

- `SVGRenderer.measure_blocks()` returns per-block `BlockMetrics` (line count,
  line advance, leading space, whether the block may be split, whether it must
  keep with the next). The measure half of a measure-then-place pair, mirroring the
  table path's `TableRowLayout`.
- `SVGRenderer.render_block_window()` draws a run of a block's wrapped lines,
  positioned at the top of its own box so a continuation does not inherit the
  offset of the lines before it.
- `Style.avoid_runts`: when a paragraph's last line would hold a single short
  word, pull a word down from the line above if the moved word still fits.
  Off by default, so existing wrap points are unchanged.

Together the first two let a caller flow markdown into fixed-height boxes --
columns, pages, slides -- deciding its own break points. mdsvg owns line
breaking and knows nothing about what the boxes are.

## [2.0.0] - 2026-08-02

### Added

- `ListItem.children: tuple[AnyBlock, ...]` — nested block content (sub-lists) parsed from list-item bodies. Defaults to `()`, so existing constructors and flat-list rendering are unchanged. Replaces the inert `nested_list` field removed in 1.1.0, and this time it is parsed and rendered.
- `FontFace` / `FontFaces` (`mdsvg.fonts`): a `FontFace` names one concrete font file, optionally instanced at a variable-font weight (`path`, `weight`, `font_number`). `FontFaces` groups the set a caller paints with — `regular` plus optional `bold`, `italic`, `bold_italic`, `mono` — so each style can be measured against its own real file instead of guessed from the regular font file.
- `SVGRenderer(fonts=FontFaces(...))`: measures bold/italic/bold-italic/mono runs against the supplied real font files. `(is_bold, is_italic)` selects `bold_italic`, falling back to `italic`, then `bold`; a style with no matching font file falls back to the existing ratio-scaling estimate. Mutually exclusive with `font_path`/`mono_font_path` — passing both raises `ValueError`.
- `FontMeasurer(weight=...)`: when the loaded font has an `fvar` table, instances it once at construction via `fontTools.varLib.instancer.instantiateVariableFont` and measures the instanced glyph metrics. Requesting a weight on a font with no `fvar` table raises `ValueError` — a caller error, not something to silently ignore. `_cached_measurer`'s LRU key now includes weight (`(font_path, font_number, weight)`) since the same file instanced at different weights has different advance widths.
- `RenderResult.max_content_width`: the widest laid-out line actually emitted — across paragraphs, headings, list items, table cells, and code block lines — in the same coordinate space as the `width` passed to `render_content()`. Lets a caller detect that content painted wider than its box. `0.0` for empty content.

### Changed

- **`Style.italic_char_width_ratio` default corrected from `0.52` to `0.447`, and its sign fixed.** Measured from real variable font files, italic is *narrower* than regular (Source Serif 4: -13.85%, Inter: +0.20%), not ~8% wider as the old default implied. The new default (`0.48 × (1 - 0.068)`) is the midpoint of those two measurements. This only affects callers who supply a single `font_path` (no `fonts=FontFaces(...)`) and render italic text — the common case where a real italic font file is supplied now measures correctly regardless of this default.
- `Style.char_width_ratio` / `bold_char_width_ratio` / `italic_char_width_ratio` docstrings now say plainly that they are a last-resort estimate, used only when `SVGRenderer` has no matching real font file to measure.
- `SVGRenderer._measure_text`'s docstring and the stale inline comment claiming "Bold text is typically 10-15% wider, italic ~4% wider" are replaced with the measured reality above; the code path itself now prefers a real font file over the ratio guess (see Added).

### Removed

- **`calibrate_heuristic()`** (`mdsvg.fonts`): exported public API used by nothing but its own test, and it shipped a second hardcoded bold factor (`ratio * 1.08`) alongside `Style.bold_char_width_ratio`'s `0.58` — two homes for the same guess. With `SVGRenderer(fonts=...)` measuring real font files directly, there's nothing left for a calibrated heuristic to do. No caller found anywhere in the consuming dbt charts monorepo.

### Fixed

- **A code span no longer breaks across lines when it would fit on the next one.** Runs were
  tokenized on whitespace before wrapping, so `` `width: "25%"` `` could split at its space —
  leaving half the span on each line with a background chip behind each half, reading as two
  settings rather than one. A code span is now kept whole whenever it fits a line on its own;
  one longer than any line still falls back to token and character splitting, since the
  alternative is painting past the edge.
- **Headings are measured at the weight they are painted at.** `_render_text_block` already
  received the block's `font_weight` — `Style.heading_font_weight` for headings — and did not
  pass it to measurement, so a heading was measured at the body weight and came out narrower
  than it would be drawn. `_measure_text` now takes `font_weight` and resolves a measurer at
  that weight off the same file (via the new `FontMeasurer.supports_weight`, so a static font
  keeps its default rather than raising). Bold runs are unaffected: they already paint at
  `bold_font_weight` and keep the bold font file.
- **Per-run widths now account for bold and italic.** The widths used for inline-code chip
  positions and line extents measured every run as regular, while wrapping measured bold and
  italic correctly — so a chip after a bold run sat a fraction of a pixel off.

- Multi-line and nested markdown list items no longer silently lose content. A list item written across multiple physical lines previously rendered only its first physical line (indented continuation lines were skipped without being accumulated), and an item indented past its parent vanished entirely. `_parse_unordered_list`/`_parse_ordered_list` are collapsed into one `_parse_list`: an item claims the lines after its marker up to the next sibling marker — the leading run joins its spans as continuation text (indented or lazily unindented, per CommonMark) and the remainder is dedented and parsed into `ListItem.children`. Block-starters at the same indent level (ATX headings, horizontal rules, fenced code fences, blockquotes, table rows, HTML block starts) correctly terminate the list item rather than being swallowed as continuation text. Behavior for 23 list shapes is pinned against `markdown-it` in commonmark mode (expected values committed statically; no new dependency). Known remaining gap: a nested item separated from its parent by a blank line (loose-list shape) is still dropped — documented at the skip branch in `_parse_list`.

- `get_image_size()` now sizes `data:` URIs from their own payload instead of `stat()`ing the whole URI as a file path, which raised `OSError: [Errno 63] File name too long` for any inline image past `PATH_MAX`. `data:image/svg+xml` payloads are sized from the root `<svg>` element's `width`/`height`, falling back to `viewBox`; other media types go through the existing PNG/JPEG/GIF/WebP/BMP header parser. Headers are matched per RFC 2045 — case-insensitive, and a space after the `;` is tolerated. A payload that is intact but unmeasurable (a format the header parser doesn't know, or an SVG with no intrinsic size — `width="100%"` with no `viewBox`, or dimensions that round below one pixel) returns `None`, so the renderer's `image_fallback_aspect_ratio` applies exactly as it does for a local or remote image. An `image/svg+xml` payload declaring XML entities is never handed to the XML parser and returns `None` too. A structurally corrupt URI — no `,` separator, invalid base64, or an `image/svg+xml` payload that is not XML — raises `ValueError`. Unpadded base64 is accepted, matching the forgiving-base64 decode browsers use for `data:` URIs.

### Performance

- `FontMeasurer(weight=...)` now reads per-glyph advance deltas from the font's `HVAR` table
  instead of rebuilding the font with `instantiateVariableFont`. Measuring only needs
  horizontal advances, which is exactly what `HVAR` stores; the instancer rebuilds
  `glyf`/`gvar`/`GPOS`/`avar`/`STAT` to arrive at the same numbers. Measured here: 0.2-0.8 s
  per font file before, 1-4 ms after (~200x), which for a caller supplying regular + bold + italic
  + bold-italic was ~3 s of work on the first render of every process. `avar` is applied to
  the normalized axis position, so non-default weights land where a shaper puts them; results
  match full instancing to well under a tenth of a pixel across a 53-character sample (the
  residual is the instancer rounding advances to whole font units — `HVAR` keeps the
  unrounded value). A variable font with no `HVAR` still falls back to full instancing.

## [1.1.0] - 2026-07-31

### Added

- `Style.inline_code_padding` / `Style.inline_code_border_radius`: geometry tokens for inline code chips. Default 3 px each (tighter than the fenced code block tokens). Callers can set these independently from `code_block_padding` / `code_block_border_radius`.
- `Style.heading_margin_top_px` / `Style.heading_margin_bottom_px`: optional absolute-pixel overrides for the existing em-of-heading margins. When set, mdsvg uses the px value directly instead of `font_size * heading_margin_top`/`_bottom`. Lets callers anchor heading margins to a body-rhythm value (constant px) rather than the heading's own size (which would scale the gap with H level). The em-based fields remain the default; the new fields fall back to them when `None`.
- Per-code font-override fields on `Style`: `code_font_family`, `code_font_weight`, `code_font_style`, `code_font_size`, `code_font_decoration`, `code_font_case`. Each axis is honored in both inline code spans and fenced code blocks. `code_font_case` applies `upper`/`lower` via string transform (not CSS `text-transform`, which is unreliable in resvg/vl-convert). `code_font_family` overrides `mono_font_family` when set.
- Per-blockquote font-override fields on `Style`: `blockquote_font_family`, `blockquote_font_weight`, `blockquote_font_style`, `blockquote_font_size`, `blockquote_font_decoration`, `blockquote_font_case`. Applied via the `.md-blockquote` CSS class and via string transform for `case`.
- `Style.blockquote_background`: optional background fill rect behind blockquote content. Empty string (default) emits no rect; set to any CSS color to fill.
- `Style.blockquote_border_radius`: corner radius (px) for the blockquote background rect. Defaults to 0 (square corners; no `rx` emitted).
- `Style.code_block_border_color` + `Style.code_block_border_width`: optional border stroke on code block background rects. Empty string (default) emits no stroke; set a CSS color to draw the border.
- `Style.font_weight` now controls the generated `.md-text` body font weight.
- `Style.bold_font_weight`: CSS font-weight for bold text runs — `**bold**` markdown spans and bold table cells (data cells and headers alike, since header cells are already forced bold for column-width measurement). Defaults to `"bold"` (700), matching the previous hardcoded behavior, so a no-config render is unchanged. Independent of `heading_font_weight`, which governs H1–H6 markdown headings only.

### Changed

- **Table header cells now use `bold_font_weight` instead of a hardcoded `"bold"`.** Previously `run.is_bold or is_header` shared one literal `"bold"` branch. Header cells are already forced `is_bold=True` for measurement, so routing them through the new `bold_font_weight` knob (rather than the unrelated `heading_font_weight`, which governs H1–H6 sizing/weight) keeps a header cell at least as heavy as an inline bold word in the same table, while leaving the default unchanged for callers who don't set `bold_font_weight`.

- **Heading-adjacent block spacing.** `paragraph_spacing` is no longer applied between a heading and an adjacent block. Heading margins (`heading_margin_top` / `heading_margin_bottom`, or their `_px` overrides) are now the sole source of pre/post-heading rhythm, matching the natural reading expectation that the field's stated value equals the visible space. Two adjacent headings now CSS-margin-collapse to `max(prev.margin_bottom, next.margin_top)` instead of summing. Affects every multi-block path (top-level render, `measure`, and blockquote-inner stacks). Callers that pre-compensated their heading margins for the old double-stack (e.g. `dct` set `heading_margin_top_px = 1.0 * body_line` to net `1.5` after `paragraph_spacing`) should revert to the literal target values.
- **Inline code now renders as a background chip** — a `<rect>` with `code_background` fill, `rx = inline_code_border_radius`, and `inline_code_padding` on all sides is emitted behind each inline code tspan. The old `[bracket]` placeholder is gone. A code span split across a line wrap draws one chip per line segment. Geometry is computed from the same `FontMeasurer` used for wrapping, so chips align precisely with the mono text they back.
- Fenced code blocks now shrink to their content width when possible and use tighter vertical padding.
- Unordered list markers are smaller and quieter, with reduced list indentation.
- Default list item spacing is tighter for compact report prose.
- `split_token_precise` and `wrap_text_precise` now prefer natural seam characters (`_/.-?&=:`) over arbitrary mid-character breaks when splitting long tokens that exceed the line width. All callers (tables, titles, callouts, prose) benefit automatically.
- `FontMeasurer` instances are now cached by font path via `_cached_measurer` (process-global `lru_cache`). `SVGRenderer` and `get_default_measurer` both route through this cache, so repeated renders with the same font path open the TTF file only once. Measured 3× speedup on text-heavy dashboards (color-palettes reference font file: 4 s → 1.3 s render).

### Removed

- Inert `nested_list` field on `ListItem` — parser never populated it and renderer never read it; nested lists were never functional through this field.
- Internal `utils` helpers that were never called: `indent_text`, `generate_id`, `clamp`, and the color cluster (`lighten_color`, `darken_color`, `hex_to_rgb`, `rgb_to_hex`). None of these were exported from the package.

## [0.7.0] - 2025-12-15

### Changed

- `SVGRenderer` now requires precise font measurement for wrapping and truncation; the old heuristic text-measurement mode has been removed.

### Removed

- Removed SVG `<foreignObject>` rendering for code blocks to improve portability across SVG renderers.
- Removed `foreignObject` from the `code_block_overflow` options (use `wrap`, `show`, `hide`, or `ellipsis`).

## [0.6.3] - 2025-12-10

### Added

- Style presets for different rendering contexts: `DOCUMENT_PRESET`, `COMPACT_PRESET`, `MINIMAL_PRESET`
- `StylePresets` class for organized access to presets
- `merge_styles()` helper function for combining presets with themes
- Compact preset uses tighter margins (0.3em vs 1.5em for headings) for dashboards and UI components
- Minimal preset for very tight spaces like tooltips

### Changed

- Default style remains unchanged (document-style generous whitespace)
- Users needing compact UI rendering can now use `COMPACT_PRESET` instead of manually configuring margins

## [0.6.2] - 2025-12-09

### Fixed

- Fixed all linting errors that were blocking CI/CD
- Removed unused imports and variables
- Fixed code style issues (collapsible if statements, ternary operators)

### Added

- Pre-commit hooks configuration for automatic linting before commits
- Ruff formatting integration

## [0.6.1] - 2025-12-09

### Fixed

- Added missing style option to playground server (`italic_char_width_ratio`)

### Added

- Documentation for text measurement ratios in formatting example

## [0.6.0] - 2025-12-08

### Added

- Image sizing support with automatic dimension fetching
- Extended markdown syntax for explicit image dimensions: `![alt](url){width=X height=Y}`
- `image_width`, `image_height`, `image_fallback_aspect_ratio` style options
- `image_enforce_aspect_ratio` option to skip dimension fetching
- Code block overflow options: `wrap`, `show`, `hide`, `ellipsis`, `foreignObject`
- `code_block_overflow` style option
- `mono_font_path` parameter for SVGRenderer for precise monospace measurement
- Image URL mapping support for CDN integration

### Changed

- Images now default to full container width instead of fixed 200px
- Improved monospace text measurement (deterministic char count × width)

## [0.5.0] - 2025-12-06

### Added

- Initial release of markdown-svg
- Core rendering functionality:
  - Headings (h1-h6) with configurable scales
  - Paragraphs with automatic word wrapping
  - Bold, italic, and bold+italic text
  - Inline code with background styling
  - Links (rendered as clickable SVG anchors)
  - Unordered lists with bullet points
  - Ordered lists with numbers
  - Fenced and indented code blocks
  - Blockquotes with left border
  - Horizontal rules
  - Tables with header and alignment support
  - Images as SVG `<image>` elements
- `render()` function for direct markdown-to-SVG conversion
- `measure()` function for dimension queries
- `parse()` function for AST access
- `render_blocks()` function for rendering pre-parsed content
- `Style` class for comprehensive styling control
- Built-in themes: `LIGHT_THEME`, `DARK_THEME`, `GITHUB_THEME`
- `Style.with_updates()` for creating modified style copies
- Full type annotations throughout
- Comprehensive test suite
- Precise text measurement via fonttools
- Google Fonts download support

### Technical Details

- Accurate text width measurement using fonttools font metrics
- Configurable character width ratios for different fonts
- SVG output with embedded CSS classes for styling
- Proper XML escaping for all text content
- Support for Python 3.9+
