"""parse — YAML/markdown text → AuthoredBoard.

Stage: COMPILE (step 1 of 4: parse → validate → normalize → resolve)

`parser` turns a YAML string into `AuthoredBoard`; `markdown` is the
pre-compile transform that turns a `.md` board into that YAML string.
`meta` loads the `meta.yml` cascade, `source_map` records
line/column provenance for authored keys, and `yaml_error_formatter`
renders parse and schema failures into author-facing messages.

Modules are imported by path (`compile.parse.parser`); nothing is
re-exported here.
"""
