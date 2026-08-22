# Text Formatting

## Basic Formatting

This is **bold text** for emphasis.

This is *italic text* for subtle emphasis.

This is ***bold and italic*** combined.

This is ~~strikethrough~~ text.

## Links

Visit [GitHub](https://github.com) for code hosting.

Check out the [markdown-svg documentation](https://github.com/davefowler/markdown-svg) for more details.

## Inline Code

Use `backticks` for inline code like `variables` or `functions()`.

You can reference things like `config.json` or `npm install` inline.

## Combined Formatting

You can **combine *different* formatting** in creative ways.

Here's a **[bold link](https://example.com)** and an *[italic link](https://example.com)*.

---

## Horizontal Rules

Use horizontal rules to separate sections.

---

They create visual breaks in your content.

## Text Measurement Notes

For accurate word wrapping, markdown-svg measures text width using fonttools. Pass `SVGRenderer(fonts=FontFaces(regular=..., bold=..., italic=...))` to measure bold/italic runs against their real font files — this is the accurate path and should be preferred whenever those files are available.

When only a single `font_path` is supplied, bold and italic widths fall back to a scaling-ratio estimate against the regular measurement:

| Style | Ratio | Notes |
|-------|-------|-------|
| Regular | 0.48 | `char_width_ratio` |
| Bold | 0.58 | ~20% wider than regular (real bold font files are typically only ~2-3% wider) |
| Italic | 0.447 | ~7% *narrower* than regular — italic glyphs are narrower, not wider |
| Monospace | 0.60 | Fixed width for all characters |

These ratios are a last resort; they can be tuned via Style options if your font differs significantly from the defaults, but using real `fonts=FontFaces(...)` is always more accurate.
