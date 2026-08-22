"""normalize — AuthoredBoard → Board.

Stage: COMPILE (step 3 of 4: parse → validate → normalize → resolve)

`dispatch.normalize_board` is the entry point; `charts`, `layout`,
`queries`, and `variables` hold the per-concern transforms it drives,
with `single_series_allocation` and `chart_focus` as narrower helpers.
`sql_authoring_lint` lives here because its only consumer is `queries`.

Validation is not a separate pass at runtime — `compiler.py` interleaves
`validate/` checks with these transforms. `validate/` is a sibling package
because the checks are one concern by content, not because they run as a
distinct stage.

Modules are imported by path (`compile.normalize.dispatch`); nothing is
re-exported here, which keeps `compiler.py` and `models/board/normalized.py`
free of an import cycle through this package.
"""
