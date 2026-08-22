"""Pack proposal models and artifact store.

Transient proposal artifacts live under ``target/dbt_charts/proposals/``
and are never committed. This package defines the contract shapes that
the planner emits and the apply step consumes.
"""
