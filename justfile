# dbt charts — standalone development commands.
#
# This file is the OSS repo's root justfile. It is checked in at
# dbt-charts/oss/justfile and exported by copybara with core.move("oss", "")
# (the whole oss/ directory, this file included) — a real reviewable file,
# not a string-patched projection of dbt-charts/mod.just.

host := env_var_or_default("DCT_HOST", "127.0.0.1")
demo_dir := env_var_or_default("DCT_DEMO_DIR", ".demo")

# Two genuinely standalone-incompatible cases, re-audited empirically against
# a real export (everything else in the old, much longer list here turned out
# to already pass standalone once dbt-charts self-contained landed):
#   - test_playground_shim.py: exercises the real dbt-charts-playground
#     package. TEMPORARY: the [playground] extra falls back to PyPI standalone
#     (see copy.bara.sky's matching core.replace) because that package isn't
#     published there yet. Delete once it is.
#   - test_help_option_surface.py's "inspect" case: expects `table`/`audit`,
#     which the private dbt-charts-super-schema plugin registers via an
#     entry-point. Permanent, not temporary -- that package never ships in
#     the OSS wheel. Deselected narrowly (not file-ignored) since the file's
#     other 4 cases pass and cover real OSS-only commands.
monorepo_only := "--ignore=tests/cli/test_playground_shim.py --deselect=tests/cli/test_help_option_surface.py::test_help_documents_option_surface[inspect]"

# Show the main commands
default:
    @echo "dbt charts — development commands"
    @echo ""
    @echo "━━━ SETUP ━━━"
    @echo "  just install            Install all dependencies into .venv"
    @echo ""
    @echo "━━━ TESTING ━━━"
    @echo "  just test [ARGS]        Full test suite (excludes slow/e2e/network)"
    @echo "  just test-file FILE     Run one test file or node id"
    @echo "  just test-windows       Windows-safe release subset (-m windows)"
    @echo ""
    @echo "━━━ CODE QUALITY ━━━"
    @echo "  just fix                Format + lint with auto-fix"
    @echo "  just lint               Format check, lint, model conventions, vulture"
    @echo "  just typecheck          Static type checking (pyright + mypy)"
    @echo "  just tach               Import-boundary checks"
    @echo "  just type-state         Type-state ratchet vs merge-base"
    @echo "  just ci                 lint + typecheck + tach + test"
    @echo ""
    @echo "━━━ RUN ━━━"
    @echo "  just demo [PORT]        Scaffold a demo project and serve it"
    @echo "  just serve DIR [PORT]   Serve an existing project directory"
    @echo ""
    @echo "━━━ GENERATED ARTIFACTS ━━━"
    @echo "  just gen                Regenerate every introspection-derived artifact"
    @echo ""
    @echo "Run 'just --list' for every recipe."

# ============================================
# Setup
# ============================================

# Install all dependencies (every warehouse adapter, mcp, lsp, server extras)
install:
    uv sync --all-extras
    @echo "✅ Ready. Run 'just test' or 'just demo'."

# ============================================
# Testing
# ============================================

# Run the test suite (excludes slow, e2e, and network-marked tests)
test *ARGS: test-windows
    uv run pytest -q --tb=short tests -n auto -m "not slow and not e2e and not network" {{monorepo_only}} {{ARGS}}

# Run one test file or node id
test-file FILE *ARGS:
    uv run pytest -q --tb=short {{FILE}} {{ARGS}}

# Windows-safe release subset. LC_ALL=C + PYTHONUTF8=0 makes a missing
# encoding= raise off Windows, which is the point of the subset.
# -p no:tach: the plugin dies on the non-ASCII pyproject.
test-windows *ARGS:
    LC_ALL=C PYTHONUTF8=0 uv run pytest -q --tb=short -p no:tach tests -m windows {{monorepo_only}} {{ARGS}}

# ============================================
# Code quality
# ============================================

# Format and lint with auto-fix
fix:
    uv run ruff check --fix .
    uv run ruff format .

# Format check, lint, model-convention check, and dead-code scan
lint:
    @echo "▶ format"
    uv run ruff format --check --quiet .
    @echo "▶ lint"
    uv run ruff check --quiet .
    @echo "▶ model conventions"
    uv run python scripts/check_models.py
    @echo "▶ dead code (vulture)"
    uv run vulture

# Static type checking: pyright + mypy. mypy resolves its own config from
# pyproject.toml in cwd; --config-file makes that explicit rather than
# implicit, matching the monorepo's invocation.
typecheck:
    uv run pyright
    uv run mypy --config-file pyproject.toml src/dbt_charts

# Import-boundary checks. `check` enforces internal layering; `check-external`
# enforces the wheel-outbound allowlist against declared dependencies.
# Config lives in tach.toml. Requires `tach` in the dev dependency group.
tach:
    uv run tach check
    uv run tach check-external

# Merge-base ratchet: blocks unmarked growth of silent_fallback / cast /
# type_ignore / object_annotation / explicit_any in src/dbt_charts/core.
type-state *ARGS:
    uv run python scripts/type_state_gate.py {{ARGS}}

# Everything CI gates on
ci: lint typecheck tach test

# ============================================
# Run
# ============================================

# Scaffold a demo project under .demo/ and serve it
demo port="":
    #!/usr/bin/env bash
    set -euo pipefail
    if [ ! -f "{{demo_dir}}/dbt_charts.yml" ]; then
        mkdir -p "{{demo_dir}}"
        uv run dct init -y --project-dir "{{demo_dir}}" \
            --no-skills --no-mcp --no-vscode --no-cursor --no-with-playground
    fi
    port_args=""
    if [ -n "{{port}}" ]; then port_args="--port {{port}}"; fi
    uv run dct serve --project-dir "{{demo_dir}}" --host {{host}} $port_args

# Serve an existing project directory
serve dir port="":
    #!/usr/bin/env bash
    set -euo pipefail
    port_args=""
    if [ -n "{{port}}" ]; then port_args="--port {{port}}"; fi
    uv run dct serve --project-dir "{{dir}}" --host {{host}} $port_args

# ============================================
# Generated artifacts
# ============================================

# Regenerate every introspection-derived artifact. schema-names runs first:
# every other artifact introspects models that read ThemeName / PaletteName /
# ScalePaletteName from it.
gen: generate-schema-names generate-inherit-registry gen-highlight-artifacts gen-board-resolved-schema gen-references

# Regenerate schema_names.py (ThemeName/PaletteName/ScalePaletteName Literals).
# Re-run after adding or removing a theme or palette YAML file.
generate-schema-names:
    uv run python scripts/generate_schema_names.py

# Regenerate inherit_registry.yaml from InheritGraph markers on the Style model.
# Re-run after adding Inherit / InheritSlot annotations to style/theme.py.
generate-inherit-registry:
    uv run python scripts/generate_inherit_registry.py

# Regenerate the highlight manifest (board.json) and tmLanguage grammar.
# Re-run after any change to the authored schema's key structure.
gen-highlight-artifacts:
    uv run python scripts/gen_highlight_artifacts.py

# Regenerate board-resolved.schema.json.
# Re-run after any change to ResolvedBoard or a type it references.
gen-board-resolved-schema:
    uv run python scripts/gen_board_resolved_schema.py

# Regenerate the in-wheel YAML / error / warning reference pages that
# `dct docs` serves. The monorepo also writes an apps/docs copy; standalone
# only the wheel copies exist.
gen-references:
    #!/usr/bin/env bash
    set -euo pipefail
    docs_dir="src/dbt_charts/agent_api/docs"
    uv run python -c 'from dbt_charts.core.compile.schema import get_schema_for_prompt; print(get_schema_for_prompt())' > "$docs_dir/yaml-reference.md"
    uv run python -c 'from dbt_charts.core.diagnostics.render_reference import render_reference; print(render_reference("error", with_anchors=False), end="")' > "$docs_dir/error-reference.md"
    uv run python -c 'from dbt_charts.core.diagnostics.render_reference import render_reference; print(render_reference("warning", with_anchors=False), end="")' > "$docs_dir/warning-reference.md"
    echo "✓ $docs_dir/{yaml,error,warning}-reference.md"

# Freeze a changed YAML grammar under the same version as its dbt charts
# release. Existing snapshots are verified, never rewritten; unchanged
# candidates are a no-op.
freeze-yaml-schema version released_at:
    uv run python -m dbt_charts.schema_release {{version}} {{released_at}}
