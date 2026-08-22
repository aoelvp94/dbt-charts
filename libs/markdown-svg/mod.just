# markdown-svg recipes

host := env_var_or_default("DCT_HOST", "127.0.0.1")

default:
    @just --list markdown_svg

[no-cd]
test *ARGS:
    uv run pytest -q --tb=short libs/markdown-svg/tests -n auto -m "not slow and not e2e and not network" {{ARGS}}

# Run markdown-svg production-source type checks from repo root so `uv run`
# resolves against the shared root dev-tool venv instead of re-resolving a member-scoped one.
[no-cd]
mypy:
    uv run --python 3.13 mypy --config-file libs/markdown-svg/pyproject.toml libs/markdown-svg

# Run the markdown-svg playground (live editor + SVG preview)
[no-cd]
play port="8765":
    #!/usr/bin/env bash
    set -euo pipefail
    just _kill-port {{port}}
    echo "🎨 Starting markdown-svg playground on http://{{host}}:{{port}}/"
    exec uv run python libs/markdown-svg/playground/server.py --host {{host}} --port {{port}}

# Regenerate playground SVG examples
[no-cd]
generate-svgs:
    uv run python libs/markdown-svg/playground/generate_svgs.py
