# dbt-charts/tests

- No `__init__.py` under `dbt-charts/tests/` — never add one.
- Import sibling test helpers with a relative import (`from .conftest import ...`, `from .._paths import ...`), never the `dataface.tests.*` dotted path.
- `dbt-charts/tests/core/**` is excluded from pyright (`pyrightconfig.json`); these files are not type-checked. Removing an exclude requires clearing that subtree's pre-existing type errors in the same change.
