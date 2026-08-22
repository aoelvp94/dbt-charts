"""Jinja templating and SQL parameterization for compile-time rendering.

`jinja.py` builds the sandboxed Jinja environment authored SQL and text
render through; `parameterized.py` turns the rendered output into a
parameterized query the execute adapters can bind safely; `_helpers.py`
supplies the Jinja filters/functions both draw on; `labels_env.py` and
`variables.py` cover label templating and board-variable coercion.
"""
