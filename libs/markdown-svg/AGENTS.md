# markdown-svg

## Purpose

Convert Markdown to SVG with automatic text wrapping. SVG has no native text flow; this library parses Markdown and renders properly wrapped, styled SVG suitable for dashboards, diagrams, and exports. Core dependencies: `fonttools` (text measurement) and `nh3` (HTML sanitization).

This directory has no `[project]`/`[build-system]` of its own and is not an independent uv workspace member — it is a peer package built directly into the `dbt-charts` wheel (`dbt-charts/pyproject.toml`'s `[tool.hatch.build.targets.wheel.force-include]`), the same way `d3_format` is. Import name stays `mdsvg`.

## Testing

Run the full suite: `just markdown_svg test`
Run one test: `uv run pytest libs/markdown-svg/tests/test_foo.py::test_name -q --tb=short`
Typecheck: `just markdown_svg mypy`
Note: the just alias is `markdown_svg` (underscore), not `markdown-svg`.

## Key files

- `src/mdsvg/` — library source (importable name `mdsvg`; ships inside the `dbt-charts` wheel, not its own PyPI package)
- `src/mdsvg/parser.py`, `src/mdsvg/renderer.py` — Markdown parse + SVG render
- `src/mdsvg/style.py`, `src/mdsvg/fonts.py` — text styling and font handling
- `examples/` — runnable example scripts
- `playground/` — live web playground used during development
- `docs/` — published documentation

## Conventions / gotchas

Treat this as a standalone library even though it isn't independently packaged:

- It targets Python 3.10+ (matches the repo baseline).
- Don't reach into dbt charts internals from here. The code must remain importable standalone (its own test suite runs via `pythonpath`, with zero dependency on `dbt-charts` being built).

Repo-wide testing/CI rules in root `AGENTS.md` apply, but architectural decisions for this package should respect its standalone-library character (zero hard deps on dbt charts).
