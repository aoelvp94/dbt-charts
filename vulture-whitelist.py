# pyright: reportUndefinedVariable=false, reportUnusedExpression=false
# vulture-whitelist.py — confirmed dynamic-name false positives.
#
# Each entry MUST have a `# WHY:` line that names the specific dynamic-dispatch
# surface (Django `clean_<field>`, lark `visit_<rule>`, registry `_register("name")`,
# etc.). If you can't write one, the symbol is probably dead — delete it instead
# of whitelisting it.
#
# This file is input to vulture, not runnable Python — entries are bare names
# scattered across the codebase, so the file is not importable. Vulture's own
# `--make-whitelist` emits the same bare-name format. Ruff B018/F821 are
# suppressed for this path in ruff.toml [lint.per-file-ignores].

# === Test-mock kwarg contracts ===
# WHY: monkeypatched in via `setattr(module, "_review_visual_parity", ...)`;
# the real `_review_visual_parity` is called with these kwargs by chart_lab
# compare code, so the fake must accept the same kwarg names.
source_png  # tests/integration/test_chart_lab_compare.py:164
chosen_mark_type  # tests/integration/test_chart_lab_compare.py:164

# === TYPE_CHECKING imports used in string-quoted annotations ===
# WHY: Used in the string-quoted type annotation of `Executor.__init__`'s
# `file_materializer` parameter
# (`file_materializer: "FileSourceMaterializer | None" = None`).
# The import lives under TYPE_CHECKING; vulture can't trace quoted annotations.
FileSourceMaterializer  # src/dbt_charts/core/execute/executor.py:289 (quoted annotation; TYPE_CHECKING import at :89)

# === pymdown-extensions SuperFences callback contract (integrations/markdown.py) ===
# WHY: fence_dbt_charts / fence_dbt_charts_example are registered as
# SuperFences handlers; the library calls every handler with this exact
# positional signature (source, language, class_name, options, md, **kwargs),
# so the params must exist even where these two handlers don't read them.
language  # src/dbt_charts/integrations/markdown.py:402,453 (fence_dbt_charts, fence_dbt_charts_example)
class_name  # src/dbt_charts/integrations/markdown.py:402,453 (fence_dbt_charts, fence_dbt_charts_example)
md  # src/dbt_charts/integrations/markdown.py:402,453 (fence_dbt_charts, fence_dbt_charts_example)

# === Duck-typed adapter stub (tests/core/inspect/test_sources_dbt.py) ===
# WHY: this stub's execute(sql, fetch) matches a real warehouse adapter's
# execute() signature for duck-typing purposes; the stub always returns the
# same fixed result regardless of fetch.
fetch  # tests/core/inspect/test_sources_dbt.py:793 (stub execute())

# === MetricFlow SqlClient Protocol stub (compile/normalize/queries.py) ===
# WHY: _CompileTimeSqlClient must declare these parameter names verbatim to
# satisfy pyright's structural Protocol check against metricflow.protocols.SqlClient.
# The stub methods always raise NotImplementedError — MetricFlowEngine.explain()
# only reads sql_engine_type/sql_plan_renderer, never calls query/execute/dry_run/
# render_bind_parameter_key. Parameter names must match the Protocol for
# keyword-argument compatibility; renaming to _-prefix breaks pyright Protocol conformance.
sql_bind_parameter_set  # src/dbt_charts/core/compile/normalize/queries.py (_CompileTimeSqlClient)
bind_parameter_key  # src/dbt_charts/core/compile/normalize/queries.py (_CompileTimeSqlClient)
