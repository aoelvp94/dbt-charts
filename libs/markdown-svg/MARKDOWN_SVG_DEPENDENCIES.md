# Dependencies and Licenses

This document lists all dependencies for markdown-svg, their licenses, and their usage within the project. This information is provided for diligence purposes.

This library has no `pyproject.toml` `[project]` table of its own — it ships as a peer package inside the `dbt-charts` wheel, and its dependencies (`fonttools`, `nh3`, `pygments`) are declared directly in `dataface/pyproject.toml`.

## Required Dependencies

| Dependency | Version | License | Purpose |
|------------|---------|---------|---------|
| fonttools | >=4.0 | MIT | Used for reading font metrics (glyph widths, units per em) from TTF/OTF font files to enable precise text width measurement. Imported in `src/mdsvg/fonts.py` via `fontTools.ttLib.TTFont`. |

## Optional Dependencies

| Dependency | Version | License | Purpose |
|------------|---------|---------|---------|
| pygments | (any) | BSD 2-Clause | Used for syntax highlighting in fenced code blocks (`src/mdsvg/highlight.py`); imported lazily, so it isn't a hard import-time requirement of this library, but `dbt-charts` (which bundles it) declares `pygments` as a direct dependency, so it is always present there. |

## Build System Dependencies

This library has no `[build-system]`/`pyproject.toml` `[project]` table of its own — it is built as part of `dbt-charts`'s wheel by `dataface/pyproject.toml`'s hatchling configuration.

## Development Dependencies

| Dependency | Version | License | Purpose |
|------------|---------|---------|---------|
| pytest | >=7.0 | MIT | Testing framework used for running unit tests. |
| pytest-cov | >=4.0 | MIT | Plugin for pytest that provides coverage reporting. |
| mypy | >=1.0 | MIT | Static type checker for Python, used for type validation. |
| ruff | >=0.1.0 | MIT | Fast Python linter and code formatter, used for code quality checks. |
| pre-commit | >=3.0 | MIT | Git hooks framework used to run checks before commits (linting, type checking, etc.). |

## Notes

- **Standard Library Usage**: The project makes extensive use of Python's standard library modules (e.g., `urllib.request`, `struct`, `re`, `os`, `platform`) which do not require separate licensing considerations.

- **No Runtime Markdown Parser**: The project does not use an external Markdown parsing library. Markdown parsing is implemented directly in `src/mdsvg/parser.py`.

- **Image Handling**: image dimension fetching and parsing uses only the Python standard library (`urllib.request`) — no `pillow`/`requests` dependency.

- **Syntax Highlighting**: `pygments`-driven per-token syntax highlighting is implemented in `src/mdsvg/highlight.py` (opt-in via `Style.code_highlight`); see the Optional Dependencies table above.

## License Compatibility

All dependencies use permissive open-source licenses (MIT, BSD, Apache 2.0, HPND) that are compatible with the project's MIT license. There are no copyleft licenses (GPL, AGPL) that would require derivative works to be open-sourced.
