"""Write surface over authored YAML, not part of the compile pipeline.

Consumed by Cloud's editing endpoints (`apps/cloud/apps/dashboards/api.py`,
`settings_panel.py`) and by `compile/migrations/migrations.py` to apply
scalar edits back to a board's source YAML without disturbing comments or
formatting.
"""
