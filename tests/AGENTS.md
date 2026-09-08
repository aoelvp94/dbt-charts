# tests

- No `__init__.py` under `tests/` — never add one.
- Import sibling test helpers with a relative import (`from .conftest import ...`, `from .._paths import ...`), never the `tests.*` dotted path.
- `tests/core/**` is excluded from pyright (`pyrightconfig.json`); these files are not type-checked. Removing an exclude requires clearing that subtree's pre-existing type errors in the same change.
- **Monorepo only** (`tests/visual/` is not part of the standalone package): a test that reads `DOCS_DIR` (`tests/visual/discovery.py`) must carry `@pytest.mark.docs_derived` — the main test matrix's path filter excludes `apps/docs/**`, so only `docs.yml`'s `-m docs_derived` selection actually runs it against a docs-only change. Enforced by the monorepo's `tests/scripts/test_docs_derived_marker_coverage.py`.
