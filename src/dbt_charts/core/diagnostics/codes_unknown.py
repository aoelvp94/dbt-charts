"""ERR-INTERNAL: fallback code for unclassified internal failures."""

from __future__ import annotations

from dbt_charts.core.diagnostics.registry import REGISTRY, ErrorCode

ERR_INTERNAL = REGISTRY.register(
    ErrorCode(
        code="ERR-INTERNAL",
        domain="unknown",
        title="Internal error",
        message_template="{message}",
        doc=(
            "Fired when an unclassified internal failure occurs that does not "
            "map to a more specific error code. Check the full traceback for "
            "details. If this appears in normal usage, file a bug report."
        ),
        docs_topic="errors",
    )
)
