# d3-format recipes

default:
    @just --list d3_format

[no-cd]
test *ARGS:
    uv run pytest -q --tb=short libs/d3-format/tests -n auto -m "not slow and not e2e and not network" {{ARGS}}

# Run d3-format production-source type checks from repo root so `uv run` resolves
# against the shared root dev-tool venv instead of re-resolving a member-scoped one.
[no-cd]
mypy:
    uv run --python 3.13 mypy --config-file libs/d3-format/pyproject.toml libs/d3-format
