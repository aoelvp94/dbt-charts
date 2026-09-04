# dbt charts

The dbt charts core engine: YAML dashboard compiler, query executor, renderer, HTTP server, and inspector. The CLI (`dct`) and AI/MCP interfaces are thin wrappers over this package's Python APIs.

## Verbs
| Verb | Purpose |
|------|---------|
| `dct validate [PATH]` | Validate board YAML for errors (no DB); default: `charts/` |
| `dct render <board>` | Compile + execute + write static exports |
| `dct query SOURCE 'SELECT …'` | Execute raw SQL and return sample rows (CLI parity with MCP `execute_query`) |
| `dct query board.yaml NAME` | Run a named board query (sample rows) |
| `dct query SOURCE 'SELECT …' --validate` | Static SQL lint for raw SQL in a source context |
| `dct query board.yaml NAME --validate` | Lint the SQL of a named board query |
| `dct query SOURCE 'SELECT …' --describe` | Column schema for a SQL string |
| `dct search <query>` | Search dashboards by keyword with ranked results |
| `dct impact <column>` | Which boards reference a column (reverse index; no DB) |
| `dct serve` | Start local server; use its URL for browser previews |
| `dct examples [SLUG]` | List bundled board specimens, or print one's YAML |
| `dct init` | Bootstrap a dbt charts project |
| `dct init skills` | Install workflow skills for file-based agent auto-discovery |
| `dct init mcp` | Wire up MCP server for AI assistants |
| `dct init ci` | Scaffold a GitHub Actions workflow running `dct validate` on PRs |
| `dct --version` | Print version + install path; first check when output looks stale |

## Quick start
```yaml
charts:
  rev: {query: {sql: "SELECT month, SUM(revenue) FROM orders GROUP BY 1"}, type: bar, x: month, y: revenue}
```
```bash
dct validate charts/rev.yaml && dct render charts/rev.yaml
```

Errors carry doc pointers and `did you mean` hints — follow them. Canonical registry: `dbt_charts/core/diagnostics/`. Every code is `ERR-{SLUG}` (no domain segment in the string — `ErrorCode.domain` carries that); ERR-INTERNAL is a fallback that signals a bug (an unmigrated or wrapped raise site), not an accepted tier — treat any occurrence on a common failure path as a defect.

## Testing

Run the full suite: `just test` (monorepo) / `just test` (standalone export)
Run one test: `uv run pytest dbt-charts/tests/<path>/test_foo.py::test_name -q --tb=short`
(monorepo, from the repo root) / `uv run pytest tests/<path>/test_foo.py::test_name -q
--tb=short` or `just test-file tests/<path>/test_foo.py::test_name` (standalone, from
this package's root)

CI runs `test-dataface.yml` on Python 3.10 + 3.13 (monorepo); the standalone export's
own CI is `test.yml` + `lint.yml`.

When running tests, put the output in a temp file so further searches on the test output can be done without re-running. Repeatedly running tests without code changes is inefficient.

## Type-state gate

`scripts/type_state_gate.py` (`just type-state`; wired into pre-push and CI in
the monorepo — the recipe exists standalone too, but no exported workflow or
pre-commit hook calls it yet) flags a `dbt_charts/core` site iff it is unmarked
**and** its line was added
or modified since `origin/main` (`git diff -M`, rename-aware, against the
working tree) — no committed baseline, so nothing for two branches to
conflict over. `silent_fallback` / `cast` / `type_ignore` /
`object_annotation` / `explicit_any` are blocking (a flagged site fails the
gate); `optional` is report-only (a flagged site only prints — `T | None` is
a contract in this repo, not rot on its own).

**A site is flagged by the line it's on, not by matching its code against
other sites.** Git already solves identity exactly, with rename detection: a
pure `git mv` carries its sites with it for free, and editing a line hands
the gate the same signal a reviewer would get from the diff. The trade-off
this buys: **editing a line that already carries pre-existing unmarked rot
flags it, because you touched it** — even if the rot itself isn't new. Add a
marker or leave the line alone.

To approve growth you believe is genuinely correct, add a marker on any line of
the site's span:

```python
size = cfg.get("width", 320)  # type-state: silent_fallback — CLI default, documented in the docstring
```

A reason is mandatory — reviewed like a `# noqa: BLE001 — <reason>`, not a
silent exemption. A marker with no reason after the em-dash is a hard error,
same as an unknown category name — a reasonless marker left in place would
otherwise look "free" to the gate's marker-line suggestion and swallow a
later, real marker pasted on the same line with no diagnostic. The separator
must be an em-dash (`—`); a hyphen or en-dash also hard-errors rather than
silently failing to approve, since a hyphen is the likely default given the
"never use em or en dashes" instruction elsewhere in this file — which does
not apply to this marker.

Only one marker is honored per physical line. Read
`docs/contributing/type-state-gate-markers.md` before marking a line that
carries more than one rot site (same category or different) — the mechanics
there are not needed for the common one-site-per-line case.

## Comments

- Comments should only be relevant to the open source library, not other Fivetran concerns like how it is hosted.

## Key files

- `core/compile/` — YAML → normalized document
- `core/execute/` — run queries against databases
- `core/render/` — normalized doc → output (HTML, SVG, etc.)
- `core/serve/` — HTTP server for dashboards
- `core/inspect/` — schema inspection / table profiling (powers `dct inspect` and the `/data` browser)
- `core/registered_views/` — route→template→generated-board mechanism that powers the `/data/` browser; each *registered view* matches a URL pattern, runs optional pre-template queries, and renders an auto-generated board. Not to be confused with the `/data/` surface itself (user-facing) or `plan_entity_variables` (which uses a different, unrelated meaning of "entity"). **Reserved slug prefixes:** `data/` and `inspector/` route to the built-in registered-view system views (the `/data/` browser + schema inspector) on both hosts. Don't name user boards with these prefixes — they collide with the built-in handlers (a board *file* at the prefix is shadowed by the router; a real `charts/data/` *directory* is still directory-listed in `dct serve`). Cloud mounts them under `/d/` alongside dashboards.
- `src/dbt_charts/core/render/chart/AGENTS.md` — **canonical chart-rendering philosophy and render-layer invariants** (its `## Implementation philosophy`)
- `cli/` — `dct` command-line interface (thin wrapper)
- `ai/` — AI/MCP interfaces (thin wrappers)
- `agent_api/` — typed Python API every CLI and MCP verb delegates to
- `integrations/` — external integrations (Pygments lexer for board YAML, markdown, etc.)
- `core/compile/schema/renderers/` — schema IR → derived artifacts (JSON Schema, highlight manifest, TextMate grammar)
- `data/highlighting/board.json` — **committed highlight manifest** (single source of truth for top-level keys, enum values, SQL block scalar keys). Regenerate with `just gen-highlight-artifacts` after model changes.
- `core/defaults/themes/*.yaml`, `core/defaults/palettes/`, `core/defaults/default_config.yml` — themes, palettes, and default config (chart-level defaults live in theme YAML). Adding or removing a theme/palette YAML file also requires `just generate-schema-names` (regenerates `core/compile/models/schema_names.py`'s `ThemeName`/`PaletteName`/`StopsPaletteName`/`ScalePaletteName`).
- `oss/uv.lock` — **committed standalone lock** for the Copybara OSS export (Copybara only moves files; it can't run `uv`). Regenerate with `just oss-lock` after changing dbt-charts' dependencies, extras, or dev group; `tests/packaging/test_oss_uv_lock.py` fails when it drifts.

## Visual regression testing — golden approval rule

**Monorepo-only.** `tests/visual/` and its 143 committed goldens are excluded from
the standalone export (the manifest discovers most of its cases from
`apps/docs/docs/**`, another package's content). Every recipe named in this
section — `viz-review`, `visual-approve`, `review` — is a monorepo
`justfile`/`mod.just` recipe with no standalone equivalent; none of them exist
in a standalone `dbt-charts` checkout.

**If your change causes a golden file to be updated, you MUST run `just viz-review` before pushing.** The CI gate checks that `sha256(golden bytes)` matches an APPROVED viz-review artifact added on the branch. Without it, the `visual` CI job fails.

Workflow when a render changes:
1. Approve the golden on macOS: run the monorepo's visual-approve recipe (`just visual-approve`, or `-k <case>`)
2. Commit the updated golden file
3. Run AI visual review: `just viz-review --task-path <task-path>`
   — **from the worktree holding the changed goldens.** It diffs the working branch
   against its merge-base, so from another checkout it prints `no snapshot changes
   detected — nothing to review` and exits 0: a silent no-op, not an error.
4. If the verdict is APPROVED, commit the artifact in `tasks/activity/viz-reviews/`
5. Push — the pre-push hook will verify the sha256 approval gate

The pre-push hook (`scripts/visual_approval_gate.py`) enforces this without an LLM call.

Both this and `just review` shell out to `claude -p`. They use `ANTHROPIC_API_KEY`
when it is set and otherwise fall back to the CLI's own auth — see `.env.example` for
why it belongs in `.env` rather than exported from `~/.zshrc`.

## Implementation philosophy

**Render-layer invariants live in `src/dbt_charts/core/render/chart/AGENTS.md`** — re-read its `## Implementation philosophy` before adding anything to the render layer that touches data shape.

**Don't pin theme/default values in tests.** Theme values (`page_canvas == "#fafafa"`, `bar.size == 20`, `compiled_style.border.radius == 8`) and chart defaults are tunable. Patterns like `assert page_canvas == "#fafafa"` fail on any legitimate default tweak and add zero signal beyond what existing behavior tests catch. Test structure, presence, behavior under override, and pipeline correctness instead.

**Also don't assert deletion or absence of Python symbols.** `assert not hasattr(...)`, source-grep for removed functions — that's testing Python, not our logic.

**Test file names mirror the src path.** `dbt-charts/src/dbt_charts/agent_api/search.py` → `dbt-charts/tests/agent_api/test_search.py`.

**Avoid bare-star keyword-only separators (`*`) in function signatures.** Private functions (`_name`) must never use `*`. Public functions: only reach for it when argument order at the call site would be genuinely ambiguous without keyword labels — not as a blanket API-stability hedge. Never force `foo(x=x)` when the variable name already makes the intent clear; pass positionally instead.

**Canonical architecture docs.** Maintainer-grade pages live under `docs/contributing/architecture/`. Use those and package `AGENTS.md` files rather than expanding inline guidance here.

**New author-surface fields are reviewed, not free.** Boards, charts, and themes are a public contract — the JSON Schema, docs, and highlight manifest all derive from it, and removing a field later breaks every dashboard that authored it. Before adding a field, try hard to reuse or slightly reshape an existing field's semantics instead (see the accepted/rejected chart-field table in `src/dbt_charts/core/AGENTS.md`). A diff touching `apps/docs/docs/reference/yaml-reference.md` or `dbt-charts/src/dbt_charts/agent_api/docs/yaml-reference.md` should carry a stated reason an existing field couldn't cover the need — question new entries there in review, don't wave them through.

**No internal decision identifiers in shipped artifacts.** Design-doc section labels (`C7`, `S3`, `D12`, etc.) are internal planning shorthand — they must not appear in code, tests, docstrings, AGENTS.md files, or any artifact that ships in the package or is visible to contributors. Use a plain description instead.

### agent_api thin-wrapper rule

`dbt-charts/src/dbt_charts/agent_api/` is the canonical home for every function exposed to agents via CLI or MCP. Functions there must have typed args and typed returns (no `dict[str, Any]`, no JSON strings), no Cloud/Django imports, and I/O scoped to what the verb implies.

**`cli/commands/` and `ai/mcp/` are thin wrappers — they may only:**
1. Parse / validate arguments
2. Call a function from `dbt_charts.agent_api`
3. Format the result for output

Any validation, path resolution, compilation, execution, or rendering in these layers is a violation. A PR that adds a new `dct <verb>` without a corresponding `agent_api` function is rejected — **except `dct cloud` verbs**, whose one call is into `dbt_charts.cloud_client` instead (below), never `agent_api`: `agent_api` is local-by-contract (no network, no Django) and `cloud_client` is the only module that talks to Cloud. A PR that adds business logic to a CLI command file or MCP server module is rejected.

### Module boundaries

tach enforces: `dbt_charts.cli` may depend only on `dbt_charts.agent_api` and `dbt_charts.cloud_client` (both explicit `depends_on` edges on unlayered modules — in tach 0.35, layer ordering implicitly allows skip-level and same-layer edges, so this is the enforcing shape); `dbt_charts.cloud_client` may import nothing first-party at all (`cli/commands/cloud.py` parses arguments, calls one client method, prints the result — same thin-wrapper rule, `cloud_client`'s networked sibling of `agent_api`); `dbt_charts.core` cannot import `dbt_charts.cli` or `dbt_charts.ai` (layer ordering); `dbt_charts.ai.tools` cannot import `dbt_charts.ai.mcp`.

`dbt_charts.cli` → `dbt_charts.core` is forbidden — route through `dbt_charts.agent_api`. The remaining direct import (`commands/mcp.py`'s lazy `dbt_charts.ai.mcp` import) carries a `# tach-ignore(cli->ai debt…)` marker; the burn-down task deletes it.

## Product skills (`dbt_charts/ai/skills/`)

Skills under `dbt_charts/ai/skills/` ship in the wheel and are the knowledge product dbt charts offers to AI agents. They are different from the contributor-facing `.claude/skills/` skills (which guide the humans + agents working *on* the repo, not consumers of the wheel).

### How agents reach them

The CLI verbs (bare `dct`, as a customer would invoke them):

```bash
dct skills                # list all product skills
dct skills <name>         # print one skill's SKILL.md body
dct docs                  # topic catalog (bare) or cheatsheet overview
dct docs <topic>          # one H2 section (board, queries, charts, variables, layout, getting-started, errors, …)
dct docs all              # full reference file
dct docs --search <q>     # full-text search across all topics
dct examples              # list bundled board specimens
dct examples <slug>       # print one specimen's board YAML (e.g. boards/kpi-overview)
dct examples --search <q> # search slugs, titles, and specimen YAML
```

`dct examples` is the third knowledge surface: skills give workflow prose, docs
give field reference, examples give a whole working board to copy. Specimens
live in `dbt_charts/ai/examples/<category>/` and every one renders standalone —
inline `columns`/`values` data, no `source:` — so an agent can paste one into a
project the wheel knows nothing about.

Topics are sliced from `dbt-charts/src/dbt_charts/DBT_CHARTS_SYNTAX.md` (single source).

In-repo agent guidance — including any `AGENTS.md` / `CLAUDE.md` in this repo — should point at these CLI verbs rather than at the on-disk markdown files. The CLI is the dogfooded surface; pointing at file paths invites stale copies.

### Convention: `dct` vs `uv run dct`

Two surfaces, two conventions — keep them straight:

- **Inside `dbt_charts/ai/skills/*/SKILL.md`** (the wheel-shipped product skills, read by customer-environment agents): use **bare `dct`**. Customer installs put `dct` on the venv's `PATH` via `pip install dbt-charts`, and `uv` may not be on their `PATH`.
- **Inside this repo** (contributor `AGENTS.md` / `CLAUDE.md` / task worksheets / `ai_notes/`): use **`uv run dct`**. The repo's `.venv` is not auto-activated for every shell, and bare `dct` will hit a stale `PATH` install. The `uv run` prefix forces resolution against this worktree's environment.

When the same content appears in both places (e.g. quoting a `dct docs` example in a worksheet), pick the form that matches the document's audience, not the lowest common denominator.

`cli/_workspace_guard.py` makes a violation of that second rule visible: inside a checkout that contains the package, `dct` warns to stderr when the running build didn't come from that checkout's own editable install. It never fails the command. Two limits worth knowing: a build published before the guard existed stays silent wherever it answers from, and the probe reads the source tree rather than the install, so a pip-installed `dct` run from inside a clone of the public export warns too. Machine stderr consumers set `DCT_NO_WORKSPACE_GUARD=1` (the extension's preview spawn and the CI smoke job do) — the advisory's non-JSON first line otherwise corrupts a `--diagnostics-json` parse.

### Authoring a product skill

Before writing or renaming a skill under `dbt_charts/ai/skills/`, read `docs/contributing/product-skills-authoring.md` — surface macros (`{{ s_X }}` + `surface_aliases.yaml`), the `<object>-<action>` naming standard, and the required `kind: workflow | pattern` frontmatter.
