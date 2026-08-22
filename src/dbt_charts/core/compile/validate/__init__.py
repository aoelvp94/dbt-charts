"""validate — semantic checks over AuthoredBoard.

Stage: COMPILE (step 2 of 4: parse → validate → normalize → resolve)

`dispatch.validate_board` runs the cross-reference and consistency checks
Pydantic cannot express; `formats` validates authored format strings, and
`authoring_warnings` / `board_warnings` emit the non-fatal authoring
diagnostics registered in `core/diagnostics/codes_compile.py`.

At runtime these run interleaved with `normalize/` rather than as one pass
(see `compiler.py`).

Modules are imported by path (`compile.validate.dispatch`); nothing is
re-exported here.
"""
