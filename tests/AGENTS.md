# dbt-charts/tests

- No `__init__.py` under `dbt-charts/tests/` — never add one.
- Import sibling test helpers with a relative import (`from .conftest import ...`, `from .._paths import ...`), never the `tests.*` dotted path.
- `dbt-charts/tests/core/**` is excluded from pyright (`pyrightconfig.json`); these files are not type-checked. Removing an exclude requires clearing that subtree's pre-existing type errors in the same change.
- A test that reads `DOCS_DIR` (`dbt-charts/tests/visual/discovery.py`) must carry `@pytest.mark.docs_derived` — the main test matrix's path filter excludes `apps/docs/**`, so only `docs.yml`'s `-m docs_derived` selection actually runs it against a docs-only change. Enforced by `tests/scripts/test_docs_derived_marker_coverage.py`.
